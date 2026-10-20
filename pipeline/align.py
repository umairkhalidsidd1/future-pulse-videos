"""Exact word timing for captions: match the KNOWN script to the voice audio ("forced alignment").

Uses wav2vec2 (facebook/wav2vec2-base-960h, Apache-2.0) and a CTC Viterbi pass. Accurate to about ±0.03 s,
much better than re-transcribing with Whisper (±0.1-0.5 s). Long audio is first cut into scene windows
with a quick Whisper pass, so wav2vec2 only ever sees short pieces.
"""
import difflib
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import CFG, MODELS, workers

W2V_MODEL = "facebook/wav2vec2-base-960h"
FRAME = 320 / 16000          # wav2vec2 gives one score column per 20 ms
SINGLE_PASS_MAX = 70.0       # audio shorter than this is aligned in one go (all Shorts)


def load_16k(wav: Path) -> np.ndarray:
    audio, rate = sf.read(str(wav), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    n = int(len(audio) * 16000 / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)


# ---------- text as it is spoken ----------

def _num_words(m: re.Match) -> str:
    from num2words import num2words
    raw = m.group(0).replace(",", "")
    try:
        if re.fullmatch(r"(19|20)\d\d", raw):
            return " " + num2words(int(raw), to="year") + " "
        return " " + num2words(float(raw) if "." in raw else int(raw)) + " "
    except (ValueError, OverflowError):
        return " "


def spoken(word: str) -> str:
    """A script word as the letters the voice actually says: '6,300' -> 'SIX THOUSAND THREE HUNDRED'."""
    w = re.sub(r"\$(\d[\d,.]*)", r"\1 dollars", word)
    w = w.replace("%", " percent").replace("&", " and ").replace("+", " plus ")
    w = re.sub(r"\d[\d,]*(?:\.\d+)?", _num_words, w)
    w = re.sub(r"[^A-Za-z' ]", " ", w).upper()
    return " ".join(w.split())


# ---------- wav2vec2 + CTC Viterbi ----------

@lru_cache(maxsize=1)
def _w2v():
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    torch.set_num_threads(workers())
    cache = str(MODELS / "hf")
    proc = Wav2Vec2Processor.from_pretrained(W2V_MODEL, cache_dir=cache)
    model = Wav2Vec2ForCTC.from_pretrained(W2V_MODEL, cache_dir=cache).eval()
    return proc, model


def _emissions(audio: np.ndarray) -> np.ndarray:
    import torch
    proc, model = _w2v()
    with torch.inference_mode():
        values = proc(audio, sampling_rate=16000, return_tensors="pt").input_values
        logits = model(values).logits[0]
        return torch.log_softmax(logits, dim=-1).numpy()


def _ctc_align(emis: np.ndarray, words: list[str]) -> list[tuple[float, float] | None]:
    """Viterbi path of the known letters through the CTC scores. Returns (start, end) per word."""
    vocab = _w2v()[0].tokenizer.get_vocab()
    blank, sep = vocab["<pad>"], vocab["|"]
    tokens, owner = [], []           # token ids, and which word each token belongs to (-1 = word separator)
    for i, w in enumerate(words):
        letters = [vocab[c] for c in spoken(w).replace(" ", "|") if c in vocab]
        if not letters:
            continue
        if tokens:
            tokens.append(sep)
            owner.append(-1)
        tokens += letters
        owner += [i] * len(letters)
    if not tokens:
        return [None] * len(words)
    ext = [blank]
    for t in tokens:
        ext += [t, blank]
    S, T = len(ext), emis.shape[0]
    if T < len(tokens):
        raise ValueError("audio too short for the text")
    ext = np.array(ext)
    can_skip = np.zeros(S, dtype=bool)
    can_skip[2:] = (ext[2:] != blank) & (ext[2:] != ext[:-2])
    neg = -1e30
    dp = np.full(S, neg)
    dp[0], dp[1] = emis[0, ext[0]], emis[0, ext[1]]
    back = np.zeros((T, S), dtype=np.int8)
    for t in range(1, T):
        stay = dp
        step = np.concatenate(([neg], dp[:-1]))
        skip = np.where(can_skip, np.concatenate(([neg, neg], dp[:-2])), neg)
        choice = np.stack([stay, step, skip])
        best = choice.argmax(axis=0)
        dp = choice[best, np.arange(S)] + emis[t, ext]
        back[t] = best
    s = int(S - 1 if dp[S - 1] >= dp[S - 2] else S - 2)
    state_at = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        state_at[t] = s
        s -= int(back[t, s])
    spans: dict[int, list[int]] = {}
    for t, st in enumerate(state_at):
        if st % 2 == 1:                       # odd states are letters, even states are blanks
            w = owner[(st - 1) // 2]
            if w >= 0:
                spans.setdefault(w, [t, t])[1] = t
    return [(spans[i][0] * FRAME, (spans[i][1] + 1) * FRAME) if i in spans else None for i in range(len(words))]


# ---------- coarse pass for long audio ----------

def _norm(w: str) -> str:
    return re.sub(r"[^a-z0-9]", "", w.lower())


def _whisper_coarse(audio: np.ndarray, words: list[str]) -> list[tuple[float, float] | None]:
    from faster_whisper import WhisperModel
    model = WhisperModel(CFG["captions"]["whisper_model"], device="cpu", compute_type="int8",
                         download_root=str(MODELS / "whisper"))
    segs, _ = model.transcribe(audio, language="en", word_timestamps=True, vad_filter=False)
    heard = [(w.start, w.end, _norm(w.word)) for s in segs for w in s.words]
    times: list[tuple[float, float] | None] = [None] * len(words)
    sm = difflib.SequenceMatcher(None, [_norm(w) for w in words], [h[2] for h in heard], autojunk=False)
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            times[block.a + k] = (h[0], h[1])
    return times


def _fill(times: list, words: list[str], start: float, end: float):
    """Words with no time get a share of the gap between their timed neighbours, by length."""
    i = 0
    while i < len(times):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(times) and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else start
        right = times[j][0] if j < len(times) else end
        right = max(right, left + 0.08 * (j - i))
        total = sum(len(w) + 2 for w in words[i:j])
        t = left
        for k in range(i, j):
            d = (right - left) * (len(words[k]) + 2) / total
            times[k] = (t, t + d)
            t += d
        i = j


def align_script(wav: Path, scenes: list[dict], known_spans=None) -> tuple[list[dict], list[tuple[float, float]]]:
    """Caption words (the script's own spelling) with exact times, and each scene's (start, end)."""
    audio = load_16k(wav)
    total = len(audio) / 16000
    words, scene_of = [], []
    for si, sc in enumerate(scenes):
        for w in sc["text"].split():
            words.append(w)
            scene_of.append(si)

    # 1) Windows of whole scenes, each at most ~40 s, cut in the silence between scenes.
    if total <= SINGLE_PASS_MAX:
        windows = [(0, len(words), 0.0, total)]
    else:
        if known_spans:
            coarse = [None] * len(words)
            for i, si in enumerate(scene_of):
                coarse[i] = known_spans[si]
        else:
            coarse = _whisper_coarse(audio, words)
            _fill(coarse, words, 0.0, total)
        n = len(scenes)
        first_word = [scene_of.index(si) for si in range(n)] + [len(words)]
        # bounds[si] = where scene si's window starts: halfway through the pause before it
        bounds = [0.0] + [(coarse[first_word[si] - 1][1] + coarse[first_word[si]][0]) / 2
                          for si in range(1, n)] + [total]
        windows, ws = [], 0
        for si in range(1, n + 1):
            if si == n or bounds[si + 1] - bounds[ws] > 40:
                windows.append((first_word[ws], first_word[si], bounds[ws], bounds[si]))
                ws = si

    # 2) Exact alignment inside each window. A window that fails keeps estimated times.
    times: list = [None] * len(words)
    for a, b, t0, t1 in windows:
        piece = audio[int(t0 * 16000):int(t1 * 16000)]
        try:
            got = _ctc_align(_emissions(piece), words[a:b])
            for k, span in enumerate(got):
                if span:
                    times[a + k] = (t0 + span[0], t0 + span[1])
        except Exception as e:
            print(f"  [align] window {t0:.0f}-{t1:.0f}s: estimated timing ({e.__class__.__name__})")
    aligned = sum(t is not None for t in times)
    _fill(times, words, 0.0, total)
    print(f"  [align] {aligned}/{len(words)} words exactly aligned")

    keys = [{_norm(k) for kw in sc.get("keywords", []) for k in kw.split()} for sc in scenes]
    out = [{"w": w, "s": s, "e": e, "scene": si, "key": _norm(w) in keys[si]}
           for w, (s, e), si in zip(words, times, scene_of)]
    spans = []
    for si in range(len(scenes)):
        mine = [o for o in out if o["scene"] == si]
        spans.append((mine[0]["s"], mine[-1]["e"]) if mine else (spans[-1][1] if spans else 0.0,) * 2)
    return out, spans
