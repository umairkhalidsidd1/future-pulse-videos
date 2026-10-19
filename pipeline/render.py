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


IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")


def probe_info(path: Path) -> tuple[float, int, int]:
    """(duration in seconds, width, height) of a video file. Photos count as endless."""
    if path.suffix.lower() in IMAGE_EXT:
        from PIL import Image
        try:
            with Image.open(path) as im:
                return 999.0, im.width, im.height
        except OSError:
            return 0.0, 0, 0
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


TAIL = 0.5  # seconds of picture after the last word
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
        if job["clip"].suffix.lower() in IMAGE_EXT:     # a photo: loop it as a still video
            inp = ["-loop", "1", "-framerate", str(fps), "-i", str(job["clip"])]
        else:
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


def _pop(rate: int) -> np.ndarray:
    """Short soft 'pop' (pitch-dropping sine) for a card appearing."""
    t = np.arange(int(rate * 0.09)) / rate
    tone = np.sin(2 * np.pi * (900 - 3500 * t) * t) * np.exp(-t * 45)
    return (tone * 0.35).astype(np.float32)


def _impact(rate: int) -> np.ndarray:
    """Low 'boom' for a number landing: decaying 55 Hz sine plus a little noise."""
    t = np.arange(int(rate * 0.6)) / rate
    boom = np.sin(2 * np.pi * (55 + 30 * np.exp(-t * 12)) * t) * np.exp(-t * 7)
    hit = np.random.default_rng(3).standard_normal(len(t)) * np.exp(-t * 60) * 0.25
    return ((boom + hit) * 0.55).astype(np.float32)


def _riser(rate: int, length: float = 1.0) -> np.ndarray:
    """Rising noise sweep that ends exactly on a reveal."""
    w = _whoosh(rate, length)
    env = np.linspace(0.15, 1.0, len(w)) ** 2
    return (w * env * 0.8).astype(np.float32)


def _sfx_track(events: list[tuple[float, str]], total: float, path: Path, rate: int = 48000):
    """events: (time in seconds, 'whoosh' | 'pop' | 'impact' | 'riser'). A riser ENDS at its time."""
    track = np.zeros(int(rate * (total + 1)), dtype=np.float32)
    if CFG["audio"].get("whoosh"):
        sounds = {"whoosh": (_whoosh(rate), 0.2), "pop": (_pop(rate), 0.0), "impact": (_impact(rate), 0.0)}
        riser = _riser(rate)
        sounds["riser"] = (riser, len(riser) / rate)
        for t, kind in events:
            snd, lead = sounds[kind]
            i = max(0, int((t - lead) * rate))
            track[i:i + len(snd)] += snd[: len(track) - i]
    sf.write(path, np.clip(track, -1, 1), rate)


def sound_events(timings, cards: list[dict] | None, fps: int, whoosh_scenes: set[int] | None) -> list:
    """Where the sound effects go: a pop when a card appears, a riser into headline/slam cards, an impact when
    a number lands, a whoosh at scene changes without a card (not every effect everywhere: it gets tiring)."""
    events, card_times = [], []
    for c in cards or []:
        t = c["from"] / fps
        card_times.append(t)
        if c["template"] in ("headline", "slam"):
            events.append((t, "riser"))
        if c["template"] == "stat":
            events.append((t + 1.1, "impact"))
        if c["template"] not in ("chapter",):
            events.append((t, "pop"))
    for i in range(1, len(timings)):
        t = timings[i][0]
        if (whoosh_scenes is None or i in whoosh_scenes) and not any(abs(t - ct) < 0.4 for ct in card_times):
            events.append((t, "whoosh"))
    return events


