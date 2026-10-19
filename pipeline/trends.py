"""Finds trending stories from free sources and groups the same story together."""
import json
import math
import re
import time
from calendar import timegm

import feedparser
import requests

from .config import CFG, DATA

UA = {"User-Agent": "Mozilla/5.0 (faceless-video-bot; +https://github.com)"}
STOP = set("""a an the and or but of to in on for with at by from as is are was were be been it its this that
these those new how why what when who will can could would should you your our we they their about after over
into than more most just now says said say report reports here first one two three via amid""".split())
SKIP_TEXT_HOSTS = ("news.google.com", "reddit.com", "youtube.com", "youtu.be", "x.com", "twitter.com")


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2 and w not in STOP}


def similar(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    common = len(a & b)
    return common >= 3 or common / len(a | b) >= 0.34


def _get(url: str, **kw):
    r = requests.get(url, headers=UA, timeout=20, **kw)
    r.raise_for_status()
    return r


def _hacker_news() -> list[dict]:
    ids = _get("https://hacker-news.firebaseio.com/v0/topstories.json").json()[:60]
    items = []
    for i in ids:
        try:
            it = _get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json").json()
        except requests.RequestException:
            continue
        if it and it.get("url") and it.get("title"):
            items.append({"title": it["title"], "url": it["url"], "source": "Hacker News",
                          "published": it.get("time", time.time()), "points": it.get("score", 0)})
    return items


def _rss(url: str) -> list[dict]:
    feed = feedparser.parse(_get(url).content)
    source = feed.feed.get("title", url.split("/")[2])
    items = []
    for e in feed.entries[:40]:
        published = e.get("published_parsed") or e.get("updated_parsed")
        title = e.get("title", "")
        src = source
        if "news.google.com" in url and " - " in title:  # "Headline - Publisher"
            title, src = title.rsplit(" - ", 1)
        items.append({"title": title, "url": e.get("link", ""), "source": src,
                      "published": timegm(published) if published else time.time(), "points": 0})
    return items


def _google_trends(geo: str) -> list[dict]:
    feed = feedparser.parse(_get(f"https://trends.google.com/trending/rss?geo={geo}").content)
    items = []
    for e in feed.entries:
        traffic = re.sub(r"[^0-9]", "", e.get("ht_approx_traffic", "0")) or "0"
        news_title = e.get("ht_news_item_title", "")
        items.append({"title": f"{e.title}: {news_title}" if news_title else e.title,
                      "url": e.get("ht_news_item_url", ""), "source": "Google Trends",
                      "published": time.time(), "points": int(traffic) // 1000})
    return items


def _reddit(sub: str) -> list[dict]:
    data = _get(f"https://www.reddit.com/r/{sub}/hot.json?limit=30").json()
    items = []
    for c in data["data"]["children"]:
        p = c["data"]
        if p.get("stickied") or p.get("is_self"):
            continue
        items.append({"title": p["title"], "url": p.get("url", ""), "source": f"r/{sub}",
                      "published": p.get("created_utc", time.time()), "points": p.get("score", 0) // 5})
    return items


def collect() -> list[dict]:
    t = CFG["trends"]
    jobs = []
    if t.get("hacker_news"):
        jobs.append(("Hacker News", _hacker_news, ()))
    if t.get("google_trends_geo"):
        jobs.append(("Google Trends", _google_trends, (t["google_trends_geo"],)))
    jobs += [(u, _rss, (u,)) for u in t.get("rss", [])]
    jobs += [(f"r/{s}", _reddit, (s,)) for s in t.get("reddit", [])]

    raw = []
    for name, fn, args in jobs:
        try:
            got = fn(*args)
            raw += got
            print(f"  [trends] {name}: {len(got)}")
        except Exception as e:  # one broken source must not stop the day
            print(f"  [trends] {name}: skipped ({e.__class__.__name__}: {str(e)[:80]})")

    max_age = t["max_age_hours"] * 3600
    now = time.time()
    raw = [r for r in raw if r["title"] and now - r["published"] < max_age]

    clusters: list[dict] = []
    for r in raw:
        w = words(r["title"])
        for c in clusters:
            if similar(w, c["words"]):
                c["items"].append(r)
                c["words"] |= w
                break
        else:
            clusters.append({"words": w, "items": [r]})

    history = recent_history()
    out = []
    for c in clusters:
        if any(similar(c["words"], words(h)) for h in history):
            continue
        sources = {i["source"] for i in c["items"]}
        points = sum(i["points"] for i in c["items"])
        age_h = (now - max(i["published"] for i in c["items"])) / 3600
        score = 2 * len(sources) + math.log1p(points) / 2 + max(0.0, 3 - age_h / 8)
        best = max(c["items"], key=lambda i: (i["points"], len(i["title"])))
        out.append({"title": best["title"], "score": round(score, 2), "age_hours": round(age_h, 1),
                    "sources": [{"title": i["title"], "url": i["url"], "source": i["source"]}
                                for i in c["items"][:6]]})
    out.sort(key=lambda c: c["score"], reverse=True)
    return out[:45]


def fetch_article(url: str, limit: int = 3500) -> str:
    if not url or any(h in url for h in SKIP_TEXT_HOSTS):
        return ""
    try:
        import trafilatura
        html = _get(url).text
        text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        return text[:limit]
    except Exception:
        return ""


HISTORY = DATA / "history.json"


def recent_history() -> list[str]:
    if not HISTORY.exists():
        return []
    days = CFG["channel"]["avoid_repeat_days"]
    cutoff = time.time() - days * 86400
    return [h["title"] for h in json.loads(HISTORY.read_text()) if h["ts"] > cutoff]


def add_history(titles: list[str]):
    items = json.loads(HISTORY.read_text()) if HISTORY.exists() else []
    items += [{"title": t, "ts": time.time()} for t in titles]
    HISTORY.write_text(json.dumps(items[-400:], indent=1))
