"""The pro engine: Remotion (React, in remotion/) draws footage, news cards and captions from a JSON shot list.
FFmpeg then adds the sound mix. If Remotion fails, main.py falls back to the simple FFmpeg engine."""
import json
import os
import random
import resource
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import render as ff
from .captions import _groups
from .config import CFG, ROOT, workers

REMOTION = ROOT / "remotion"
CARD_TEMPLATES = {"headline", "stat", "compare", "list", "quote", "outro", "chapter", "slam", "map", "timeline",
                  "chart"}
AGGREGATORS = {"Hacker News", "Google Trends"}


def publisher(source: dict) -> str:
    """'Hacker News' and 'Google Trends' only point at news; show the real site instead."""
    name = source.get("source", "")
    if name in AGGREGATORS or name.startswith("r/"):
        host = urlparse(source.get("url", "")).netloc.lower().removeprefix("www.")
        return host.capitalize() if host else name
    return name


def caption_pages(words: list[dict], vertical: bool) -> list[dict]:
    max_words, max_chars = (3, 14) if vertical else (5, 30)
    groups = _groups(words, max_words, max_chars)
    pages = []
    for gi, g in enumerate(groups):
        nxt = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.3
        end = min(g[-1]["e"] + 0.25, nxt)
        pages.append({"startMs": round(g[0]["s"] * 1000), "endMs": round(end * 1000),
                      "words": [{"text": w["w"].strip(), "startMs": round(w["s"] * 1000),
                                 "endMs": round(w["e"] * 1000), "key": bool(w["key"])} for w in g]})
    return pages


def scene_cards(scenes: list[dict], timings, fps: int, total: float) -> list[dict]:
    cards = []
    for i, (sc, (s0, _)) in enumerate(zip(scenes, timings)):
        c = sc.get("card")
        if not isinstance(c, dict) or c.get("template") not in CARD_TEMPLATES:
            continue
        start = s0 if i else 0.3
        end = timings[i + 1][0] if i + 1 < len(timings) else total + ff.TAIL
        dur = max(1.6, min(end - start, 4.5)) if c["template"] != "slam" else min(1.8, max(1.0, end - start))
        cards.append({"from": round(start * fps) + 2, "duration": round(dur * fps), "template": c["template"],
                      "data": {k: v for k, v in c.items() if k != "template"}})
    return cards


def _hex(c: str) -> str:
    return "#" + c.lstrip("#").upper()


def _cpu_seconds() -> tuple[float, float]:
    """(busy, stolen) CPU seconds of the whole machine from /proc/stat (Linux); this process's children elsewhere.
    Counting only our children missed Chrome's helper processes."""
    try:
        f = [int(x) for x in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]]
        hz = os.sysconf("SC_CLK_TCK")
        return (f[0] + f[1] + f[2] + f[5] + f[6]) / hz, (f[7] if len(f) > 7 else 0) / hz
    except (OSError, ValueError, IndexError):
        r = resource.getrusage(resource.RUSAGE_CHILDREN)
        return r.ru_utime + r.ru_stime, 0.0


