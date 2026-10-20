"""Free AI text models: Gemini first, Groq as a backup. Always returns parsed JSON."""
import json
import re
import time

import requests

from .config import CFG, secret


class LLMError(RuntimeError):
    pass


def _gemini(model: str, system: str, prompt: str, temperature: float) -> str:
    key = secret("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": temperature},
    }
    r = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=180)
    if r.status_code != 200:
        raise LLMError(f"Gemini {model}: HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise LLMError(f"Gemini {model}: no answer ({str(data)[:300]})")
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _groq(model: str, system: str, prompt: str, temperature: float) -> str:
    key = secret("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY not set")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        },
        timeout=180,
    )
    if r.status_code != 200:
        raise LLMError(f"Groq {model}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _parse(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def ask_json(system: str, prompt: str, temperature: float | None = None, validate=None, max_tries: int = 6):
    """Ask the first working model. `validate(result)` may raise to reject an answer: the reason is printed
    and sent back to the AI on the next try ("you wrote 900 words, need 1,150"), so it can fix it.
    At most `max_tries` answers are requested, so one bad script can never block the whole day."""
    from .status import count
    temperature = CFG["llm"]["temperature"] if temperature is None else temperature
    order = CFG["llm"].get("models") or ([f"gemini:{m}" for m in CFG["llm"]["gemini_models"]]
                                         + [f"groq:{m}" for m in CFG["llm"]["groq_models"]])
    attempts = [(_groq if p == "groq" else _gemini, m) for p, _, m in (x.partition(":") for x in order)]
    errors, feedback, tries = [], "", 0
    for fn, model in attempts:
        for retry in range(3 if fn is _groq else 2):
            if tries >= max_tries:
                raise LLMError(f"No acceptable answer after {tries} tries:\n  " + "\n  ".join(errors[-6:]))
            ask = prompt + (f"\n\nYOUR PREVIOUS ANSWER WAS REJECTED: {feedback}\nFix exactly that and answer again "
                            f"with the complete JSON." if feedback else "")
            try:
                raw = fn(model, system, ask, temperature)
            except (LLMError, requests.RequestException) as e:
                msg = " ".join(str(e).split())[:200]
                errors.append(f"{model}: {msg}")
                print(f"  [llm] {model} unavailable: {msg[:120]}")
                per_minute = fn is _groq and "HTTP 429" in msg and ("per minute" in msg or "TPM" in msg or "RPM" in msg)
                if per_minute:                              # Groq's per-minute limit: wait, then the same model
                    print("  [llm] Groq per-minute limit: waiting 60 s")
                    time.sleep(60)
                    continue
                if any(x in msg for x in ("not set", "HTTP 404", "HTTP 400", "HTTP 429", "HTTP 413")):
                    break                                   # missing / quota used up / too big: next model
                time.sleep(20 if "HTTP 503" in msg else 8)  # "high demand" passes after a short wait
                continue
            tries += 1
            count(f"text {model}")
            try:
                result = _parse(raw)
                if not isinstance(result, dict):
                    raise ValueError("the answer is not a JSON object")
                if validate:
                    validate(result)
                print(f"  [llm] answered by {model}")
                return result
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as e:
                feedback = " ".join(str(e).split())[:300]
                errors.append(f"{model}: rejected: {feedback}")
                print(f"  [llm] answer from {model} rejected: {feedback}")
    raise LLMError("All AI models failed:\n  " + "\n  ".join(errors[-8:]))


def ask_vision_json(system: str, parts: list[dict], validate=None):
    """Gemini with pictures: parts = [{"text": ...} | {"inline_data": {"mime_type", "data"}}]. Returns JSON."""
    key = secret("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    errors = []
    attempts = [m for m in CFG["llm"].get("vision_models", CFG["llm"]["gemini_models"]) for _ in range(2)]
    for n, model in enumerate(attempts):
        if n % 2:
            time.sleep(8)                 # second try of the same model after a short wait (busy / rate limit)
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              json=body, headers={"x-goog-api-key": key}, timeout=300)
            if r.status_code != 200:
                raise LLMError(f"HTTP {r.status_code} {r.text[:200]}")
            out = r.json()["candidates"][0]["content"]["parts"]
            result = _parse("".join(p.get("text", "") for p in out if not p.get("thought")))
            if validate:
                validate(result)
            print(f"  [llm] clips checked by {model}")
            return result
        except (LLMError, json.JSONDecodeError, requests.RequestException, KeyError, IndexError, TypeError,
                ValueError) as e:
            errors.append(f"{model}: {' '.join(str(e).split())[:150]}")
    raise LLMError("Picture check failed: " + " | ".join(errors[-3:]))
