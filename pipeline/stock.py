"""Free stock video from Pexels and Pixabay (both allow free commercial use).

Search results are cached for 24 hours (Pixabay's rules ask for this).
Clips used recently are skipped so videos don't keep repeating the same footage.
"""
import hashlib
import json
import random
import re
import time
from pathlib import Path

import requests

from .config import CACHE, DATA, safe_err, secret

SEARCH_CACHE = CACHE / "search"
CLIPS = CACHE / "clips"
USED = DATA / "used_clips.json"
GENERIC = ["futuristic technology", "abstract technology", "city night timelapse", "circuit board",
           "data center", "digital network", "laptop typing", "space stars"]
for d in (SEARCH_CACHE, CLIPS):
    d.mkdir(parents=True, exist_ok=True)


def _cached_get(url: str, params: dict, headers: dict) -> dict:
    key = hashlib.sha1((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    path = SEARCH_CACHE / f"{key}.json"
    if path.exists() and time.time() - path.stat().st_mtime < 86400:
        return json.loads(path.read_text())
    r = requests.get(url, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    path.write_text(json.dumps(data))
    return data


def _pexels(query: str, vertical: bool) -> list[dict]:
    key = secret("PEXELS_API_KEY")
    if not key:
        return []
    data = _cached_get("https://api.pexels.com/videos/search",
                       {"query": query, "orientation": "portrait" if vertical else "landscape",
                        "per_page": 20, "size": "medium"}, {"Authorization": key})
    out = []
    for v in data.get("videos", []):
        if v.get("duration", 0) < 3:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        short_side = (lambda f: f["width"]) if vertical else (lambda f: f["height"])
        good = sorted([f for f in files if short_side(f) >= 1080], key=short_side)
        pick = good[0] if good else (max(files, key=short_side) if files else None)
        if pick:
            out.append({"id": f"pexels_{v['id']}", "url": pick["link"], "duration": v["duration"],
                    "thumb": v.get("image", "")})
    return out


def _pixabay(query: str, vertical: bool) -> list[dict]:
    key = secret("PIXABAY_API_KEY")
    if not key:
        return []
    data = _cached_get("https://pixabay.com/api/videos/",
                       {"key": key, "q": query[:100], "per_page": 30, "safesearch": "true",
                        "video_type": "film"}, {})  # "film" = real footage, no cartoons/green screens
    out = []
    for v in data.get("hits", []):
        sizes = [s for s in v.get("videos", {}).values() if s.get("url") and s.get("width")]
        if not sizes:
            continue
        w, h = sizes[0]["width"], sizes[0]["height"]
        if v.get("duration", 0) < 3 or (not vertical and h > w) or v.get("isLowQuality") or v.get("isAiGenerated"):
            continue
        # Shorts prefer tall clips but also take wide ones (cropped to the centre): Pixabay has few tall clips.
        good = sorted([s for s in sizes if min(s["width"], s["height"]) >= 1080], key=lambda s: s["height"])
        pick = good[0] if good else max(sizes, key=lambda s: s["height"])
        tags = v.get("tags", "").lower()
        words = [x for x in query.lower().split() if len(x) > 2]
        if words and not any(re.search(rf"\b{re.escape(x[:5])}", tags) for x in words):
            continue  # Pixabay sometimes returns unrelated clips; keep only ones tagged with a search word
        thumb = (v["videos"].get("small") or v["videos"].get("tiny") or {}).get("thumbnail", "")
        out.append({"id": f"pixabay_{v['id']}", "url": pick["url"], "duration": v["duration"],
                    "tall": h > w, "thumb": thumb})
    if vertical:
        out.sort(key=lambda i: not i["tall"])  # stable: keeps Pixabay's best-match order within each group
    return out


class Stock:
    def __init__(self, vertical: bool, seed: str):
        self.vertical = vertical
        self.rng = random.Random(seed)
        self.used_now: set[str] = set()
        self.recent: list[str] = json.loads(USED.read_text()) if USED.exists() else []

    def enabled(self) -> bool:
        return bool(secret("PEXELS_API_KEY") or secret("PIXABAY_API_KEY"))

    def _search(self, query: str) -> list[dict]:
        results = []
        for fn in (_pexels, _pixabay):
            try:
                results += fn(query, self.vertical)
            except requests.RequestException as e:
                print(f"  [stock] {fn.__name__} '{query}' failed: {safe_err(e)}")
        return results

    def _download(self, item: dict) -> Path | None:
        path = CLIPS / f"{item['id']}.mp4"
        if path.exists() and path.stat().st_size > 10_000:
            return path
        try:
            with requests.get(item["url"], stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return path
        except requests.RequestException as e:
            print(f"  [stock] download failed {item['id']}: {safe_err(e)}")
            path.unlink(missing_ok=True)
            return None

    def _candidates(self, query: str, alt: str, want: int) -> list[dict]:
        """Clips for one scene, best search matches first (falls back to simpler and generic searches)."""
        # Backups keep the FIRST words: "rocket launch night" -> "rocket launch" -> "rocket" (the subject).
        parts = query.split()
        tries = [query, alt, " ".join(parts[:2]), parts[0] if parts else "", self.rng.choice(GENERIC)]
        found, seen = [], set()
        for q in dict.fromkeys(t for t in tries if t):
            for item in self._search(q):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    found.append(item)
            if len(found) >= want:
                break
        found.sort(key=lambda i: i["id"] in self.recent)  # stable: unused clips first, best matches first
        return found[:want]

    def clips_for_scenes(self, scenes: list[dict], needs: list[int]) -> list[list[Path]]:
        """For every scene, up to `need` clips that really show what is being said. Gemini looks at the
        clips' preview pictures and drops the ones that don't fit; if that check fails, search order is used."""
        if not self.enabled():
            return [[] for _ in scenes]
        cands = [self._candidates(sc.get("visual", "technology"), sc.get("visual_alt", ""), max(6, n + 3))
                 for sc, n in zip(scenes, needs)]
        approved = rank_clips(scenes, cands)
        result = []
        for si, (n, cs) in enumerate(zip(needs, cands)):
            if approved is None:          # check couldn't run: best search matches
                ok = cs[:2]
            else:                         # only clips the picture check approved
                ok = [cs[k] for k in approved[si]]
            paths = []
            for item in ok:
                if len(paths) >= n:
                    break
                if item["id"] in self.used_now:
                    continue
                p = self._download(item)
                if p:
                    self.used_now.add(item["id"])
                    paths.append(p)
            result.append(paths)
        # A scene with no approved clip borrows approved footage from the nearest scene (shown from another
        # moment of the clip), instead of showing something unrelated.
        for si, paths in enumerate(result):
            if paths:
                continue
            for d in range(1, len(result)):
                near = [result[j] for j in (si - d, si + d) if 0 <= j < len(result) and result[j]]
                if near:
                    paths.extend(near[0][:needs[si]])
                    break
        return result

    def save_used(self):
        USED.write_text(json.dumps((self.recent + sorted(self.used_now))[-800:]))


def _thumb(url: str) -> bytes | None:
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.content if len(r.content) > 500 else None
    except requests.RequestException:
        return None


def rank_clips(scenes: list[dict], cands: list[list[dict]]) -> list[list[int]] | None:
    """Ask Gemini which preview pictures fit each scene's words (10 scenes per request).
    Returns, per scene, the indexes of fitting clips (best first), or None if the check can't run."""
    import base64
    from concurrent.futures import ThreadPoolExecutor
    from .llm import ask_vision_json
    if not secret("GEMINI_API_KEY"):
        return None
    with ThreadPoolExecutor(8) as pool:
        thumbs = [list(pool.map(_thumb, [c.get("thumb", "") for c in cs])) for cs in cands]
    system = ("You are a video editor choosing B-roll stock footage for a tech news video. "
              "Return only valid JSON.")
    approved: list[list[int]] = [[] for _ in scenes]
    for start in range(0, len(scenes), 10):
        parts = [{"text": "For each scene below you see the narration and numbered preview pictures of stock clips. "
                          "Score EVERY clip from 0 to 10 for how well it fits what is being said: 9-10 shows "
                          "exactly that, 6-8 clearly related, 4-5 loosely related but fine as background "
                          "(e.g. a lab for a science line), 0-3 unrelated or odd. Give 0 to clips with visible text, "
                          "logos or watermarks, low quality, or a stranger who could be mistaken for a real named "
                          'person. Answer like {"S0": {"C0": 7, "C1": 2}, "S1": {"C0": 9}}.'}]
        for si in range(start, min(start + 10, len(scenes))):
            parts.append({"text": f'\nS{si} narration: "{scenes[si]["text"]}"'})
            for ci, img in enumerate(thumbs[si]):
                if img:
                    parts.append({"text": f"S{si}-C{ci}:"})
                    parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
        try:
            answer = ask_vision_json(system, parts, validate=lambda r: r if isinstance(r, dict) else 1 / 0)
        except Exception as e:
            print(f"  [stock] picture check skipped: {safe_err(e)}")
            return None
        for si in range(start, min(start + 10, len(scenes))):
            scores = answer.get(f"S{si}", {})
            scored = []
            for label, score in (scores.items() if isinstance(scores, dict) else []):
                m = re.fullmatch(r"(?:S\d+-)?C(\d+)", str(label).strip())
                if m and int(m.group(1)) < len(cands[si]) and isinstance(score, (int, float)):
                    scored.append((float(score), int(m.group(1))))
            scored.sort(reverse=True)
            good = [ci for sc, ci in scored if sc >= 6]
            approved[si] = good or [ci for sc, ci in scored[:1] if sc >= 4]
    kept = sum(map(len, approved))
    print(f"  [stock] picture check kept {kept} of {sum(map(len, cands))} clips")
    return approved