def render(*, kind: str, scenes: list[dict], timings, total: float, words: list[dict], voice_wav: Path, stock,
           work: Path, out_path: Path, seed: str, theme: dict, hook: str = "", extra_cards: list[dict] | None = None,
           whoosh_scenes: set[int] | None = None, mood: str | None = None, look: dict | None = None) -> list[Path]:
    """Renders the video; returns the clips/photos it used (for the thumbnail)."""
    spec = CFG[kind]
    fps, vertical = spec["fps"], kind == "short"
    rng = random.Random(seed)
    shots = ff.plan_shots(kind=kind, scenes=scenes, timings=timings, total=total, stock=stock, seed=seed,
                          words=words)
    # every 2nd stressed word (every 3rd in long videos) gets a quick zoom punch
    key_frames = [round(w["s"] * fps) for w in words if w["key"]][::2 if vertical else 3]

    run_id = uuid.uuid4().hex[:10]
    pub = REMOTION / "public" / "runs" / run_id
    pub.mkdir(parents=True, exist_ok=True)
    try:
        props_shots = []
        for sh in shots:
            src, credit = "", ""
            if sh["clip"]:
                name = sh["clip"].name
                link = pub / name
                if not link.exists():
                    try:
                        os.link(sh["clip"].resolve(), link)       # hard link: instant, no copy
                    except OSError:
                        shutil.copy2(sh["clip"], link)
                src = f"runs/{run_id}/{name}"
                credit = ("NASA" if name.startswith("nasa_") else
                          "Photo: Wikimedia Commons" if name.startswith("wiki_") else "")
            motion = sh["motion"] if sh["motion"] != "pan" else rng.choice(["pan_left", "pan_right"])
            kind = "image" if sh["clip"] and sh["clip"].suffix.lower() in ff.IMAGE_EXT else "video"
            punches = [f - sh["from"] for f in key_frames if sh["from"] + 3 <= f < sh["from"] + sh["frames"] - 4]
            props_shots.append({"from": sh["from"], "duration": sh["frames"], "src": src, "kind": kind,
                                "width": sh["clip_size"][0], "height": sh["clip_size"][1],
                                "trimBefore": round(sh["offset"] * fps), "motion": motion, "credit": credit,
                                "punches": punches[:2]})
        duration = round((total + ff.TAIL) * fps)
        props = {
            "fps": fps, "durationInFrames": duration, "vertical": vertical,
            "theme": {"text": _hex(theme["text"]), "highlight": _hex(theme["highlight"]),
                      "keyword": _hex(theme["keyword"]), "card": "#F7F7F2", "ink": "#0B0F1A"},
            "look": look or {"cardStyle": "light", "captionY": 0.6, "hookTilt": -2},
            "brand": CFG["channel"]["name"],
            "hook": {"text": hook, "frames": round((2.6 if vertical else 2.8) * fps)} if hook else None,
            "progressBar": bool(vertical and CFG["captions"].get("progress_bar")),
            "shots": props_shots,
            "cards": scene_cards(scenes, timings, fps, total) + (extra_cards or []),
            "captions": caption_pages(words, vertical),
        }
        props_file = work / "props.json"
        props_file.write_text(json.dumps(props))
        video_only = work / "video_only.mp4"
        tabs = workers()
        print(f"  [remotion] {len(props_shots)} shots, {len(props['cards'])} cards, {duration} frames")
        # A busy machine can miss Remotion's per-frame time limit ("delayRender ... not cleared"):
        # try once more with half the browser tabs before giving up on the pro engine.
        for attempt, conc in enumerate([tabs, max(1, tabs // 2)]):
            cmd = ["npx", "remotion", "render", "src/index.ts", "Short" if vertical else "Long",
                   str(video_only.resolve()), f"--props={props_file.resolve()}", "--muted", "--codec=h264",
                   "--crf=20", "--log=error", f"--concurrency={conc}", "--timeout=240000"]
            if sys.platform == "darwin":   # Remotion's default small browser does not start on this macOS
                cmd.append("--chrome-mode=chrome-for-testing")
            t0 = time.time()
            cpu0 = _cpu_seconds()
            try:
                p = subprocess.run(cmd, cwd=REMOTION, capture_output=True, text=True,
                                   timeout=1800 + duration / fps * 12)
                err = (p.stderr or p.stdout)[-1500:] if p.returncode != 0 or not video_only.exists() else ""
            except subprocess.TimeoutExpired:
                err = "Remotion froze (wall-clock limit reached)"
            if not err:
                wall = time.time() - t0
                used = [b - a for a, b in zip(cpu0, _cpu_seconds())]
                print(f"  [remotion] drew {duration} frames in {wall:.0f} s ({conc} tabs, "
                      f"~{used[0] / max(wall, 1):.1f} cores busy, ~{used[1] / max(wall, 1):.1f} cores stolen by "
                      f"other users of the machine)")
                break
            print(f"  [remotion] try {attempt + 1} failed ({conc} tabs): {err.strip().splitlines()[0][:160]}")
        if err:
            raise RuntimeError(f"Remotion failed: {err}")
    finally:
        shutil.rmtree(pub, ignore_errors=True)

    t1 = time.time()
    ff.mix(video_only=video_only, voice_wav=voice_wav, timings=timings, total=total, work=work, out_path=out_path,
           seed=seed, fps=fps, whoosh_scenes=whoosh_scenes, words=words, cards=props["cards"], mood=mood,
           long=not vertical)
    print(f"  [render] sound mix + finish in {time.time() - t1:.0f} s")
    return [sh["clip"] for sh in shots if sh["clip"]]
