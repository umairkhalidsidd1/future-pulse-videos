"""Voice-over. First choice: Google Gemini TTS (top-5 most natural voice in public listening tests, free tier,
outputs may be used commercially). Backup: Kokoro (Apache-2.0, runs on the CPU) when Gemini's small daily
limit is used up. A video always uses ONE engine from start to end, never a mix."""
import base64
import io
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
import soundfile as sf

from .config import CFG, MODELS, safe_err, secret

RATE = 24000
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


class VoiceError(RuntimeError):
    pass


# ---------- Gemini TTS ----------

def _gemini(model: str, text: str) -> np.ndarray:
    v = CFG["voice"]
    key = secret("GEMINI_API_KEY")
    if not key:
        raise VoiceError("GEMINI_API_KEY not set")
    body = {"contents": [{"parts": [{"text": f"{v['style'].rstrip()}\n#### TRANSCRIPT\n{text}"}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v["gemini_voice"]}}}}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      json=body, headers={"x-goog-api-key": key}, timeout=600)
    if r.status_code != 200:
        raise VoiceError(f"{model}: HTTP {r.status_code} {r.text[:200]}")
    try:
        part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError) as e:
        raise VoiceError(f"{model}: no audio in answer") from e
    raw = base64.b64decode(part["data"])
    if raw[:4] == b"RIFF":                    # a full WAV file
        audio, rate = sf.read(io.BytesIO(raw), dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != RATE:
            audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * RATE / rate)),
                              np.arange(len(audio)), audio).astype(np.float32)
        return audio
    m = re.search(r"rate=(\d+)", part.get("mimeType", ""))   # raw 16-bit PCM
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    rate = int(m.group(1)) if m else RATE
    if rate != RATE:
        audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * RATE / rate)),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def _words(text: str) -> list[str]:
    from .align import _norm, spoken
    text = re.sub(r"<[^>]+>", " ", text)
    return [w for w in (_norm(x) for x in spoken(text).split()) if w]