def ensure_music():
    """Downloads the licensed tracks listed in config.yaml once (GitHub caches the folder)."""
    import urllib.parse
    import requests
    a = CFG["audio"]
    folder = ROOT / a["music_dir"]
    folder.mkdir(parents=True, exist_ok=True)
    for name in a.get("music_tracks", []):
        path = folder / f"{name}.mp3"
        if path.exists() and path.stat().st_size > 100_000:
            continue
        try:
            r = requests.get(a["music_url"] + urllib.parse.quote(name) + ".mp3", timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
            print(f"  [music] downloaded {name}")
        except requests.RequestException as e:
            print(f"  [music] could not download {name}: {e.__class__.__name__}")


def _music(seed: str, mood: str | None = None) -> Path | None:
    ensure_music()
    a = CFG["audio"]
    folder = ROOT / a["music_dir"]
    tracks = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg"))
    pool = [t for t in tracks if t.stem in a.get("music_moods", {}).get(mood or "", [])]
    choices = pool or tracks
    return random.Random(seed).choice(choices) if choices else None


def music_bed(music: Path, words: list[dict] | None, total: float, path: Path, seed: str, long: bool,
              rate: int = 48000):
    """The music, with its volume set word by word: low under the voice, up in pauses and at the very start,
    so it never fights the narration. Starts at a random point of the track (skips the slow intro)."""
    p = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(music), "-ac", "1", "-ar", str(rate),
                        "-f", "f32le", "-"], capture_output=True)
    song = np.frombuffer(p.stdout, dtype=np.float32)
    n = int(rate * total)
    if len(song) < rate:
        song = np.zeros(n, dtype=np.float32)
    start = random.Random(seed).randint(0, max(0, min(len(song) - n, int(len(song) * 0.4))))
    bed = np.resize(song[start:] if len(song) - start >= n else song, n).astype(np.float32)
    a = CFG["audio"]
    under, gap, open_db = a.get("music_under_voice_db", -26), a.get("music_in_pauses_db", -17), -14
    gain = np.full(n, 10 ** (gap / 20), dtype=np.float32)
    for w in words or []:                       # under the voice while words are spoken
        i, j = int(max(0, w["s"] - 0.08) * rate), int((w["e"] + 0.12) * rate)
        gain[i:j] = 10 ** (under / 20)
    gain[: int(rate * 0.9)] = np.maximum(gain[: int(rate * 0.9)], 10 ** (open_db / 20))   # louder first second
    ramp = int(rate * 0.12)
    gain = np.convolve(gain, np.ones(ramp) / ramp, mode="same").astype(np.float32)        # smooth 120 ms fades
    if long:                                     # long videos fade out at the end; Shorts loop, so no fade
        f = int(rate * 2.5)
        gain[-f:] *= np.linspace(1, 0, f)
    sf.write(path, bed * gain, rate)


def plan_shots(*, kind: str, scenes: list[dict], timings: list[tuple[float, float]], total: float, stock,
               seed: str, words: list[dict] | None = None) -> list[dict]:
    """Cut list for the whole video: which clip plays when, from which moment, with which motion.
    Cuts land exactly on the start of a spoken word (like an editor cutting on the beat)."""
    spec = CFG[kind]
    fps, cut = spec["fps"], spec["cut_seconds"]
    rng = random.Random(seed)
    end_all = total + TAIL
    plan = []
    for i, (scene, (s0, _)) in enumerate(zip(scenes, timings)):
        s_end = timings[i + 1][0] if i + 1 < len(timings) else end_all
        start = 0.0 if i == 0 else s0
        dur = s_end - start
        plan.append((start, dur, max(1, round(dur / (cut * rng.uniform(0.85, 1.15))))))
    all_clips = stock.clips_for_scenes(scenes, [n for _, _, n in plan])
    shots, lengths = [], {}
    for i, ((start, dur, n), clips) in enumerate(zip(plan, all_clips)):
        starts = [w["s"] for w in (words or []) if w["scene"] == i and start + 0.6 < w["s"] < start + dur - 0.6]

        def snap(t: float) -> float:
            near = min(starts, key=lambda x: abs(x - t), default=None)
            return near if near is not None and abs(near - t) < 0.6 else t
        bounds = [start] + [snap(start + dur * k / n) for k in range(1, n)] + [start + dur]
        for k in range(n):
            a = round(bounds[k] * fps)
            b = round(bounds[k + 1] * fps)
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
            if clip and clip.suffix.lower() not in IMAGE_EXT:
                room = clip_len - need
                offset = rng.uniform(0, room) if room > 0 else 0.0
            shots.append({"scene": i, "from": a, "frames": b - a, "clip": clip, "offset": offset,
                          "clip_size": lengths[clip][1:] if clip else (0, 0),
                          "pan": rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (0.6, 0.6), (-0.6, 0.6)]),
                          "motion": rng.choices(["zoom_in", "pan", "zoom_out"], weights=[4, 3, 2])[0],
                          "colors": PLACEHOLDER_COLORS[i % len(PLACEHOLDER_COLORS)]})
    return shots


