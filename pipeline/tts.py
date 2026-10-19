"""Free, commercial-use AI voice: Kokoro (Apache-2.0), run on the CPU with ONNX."""
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import CFG, MODELS

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


def ensure_models():
    import requests
    for name in FILES:
        path = MODELS / name
        if path.exists() and path.stat().st_size > 1_000_000:
            continue
        print(f"  [tts] downloading {name} ...")
        with requests.get(MODEL_URL + name, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)


@lru_cache(maxsize=1)
def _kokoro():
    from kokoro_onnx import Kokoro
    ensure_models()
    return Kokoro(str(MODELS / FILES[0]), str(MODELS / FILES[1]))


def clean(text: str) -> str:
    # Small fixes that make the voice read tech words better.
    for a, b in (("AI's", "A.I.'s"), (" AI ", " A.I. "), ("&", " and "), ("%", " percent"), ("—", ", ")):
        text = text.replace(a, b)
    return text.strip()


def synth(scenes: list[dict], out_wav: Path) -> tuple[list[tuple[float, float]], float]:
    """Speak every scene. Returns (start, end) seconds for each scene and the total length."""
    v = CFG["voice"]
    kokoro = _kokoro()
    rate = None
    pieces, timings, t = [], [], 0.0
    for scene in scenes:
        text = clean(" " + scene["text"] + " ")
        audio, rate = kokoro.create(text, voice=v["voice"], speed=v["speed"], lang="en-us",
                                    sentence_pause=0.12, clause_pause=0.05)
        audio = np.asarray(audio, dtype=np.float32)
        gap = np.zeros(int(rate * v["scene_gap"]), dtype=np.float32)
        start = t
        t += len(audio) / rate
        timings.append((start, t))
        t += len(gap) / rate
        pieces += [audio, gap]
    full = np.concatenate(pieces)
    peak = float(np.max(np.abs(full))) or 1.0
    sf.write(out_wav, full / peak * 0.95, rate)
    return timings, len(full) / rate
