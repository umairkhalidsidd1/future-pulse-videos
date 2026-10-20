"""Endless, fresh topics for each channel, and the facts to write about them.

Ideas come from: what people read most on Wikipedia yesterday (a trend signal), Wikipedia's "on this day"
(history), the channel's news feeds, and evergreen ideas from the AI. The AI picks the best; a duplicate
guard blocks anything the channel covered in the last year. Facts come from Wikipedia articles (and the news
item when there is one). Facts are never stored in the public repo.
"""
import datetime as dt
import json
import re
import time

import requests

from .config import CFG, DATA
from .llm import ask_json
from .trends import _rss, fetch_article, similar, words

UA = {"User-Agent": "VideoFactoryBot/1.0 (https://github.com/umairkhalidsidd1/future-pulse-videos)"}
WIKI = "https://en.wikipedia.org"
TOPIC_LOG = DATA / "topics"
SKIP_PAGES = re.compile(r"^(Main Page|Deaths in|Special:|List of|Wikipedia:|Portal:|\d{4} in )", re.I)


# ---------- idea sources ----------

def most_read(days_ago: int = 1) -> list[dict]:
    d = dt.date.today() - dt.timedelta(days=days_ago)
    r = requests.get(f"{WIKI}/api/rest_v1/feed/featured/{d:%Y/%m/%d}", headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for a in r.json().get("mostread", {}).get("articles", []):
        t = a.get("normalizedtitle", "")
        if t and not SKIP_PAGES.match(t):
            out.append({"title": t, "wiki": t, "source": f"Wikipedia most-read ({a.get('views', 0):,} views)",
                        "about": a.get("description", "") or a.get("extract", "")[:160]})
    return out


def on_this_day() -> list[dict]:
    d = dt.date.today()
    r = requests.get(f"{WIKI}/api/rest_v1/feed/onthisday/events/{d:%m/%d}", headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json().get("events", []):
        pages = [p.get("normalizedtitle") or p.get("title") for p in e.get("pages", []) if p]
        if e.get("year", 3000) <= d.year - 25 and pages:          # history, not recent news
            out.append({"title": f"{e['year']}: {e['text']}", "wiki": pages[0],
                        "source": f"On this day ({d:%B %d}, {e['year']})", "about": e["text"][:200]})
    return out


def news(urls: list[str]) -> list[dict]:
    out = []
    for u in urls:
        try:
            for it in _rss(u)[:15]:
                if time.time() - it["published"] < 4 * 86400:
                    out.append({"title": it["title"], "wiki": "", "source": f"News: {it['source']}",
                                "url": it["url"], "about": ""})
        except Exception as e:
            print(f"  [topics] feed skipped {u}: {e.__class__.__name__}")
    return out


# ---------- duplicate guard ----------

def _log_path(channel: str):
    TOPIC_LOG.mkdir(parents=True, exist_ok=True)
    return TOPIC_LOG / f"{channel}.json"


def used(channel: str) -> list[dict]:
    p = _log_path(channel)
    items = json.loads(p.read_text()) if p.exists() else []
    cutoff = time.time() - CFG["channel"]["avoid_repeat_days"] * 86400
    return [x for x in items if x["ts"] > cutoff]


def remember(channel: str, topic: dict):
    p = _log_path(channel)
    items = json.loads(p.read_text()) if p.exists() else []
    items.append({"title": topic["title"], "wiki": topic.get("wiki", []), "ts": time.time()})
    p.write_text(json.dumps(items[-3000:], indent=0))


def is_repeat(channel: str, title: str, wiki: list[str]) -> bool:
    past = used(channel)
    pages = {w.lower() for x in past for w in (x.get("wiki") or [])}
    main = (wiki or [""])[0].lower()
    return bool(main and main in pages) or any(similar(words(title), words(x["title"])) for x in past)


# ---------- choosing ----------

def _check_pick(r):
    if not isinstance(r.get("topics"), list) or not r["topics"]:
        raise ValueError("no topics")


def pick(channel: str, ch: dict, n: int) -> list[dict]:
    """n fresh topics for this channel: {title, thesis, angle, wiki: [article titles], url?}."""
    ideas = []
    try:
        ideas += most_read()[:40]
    except requests.RequestException as e:
        print(f"  [topics] most-read skipped: {e.__class__.__name__}")
    if ch.get("on_this_day"):
        try:
            ideas += on_this_day()[:30]
        except requests.RequestException as e:
            print(f"  [topics] on-this-day skipped: {e.__class__.__name__}")
    ideas += news(ch.get("topic_feeds", []))[:30]
    recent = [x["title"] for x in used(channel)][-60:]
    listing = "\n".join(f"{i}. {x['title']}  [{x['source']}] {x.get('about', '')[:120]}" for i, x in enumerate(ideas))
    prompt = f"""You plan videos for a YouTube channel about: {ch['niche']}.
Style: {ch['style']}.

TOPIC IDEAS FROM TODAY (trend signals; most are OFF-niche, ignore those):
{listing or "(none today)"}

ALREADY COVERED (never repeat these or near-duplicates):
{chr(10).join(recent) or "(nothing yet)"}

Choose {n + 2} video topics for this channel. Mix:
- topics that ride today's trend signals above (when they truly fit the niche), and
- evergreen topics with huge, lasting search interest in this niche (you may invent these).
Each topic must: fit the niche exactly, have a clear question that makes people click, be explainable with
real facts from Wikipedia, and be materially different from the others and from ALREADY COVERED.
Never: health/medical, legal or financial ADVICE; graphic violence; living private persons; hate.

Return JSON: {{"topics": [{{"title": "working title", "question": "the one question the video answers",
"thesis": "our point of view in one sentence", "wiki": ["Exact English Wikipedia article title", "optional 2nd",
"optional 3rd"], "idea_index": <number from the list or null>, "why": "why people will click"}}]}}"""
    r = ask_json(f"You are the head of programming for a {ch['niche']} channel. Return only JSON.", prompt,
                 temperature=0.8, validate=_check_pick)
    out = []
    for t in r["topics"]:
        if not isinstance(t, dict) or not t.get("title"):
            continue
        wiki = [w for w in t.get("wiki", []) if isinstance(w, str) and w.strip()][:3]
        if is_repeat(channel, t["title"], wiki):
            print(f"  [topics] skipped (covered before): {t['title']}")
            continue
        idx = t.get("idea_index")
        src = ideas[idx] if isinstance(idx, int) and 0 <= idx < len(ideas) else {}
        out.append({"title": t["title"], "question": t.get("question", ""), "thesis": t.get("thesis", ""),
                    "wiki": wiki, "why": t.get("why", ""), "url": src.get("url", ""),
                    "trend": src.get("source", "evergreen")})
    return out[: n + 2]


# ---------- facts ----------

def wiki_text(title: str, limit: int = 9000) -> tuple[str, str]:
    """(plain article text, final title) of an English Wikipedia article, or ('', title)."""
    r = requests.get(f"{WIKI}/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "format": "json", "prop": "extracts", "explaintext": 1, "titles": title, "redirects": 1})
    r.raise_for_status()
    page = next(iter(r.json().get("query", {}).get("pages", {}).values()), {})
    text = re.sub(r"\n==+ (See also|References|External links|Notes|Further reading|Bibliography) ==+.*", "",
                  page.get("extract", ""), flags=re.S)
    return text[:limit], page.get("title", title)


def research(topic: dict) -> str:
    """Facts for the writer: the Wikipedia articles (and the news story). Returns '' if too thin."""
    parts = []
    for i, t in enumerate(topic.get("wiki", [])):
        try:
            text, real = wiki_text(t, 9000 if i == 0 else 4000)
        except requests.RequestException:
            continue
        if len(text) > 800:
            parts.append(f"SOURCE (Wikipedia: {real}):\n{text}")
            topic.setdefault("sources", []).append({"title": real, "source": "Wikipedia",
                                                    "url": f"{WIKI}/wiki/{real.replace(' ', '_')}"})
    if topic.get("url"):
        text = fetch_article(topic["url"], 5000)
        if len(text) > 400:
            parts.insert(0, f"SOURCE (news): {topic['url']}\n{text}")
            topic.setdefault("sources", []).insert(0, {"title": topic["title"], "source": "News",
                                                       "url": topic["url"]})
    facts = "\n\n---\n\n".join(parts)
    return facts if len(facts) > 2500 else ""