def mix(*, video_only: Path, voice_wav: Path, timings, total: float, work: Path, out_path: Path, seed: str,
        fps: int, whoosh_scenes: set[int] | None = None, ass_path: Path | None = None, words=None, cards=None,
        mood: str | None = None, long: bool = False):
    """Final file: picture + voice + sound effects + music bed, loudness-normalised for social platforms."""
    end_all = total + TAIL
    sfx = work / "sfx.wav"
    _sfx_track(sound_events(timings, cards, fps, whoosh_scenes), end_all, sfx)
    music = _music(seed, mood)
    a = CFG["audio"]
    inputs = ["-i", str(video_only), "-i", str(voice_wav), "-i", str(sfx)]
    graph = [f"[2:a]aresample=48000,volume=0.55,atrim=0:{end_all:.3f}[sx]"]
    finish = CFG.get("render", {}).get("finish_look", True)
    look = "noise=alls=5:allf=t,vignette=angle=PI/6"   # light film grain + soft vignette
    if ass_path:
        ass_rel = os.path.relpath(ass_path, ROOT).replace("\\", "/").replace(":", "\\:")
        fonts_rel = os.path.relpath(ASSETS / "fonts", ROOT)
        graph.insert(0, f"[0:v]ass='{ass_rel}':fontsdir='{fonts_rel}'" + (f",{look}" if finish else "") + "[v]")
    elif finish:
        graph.insert(0, f"[0:v]{look}[v]")
    if ass_path or finish:
        vmap, vcodec = ["-map", "[v]"], ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-profile:v", "high",
                                         "-pix_fmt", "yuv420p", "-maxrate", "12M", "-bufsize", "24M", "-r", str(fps)]
    else:  # picture is already finished (Remotion): copy it untouched
        vmap, vcodec = ["-map", "0:v"], ["-c:v", "copy"]
    voice = f"[1:a]aresample=48000,apad=whole_dur={end_all:.3f}[vo]"
    if music:
        bed = work / "music_bed.wav"
        music_bed(music, words, end_all, bed, seed, long)
        inputs += ["-i", str(bed)]
        graph += [voice, "[3:a]aresample=48000[md]", "[vo][sx][md]amix=inputs=3:duration=first:normalize=0[mix]"]
        print(f"  [render] music: {music.name} ({mood or 'any'} mood)")
    else:
        graph += [voice, "[vo][sx]amix=inputs=2:duration=first:normalize=0[mix]"]
    graph.append(f"[mix]loudnorm=I={a['loudness_lufs']}:TP=-1.5:LRA=11,aresample=48000[a]")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph),
         *vmap, "-map", "[a]", "-t", f"{end_all:.3f}", *vcodec,
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)])
    fix_loudness(out_path, a["loudness_lufs"])


def loudness(path: Path) -> float | None:
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    found = [float(x) for x in __import__("re").findall(r"^\s+I:\s+(-?[\d.]+) LUFS", p.stderr, flags=8)]
    return found[-1] if found else None


def fix_loudness(path: Path, target: float):
    """One-pass loudnorm lands 1-2 dB off; measure the finished file and correct it exactly (video copied)."""
    now = loudness(path)
    if now is None or abs(now - target) < 0.5:
        return
    tmp = path.with_suffix(".loud.mp4")
    run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path), "-map", "0:v", "-map", "0:a", "-c:v", "copy",
         "-af", f"volume={target - now:.2f}dB,alimiter=limit=0.89:level=false", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-movflags", "+faststart", str(tmp)])
    tmp.replace(path)
    print(f"  [render] loudness {now:.1f} -> {loudness(path):.1f} LUFS")


def render(*, kind: str, scenes: list[dict], timings: list[tuple[float, float]], total: float,
           voice_wav: Path, ass_path: Path, stock, work: Path, out_path: Path, seed: str,
           whoosh_scenes: set[int] | None = None) -> list[Path]:
    """The simple FFmpeg engine (backup): stock clips + burned-in captions. Returns the segment files."""
    spec = CFG[kind]
    w, h, fps = spec["width"], spec["height"], spec["fps"]
    seg_dir = work / "segments"
    shutil.rmtree(seg_dir, ignore_errors=True)
    seg_dir.mkdir(parents=True)
    shots = plan_shots(kind=kind, scenes=scenes, timings=timings, total=total, stock=stock, seed=seed)
    jobs = [{**sh, "w": w, "h": h, "fps": fps, "out": seg_dir / f"{i:04d}.mp4"} for i, sh in enumerate(shots)]
    workers = max(1, (os.cpu_count() or 2) // 2)
    print(f"  [render] {len(jobs)} cuts, {workers} at a time")
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(_segment, jobs))
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{j['out'].resolve()}'\n" for j in jobs))
    video_only = work / "video_only.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy",
         str(video_only)])
    mix(video_only=video_only, voice_wav=voice_wav, timings=timings, total=total, work=work, out_path=out_path,
        seed=seed, fps=fps, whoosh_scenes=whoosh_scenes, ass_path=ass_path)
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