def _check_full(audio: np.ndarray, script: str):
    """Listen to the WHOLE recording and compare it with the script. Rejects audio where the AI read its
    instructions out loud, skipped a sentence, or added words (a start check alone misses those)."""
    import difflib
    from faster_whisper import WhisperModel
    a16 = np.interp(np.linspace(0, len(audio) - 1, len(audio) * 2 // 3), np.arange(len(audio)), audio)
    model = WhisperModel("base.en", device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"))
    segs, _ = model.transcribe(a16.astype(np.float32), language="en")
    heard = _words(" ".join(s.text for s in segs))
    want = _words(script)
    sm = difflib.SequenceMatcher(None, want, heard, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    missing = 1 - matched / max(1, len(want))
    extra = 1 - matched / max(1, len(heard))
    first = want[:4]
    starts_ok = any(w in heard[:12] for w in first if len(w) > 2) if first else True
    if missing > 0.15 or extra > 0.15 or not starts_ok:
        raise VoiceError(f"voice does not match the script ({missing:.0%} missing, {extra:.0%} extra)")


def speech_text(scenes: list[dict]) -> str:
    """What the voice reads: the script with the key word of each scene in CAPS (Gemini stresses it) and a
    short pause before reveal lines. Captions still show the plain script."""
    parts = []
    for i, sc in enumerate(scenes):
        text = sc["text"]
        for kw in sc.get("keywords", [])[:1]:
            if len(kw) > 3 and not kw.isupper():
                text = re.sub(rf"\b{re.escape(kw)}\b", kw.upper(), text, count=1)
        reveal = i == len(scenes) - 1 or re.match(r"(but|here's|here is|so|and that's|now)\b", text, re.I)
        parts.append(("<short pause> " if i and reveal else "") + text)
    return " ".join(parts)


# ---------- Kokoro (backup) ----------

def ensure_models():
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


def _kokoro_say(text: str) -> np.ndarray:
    v = CFG["voice"]
    for a, b in (("AI's", "A.I.'s"), (" AI ", " A.I. "), ("&", " and "), ("%", " percent"), ("—", ", ")):
        text = f" {text} ".replace(a, b).strip()
    audio, rate = _kokoro().create(text, voice=v["kokoro_voice"], speed=1.0, lang="en-us",
                                   sentence_pause=0.12, clause_pause=0.05)
    return np.asarray(audio, dtype=np.float32)


# ---------- shared ----------

def _trim(audio: np.ndarray, pad: float = 0.08) -> np.ndarray:
    level = np.abs(audio)
    loud = np.where(level > 0.02 * (level.max() or 1))[0]
    if not len(loud):
        return audio
    a, b = max(0, loud[0] - int(pad * RATE)), min(len(audio), loud[-1] + int(pad * RATE))
    return audio[a:b]


def _chunks(scenes: list[dict], max_words: int = 600) -> list[list[dict]]:
    """Whole scenes grouped into pieces of at most ~600 words (one Gemini request each)."""
    out, cur, n = [], [], 0
    for sc in scenes:
        k = len(sc["text"].split())
        if cur and n + k > max_words:
            out.append(cur)
            cur, n = [], 0
        cur.append(sc)
        n += k
    if cur:
        out.append(cur)
    return out


def _tempo(audio: np.ndarray, factor: float) -> np.ndarray:
    """Speed up without changing the pitch (FFmpeg atempo)."""
    if abs(factor - 1) < 0.02:
        return audio
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / "out.wav"
        sf.write(src, audio, RATE)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-af", f"atempo={factor:.3f}",
                        str(dst)], check=True)
        out, _ = sf.read(dst, dtype="float32")
    return out


def synth(scenes: list[dict], out_wav: Path, kind: str = "short") -> tuple[None, float]:
    """Speaks the whole script into out_wav. Returns (None, length in seconds); exact word and scene
    times come from align.align_script afterwards."""
    v = CFG["voice"]
    pieces = _chunks(scenes)
    script = " ".join(sc["text"] for sc in scenes)
    words = len(script.split())
    import hashlib
    import json
    stamp = hashlib.sha1(json.dumps([script, v, kind], sort_keys=True).encode()).hexdigest()
    stamp_file = out_wav.with_suffix(".stamp")
    if out_wav.exists() and stamp_file.exists() and stamp_file.read_text() == stamp:
        total = sf.info(str(out_wav)).duration
        print(f"  [tts] same script as before: reusing the voice-over ({total:.1f} s)")
        return None, total
    audio, engine = None, None
    for model in v.get("gemini_models", []):
        try:
            parts = []
            for piece in pieces:
                plain = " ".join(sc["text"] for sc in piece)
                part = _trim(_gemini(model, speech_text(piece)))
                expected = len(plain.split()) / 150 * 60
                if not 0.5 * expected < len(part) / RATE < 1.8 * expected:
                    raise VoiceError(f"odd length {len(part) / RATE:.0f}s for ~{expected:.0f}s of text")
                _check_full(part, plain)
                parts.append(part)
            gap = np.zeros(int(0.25 * RATE), dtype=np.float32)
            audio = np.concatenate([x for p in parts for x in (p, gap)][:-1])
            engine = model
            break
        except (VoiceError, requests.RequestException) as e:
            print(f"  [tts] {safe_err(e)}; trying the next voice engine")
    if audio is None:
        audio = _trim(np.concatenate([_kokoro_say(" ".join(sc["text"] for sc in p)) for p in pieces]))
        engine = f"kokoro ({v['kokoro_voice']})"

    target = v["target_wpm"][kind]
    wpm = words / (len(audio) / RATE / 60)
    factor = min(1.25, max(0.85, target / wpm))
    audio = _tempo(audio, factor)
    peak = float(np.max(np.abs(audio))) or 1.0
    sf.write(out_wav, audio / peak * 0.95, RATE)
    stamp_file.write_text(stamp)
    total = len(audio) / RATE
    print(f"  [tts] {engine}: {total:.1f} s, {words / total * 60:.0f} words/min (sped up x{factor:.2f})")
    return None, total
