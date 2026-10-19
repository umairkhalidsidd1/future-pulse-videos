"""Free stock video from Pexels and Pixabay (both allow free commercial use).

Search results are cached for 24 hours (Pixabay's rules ask for this).
Clips used recently are skipped so videos don't keep repeating the same footage.
"""
import hashlib
import json
import random
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
            out.append({"id": f"pexels_{v['id']}", "url": pick["link"], "duration": v["duration"]})
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
        if v.get("duration", 0) < 3 or (not vertical and h > w):
            continue
        # Shorts prefer tall clips but also take wide ones (cropped to the centre): Pixabay has few tall clips.
        good = sorted([s for s in sizes if min(s["width"], s["height"]) >= 1080], key=lambda s: s["height"])
        pick = good[0] if good else max(sizes, key=lambda s: s["height"])
        out.append({"id": f"pixabay_{v['id']}", "url": pick["url"], "duration": v["duration"],
                    "tall": h > w})
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

    def clips(self, query: str, n: int) -> list[Path]:
        """Up to n different clips for this query (falls back to simpler and generic queries)."""
        if not self.enabled():
            return []
        # Backups keep the FIRST words: "rocket launch night" -> "rocket launch" -> "rocket" (the subject).
        parts = query.split()
        tries = [query, " ".join(parts[:2]), parts[0] if parts else "", self.rng.choice(GENERIC)]
        found: list[dict] = []
        for q in dict.fromkeys(t for t in tries if t):
            items = [i for i in self._search(q) if i["id"] not in self.used_now
                     and i["id"] not in {f["id"] for f in found}]
            fresh = [i for i in items if i["id"] not in self.recent]  # best matches first, unused first
            stale = [i for i in items if i["id"] in self.recent]
            found += fresh + stale
            if len(found) >= n:
                break
        paths = []
        for item in found:
            if len(paths) >= n:
                break
            p = self._download(item)
            if p:
                self.used_now.add(item["id"])
                paths.append(p)
        return paths

    def save_used(self):
        USED.write_text(json.dumps((self.recent + sorted(self.used_now))[-800:]))
