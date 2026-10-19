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


def ask_json(system: str, prompt: str, temperature: float | None = None, validate=None):
    """Ask the first working model. `validate(result)` may raise to reject an answer and try again.
    Raises LLMError if every model fails."""
    temperature = CFG["llm"]["temperature"] if temperature is None else temperature
    attempts = [(_gemini, m) for m in CFG["llm"]["gemini_models"]]
    attempts += [(_groq, m) for m in CFG["llm"]["groq_models"]]
    errors = []
    for fn, model in attempts:
        for retry in range(2):
            try:
                result = _parse(fn(model, system, prompt, temperature))
                if not isinstance(result, dict):
                    raise LLMError("answer is not a JSON object")
                if validate:
                    validate(result)
                print(f"  [llm] answered by {model}")
                return result
            except (LLMError, json.JSONDecodeError, requests.RequestException, KeyError, IndexError,
                    TypeError, ValueError) as e:
                errors.append(f"{model}: {e}")
                msg = str(e)
                if "not set" in msg or "HTTP 404" in msg or "HTTP 400" in msg:
                    break  # this model/provider can't work; try the next one
                time.sleep(5 if retry == 0 else 0)
    raise LLMError("All AI models failed:\n  " + "\n  ".join(errors[-8:]))


def ask_vision_json(system: str, parts: list[dict], validate=None):
    """Gemini with pictures: parts = [{"text": ...} | {"inline_data": {"mime_type", "data"}}]. Returns JSON."""
    key = secret("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set")
    errors = []
    for model in CFG["llm"].get("vision_models", CFG["llm"]["gemini_models"]):
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
            errors.append(f"{model}: {str(e)[:150]}")
    raise LLMError("Picture check failed: " + " | ".join(errors[-3:]))
