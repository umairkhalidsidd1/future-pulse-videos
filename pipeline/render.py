"""Builds the final video with FFmpeg: fast cuts, slow pans, captions, voice, music and whooshes."""
import json
import math
import os
import random
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import ASSETS, CFG, ROOT

PLACEHOLDER_COLORS = [("0x0f2027", "0x2c5364"), ("0x1a0533", "0x3b1c6e"), ("0x0b1d3a", "0x0f5e7a"),
                      ("0x231942", "0x5e548e"), ("0x101820", "0x1f4068")]


def run(cmd: list[str]):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:8])} ...\n{p.stderr[-1500:]}")


def probe_info(path: Path) -> tuple[float, int, int]:
    """(duration in seconds, width, height) of a video file."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        data = json.loads(p.stdout)
        st = data["streams"][0]
        return float(data["format"]["duration"]), int(st["width"]), int(st["height"])
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        return 0.0, 0, 0


def probe_duration(path: Path) -> float:
    return probe_info(path)[0]


GRADE = "eq=contrast=1.07:saturation=1.25:brightness=0.01"  # punchier colours, like big channels


def _segment(job: dict):
    """Render one cut from a stock clip (or a moving gradient if there is none).

    Tall clip in a tall video, or wide clip in a wide video: fill the frame with a gentle zoom or pan.
    Wide clip in a tall Short: show most of the clip in the middle over a blurred copy of itself,
    instead of cropping it hard (which looks far too zoomed in)."""
    w, h, fps, frames = job["w"], job["h"], job["fps"], job["frames"]
    dur = frames / fps
    hold = f"tpad=stop_mode=clone:stop_duration={dur + 1:.2f},fps={fps}"
    end = "setsar=1,format=yuv420p"
    graph = None
    if job["clip"]:
        cw, ch = job["clip_size"]
        wide_in_tall = h > w and cw > ch
        if wide_in_tall:
            fh = int(h * 0.5) // 2 * 2                        # half the screen tall
            fw = max(w, int(fh * cw / ch) // 2 * 2)          # ~63% of a 16:9 clip's width shows
            x = f"(iw-{w})/2+{job['pan'][0] or 0.6}*(iw-{w})/2*(t/{dur:.3f}*2-1)"
            top = int(h * 0.44 - fh / 2) // 2 * 2
            graph = (f"[0:v]{hold},split[a][b];"
                     f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                     f"boxblur=40:2,eq=brightness=-0.10:saturation=1.2[bg];"
                     f"[b]scale={fw}:{fh},crop={w}:{fh}:'{x}':0,{GRADE}[fg];"
                     f"[bg][fg]overlay=0:{top},{end}[v]")
        elif job["motion"] == "pan":
            zw, zh = int(w * 1.06) // 2 * 2, int(h * 1.06) // 2 * 2
            dx, dy = job["pan"]
            x = f"(iw-{w})/2+{dx}*(iw-{w})/2*(t/{dur:.3f}*2-1)"
            y = f"(ih-{h})/2+{dy}*(ih-{h})/2*(t/{dur:.3f}*2-1)"
            vf = (f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={w}:{h}:'{x}':'{y}',"
                  f"{hold},{GRADE},{end}")
        else:  # slow zoom in or out; working at 1.5x size keeps the zoom smooth (no jitter)
            bw, bh = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
            z0, z1 = (1.0, 1.08) if job["motion"] == "zoom_in" else (1.08, 1.0)
            z = f"{z0}+({z1 - z0:.2f})*on/{max(1, frames - 1)}"
            vf = (f"scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},{hold},"
                  f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps},"
                  f"{GRADE},{end}")
        inp = ["-ss", f"{job['offset']:.2f}", "-i", str(job["clip"])]
    else:
        c0, c1 = job["colors"]
        inp = ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0={c0}:c1={c1}:speed=0.015:r={fps}:d={dur + 1:.2f}"]
        vf = f"fps={fps},{end}"
    filt = ["-filter_complex", graph, "-map", "[v]"] if graph else ["-vf", vf]
    run(["ffmpeg", "-y", "-v", "error", *inp, *filt, "-frames:v", str(frames), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "2", str(job["out"])])


def _whoosh(rate: int, length: float = 0.45) -> np.ndarray:
    """A synthetic whoosh (filtered noise sweep), so there are no sound-effect copyright issues."""
    n = int(rate * length)
    t = np.linspace(0, 1, n)
    noise = np.random.default_rng(7).standard_normal(n)
    # Sweep a simple one-pole low-pass filter from dark to bright.
    out = np.zeros(n)
    y = 0.0
    alpha = 0.02 + 0.5 * t ** 1.5
    for i in range(n):
        y += alpha[i] * (noise[i] - y)
        out[i] = y
    env = np.sin(np.pi * t) ** 2
    out *= env
    return (out / (np.max(np.abs(out)) or 1) * 0.5).astype(np.float32)


def _sfx_track(times: list[float], total: float, path: Path, rate: int = 48000):
    track = np.zeros(int(rate * (total + 1)), dtype=np.float32)
    if CFG["audio"].get("whoosh"):
        w = _whoosh(rate)
        for t in times:
            i = max(0, int((t - 0.2) * rate))
            track[i:i + len(w)] += w[: len(track) - i]
    sf.write(path, track, rate)


def _music(seed: str) -> Path | None:
    folder = ROOT / CFG["audio"]["music_dir"]
    tracks = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg"))
    return random.Random(seed).choice(tracks) if tracks else None


def render(*, kind: str, scenes: list[dict], timings: list[tuple[float, float]], total: float,
           voice_wav: Path, ass_path: Path, stock, work: Path, out_path: Path, seed: str,
           whoosh_scenes: set[int] | None = None) -> list[Path]:
    """Returns the list of rendered segment files (the first one is handy for thumbnails)."""
    spec = CFG[kind]
    w, h, fps, cut = spec["width"], spec["height"], spec["fps"], spec["cut_seconds"]
    rng = random.Random(seed)
    tail = 0.5
    end_all = total + tail
    seg_dir = work / "segments"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True)

    jobs, lengths = [], {}
    plan = []
    for i, (scene, (s0, _)) in enumerate(zip(scenes, timings)):
        s_end = timings[i + 1][0] if i + 1 < len(timings) else end_all
        start = 0.0 if i == 0 else s0
        dur = s_end - start
        plan.append((start, dur, max(1, round(dur / (cut * rng.uniform(0.85, 1.15))))))
    all_clips = stock.clips_for_scenes(scenes, [n for _, _, n in plan])
    for i, ((start, dur, n), clips) in enumerate(zip(plan, all_clips)):
        colors = PLACEHOLDER_COLORS[i % len(PLACEHOLDER_COLORS)]
        for k in range(n):
            a = round((start + dur * k / n) * fps)
            b = round((start + dur * (k + 1) / n) * fps)
            if b <= a:
                continue
            need = (b - a) / fps + 0.2
            clip, clip_len = None, 0.0
            for c in (clips[(k + j) % len(clips)] for j in range(len(clips))):  # prefer a clip long enough
                c_len = lengths.setdefault(c, probe_info(c))[0]
                if clip is None or (clip_len < need <= c_len):
                    clip, clip_len = c, c_len
                if clip_len >= need:
                    break
            offset = 0.0
            if clip:
                room = clip_len - need
                offset = rng.uniform(0, room) if room > 0 else 0.0
            pan = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (0.6, 0.6), (-0.6, 0.6)])
            motion = rng.choices(["zoom_in", "pan", "zoom_out"], weights=[4, 3, 2])[0]
            jobs.append({"w": w, "h": h, "fps": fps, "frames": b - a, "clip": clip, "offset": offset,
                         "pan": pan, "motion": motion, "clip_size": lengths[clip][1:] if clip else (0, 0),
                         "colors": colors, "out": seg_dir / f"{len(jobs):04d}.mp4"})

    workers = max(1, (os.cpu_count() or 2) // 2)
    print(f"  [render] {len(jobs)} cuts, {workers} at a time")
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(_segment, jobs))

    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{j['out'].resolve()}'\n" for j in jobs))
    video_only = work / "video_only.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy",
         str(video_only)])

    whoosh_at = [timings[i][0] for i in range(1, len(timings)) if whoosh_scenes is None or i in whoosh_scenes]
    sfx = work / "sfx.wav"
    _sfx_track(whoosh_at, end_all, sfx)

    music = _music(seed)
    a = CFG["audio"]
    inputs = ["-i", str(video_only), "-i", str(voice_wav), "-i", str(sfx)]
    ass_rel = os.path.relpath(ass_path, ROOT).replace("\\", "/").replace(":", "\\:")
    fonts_rel = os.path.relpath(ASSETS / "fonts", ROOT)
    graph = [f"[0:v]ass='{ass_rel}':fontsdir='{fonts_rel}'[v]",
             f"[2:a]aresample=48000,volume=0.55,atrim=0:{end_all:.3f}[sx]"]
    voice = f"[1:a]aresample=48000,apad=whole_dur={end_all:.3f}"
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        graph += [f"{voice},asplit=2[vo][vk]",
                  f"[3:a]aresample=48000,volume={a['music_volume']},atrim=0:{end_all:.3f}[m]",
                  "[m][vk]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[md]",
                  "[vo][sx][md]amix=inputs=3:duration=first:normalize=0[mix]"]
        print(f"  [render] music: {music.name}")
    else:
        graph += [f"{voice}[vo]", "[vo][sx]amix=inputs=2:duration=first:normalize=0[mix]"]
    graph.append(f"[mix]loudnorm=I={a['loudness_lufs']}:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph),
         "-map", "[v]", "-map", "[a]", "-t", f"{end_all:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high", "-pix_fmt", "yuv420p",
         "-maxrate", "12M", "-bufsize", "24M", "-r", str(fps),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)])
    return [j["out"] for j in jobs]


def chapter_times(timings, scene_ranges: list[tuple[str, int]]) -> str:
    """scene_ranges: [(chapter title, first scene index)] -> 'm:ss Title' lines."""
    lines = []
    for title, idx in scene_ranges:
        t = 0 if not lines else timings[idx][0]
        lines.append(f"{int(t // 60)}:{int(t % 60):02d} {title}")
    return "\n".join(lines)


def fmt_seconds(t: float) -> str:
    return f"{int(t // 60)}:{int(math.floor(t % 60)):02d}"
