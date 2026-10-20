"""Writes scripts with the free AI. Rules for hooks, retention and truth are baked into the prompts.

Hook and Shorts rules are adapted from the MIT-licensed social-media-skills/skills
pack (hook-writer, youtube-shorts).
"""
import json
import re

from .config import CFG
from .llm import ask_json
from .trends import fetch_article

# The old single-channel news flow (kept for `python -m pipeline test`); the factory uses channel_system().
CH = {"name": "Factory", "niche": "technology and the future", "language": "en", **CFG["channel"]}

SYSTEM = f"""You are the head writer of "{CH['name']}", a faceless YouTube / TikTok / Instagram channel about
{CH['niche']}. Language: {CH['language']}.

Voice: a smart, trustworthy explainer with calm confident energy, like a friend who works in tech. You always
add an angle: why it matters and what it means for the viewer. Never just read the headline. No hype words
("shocking", "insane", "crazy", "mind-blowing", "you won't believe"), no emojis in narration,
no "In today's video", no "Hey guys".

TRUTH RULES (most important):
- Use ONLY facts found in the SOURCES you are given. Never invent numbers, dates, quotes, prices or claims.
- If something is a plan, rumor, claim or prediction, say who claims it ("Musk says...", "according to The Verge").
- Never write fake first-person quotes from real people.
- Titles and hooks may create curiosity, but the video must deliver exactly what they promise. No bait-and-switch.
- No financial, medical or legal advice.

Return ONLY valid JSON that matches the requested shape."""

HOOK_RULES = """HOOK RULES (the first 1-3 seconds decide everything):
- Write 5 hook candidates, each built on a DIFFERENT mechanism: curiosity gap, stakes, specific number,
  contrarian, timeliness, self-relevance ("your phone..."), mistake, transformation.
- Each hook max 12 words, uses a real detail from the sources, and opens a gap a stranger needs closed.
- Banned dead templates: "You won't believe", "the secret nobody tells you", "Did you know",
  "In today's video", "Let's talk about", "Hey guys".
- Score each 1-10 on: real gap, specific, true to sources, would a stranger need the next line. Pick the best.
- hook_text = the on-screen text on the FIRST FRAME: 2-6 words, ALL CAPS, must work with sound off,
  same gap as the spoken hook but not the same words."""

SCRIPT_RULES = """WRITE FOR THE EAR (this is read aloud by a voice):
- 8-14 words per sentence. Contractions (it's, they're). One number per sentence, rounded ("about 6,000").
- Ask a question right before a reveal. Use concrete details, not adjectives.
- Start with the most interesting true detail. No wind-up, no "so", no "today we".
- Titles are concrete and calm: what happened + why it matters. No ALL-CAPS words, no "SHOCKING"."""

CARD_RULES = """ON-SCREEN CARDS (they show proof, like on news channels). Each scene has "card": null or ONE card.
Use cards on about 40% of scenes, never on the first scene, never on two scenes in a row:
- {"template": "headline"} : once, in scene 2 or 3. Shows the real source headline (we fill in the text).
- {"template": "stat", "value": 6300, "prefix": "", "suffix": "lbs", "label": "of cargo on board"} : ONLY a
  number that appears in the SOURCES. Label max 6 words.
- {"template": "compare", "title": "Cost to orbit", "leftLabel": "Then", "leftValue": "$54,500/kg",
  "rightLabel": "Now", "rightValue": "$2,700/kg"} : then vs now or A vs B, values from the SOURCES, max 14 chars each.
- {"template": "list", "title": "3 things to know", "items": ["max 5 words", "max 5 words", "max 5 words"]}
- {"template": "quote", "text": "...", "who": "Name", "where": "where they said it"} : ONLY a quote that appears
  WORD FOR WORD in the SOURCES. Max 20 words. Otherwise no quote card.
- {"template": "slam", "text": "FIVE GIGAWATTS BY 2039"} : the single most striking fact in 2-4 big words, once
  per video, on a scene that says those words.
- {"template": "map", "label": "Navarino Bay", "lat": 36.93, "lon": 21.68, "zoom": 6, "highlight": ["Greece"]} :
  WHERE something happened. Real coordinates; zoom 1 (world) to 8 (a city); "highlight" = English country names.
- {"template": "timeline", "title": "Road to Navarino", "events": [{"year": "1821", "label": "max 4 words"}, ...]} :
  3-4 dated events, ONLY dates that appear in the SOURCES.
- {"template": "chart", "title": "Ships at Navarino", "bars": [{"label": "Allies", "value": 27}, ...], "unit": "",
  "prefix": ""} : 2-5 bars comparing numbers that ALL appear in the SOURCES."""

VISUAL_RULES = """VISUAL RULES: every scene has "visual": a 1-3 word STOCK FOOTAGE search query for something concrete and
filmable that MATCHES what is being said (e.g. "electric car highway", "robot arm factory", "rocket launch",
"server room", "smartphone hand"). Put the main noun FIRST. Also "visual_alt": a broader 1-2 word backup query
that surely exists on free stock sites (e.g. "rocket", "laboratory", "computer", "city night", "astronaut").
Never a person's name, brand logo or specific product name in "visual" (stock sites don't have those).
"wiki": the EXACT English Wikipedia article title of the real company, product, person, place or object this
scene is about, so we can show a real photo of it (e.g. "Amazon (company)", "MacBook Pro", "SpaceX Starship",
"Elon Musk", "Small modular reactor"). Use "" when the scene is about nothing specific.
"keywords": 1-2 important words copied exactly from that scene's text, to highlight in captions."""


# ---------- answer checks: a bad AI answer is rejected and asked again ----------

def _check_scenes(scenes, minimum: int):
    if not isinstance(scenes, list) or len(scenes) < minimum:
        raise ValueError(f"needs at least {minimum} scenes")
    for s in scenes:
        if not isinstance(s, dict) or not str(s.get("text", "")).strip():
            raise ValueError("a scene has no text")
        if not str(s.get("visual", "")).strip():
            s["visual"] = "technology"
        if not str(s.get("visual_alt", "")).strip():
            s["visual_alt"] = ""
        s["wiki"] = str(s.get("wiki") or "").strip()[:80]
        if not isinstance(s.get("keywords"), list):
            s["keywords"] = []
        s["card"] = clean_card(s.get("card"))
    for i, s in enumerate(scenes):            # no card on the first scene, never two cards in a row
        if s["card"] and (i == 0 or scenes[i - 1]["card"]):
            s["card"] = None


def _short(v, n: int) -> str:
    return " ".join(str(v).split())[:n]


def clean_card(c):
    """A card the renderer can draw, or None. Anything malformed is dropped (the scene stays)."""
    if not isinstance(c, dict):
        return None
    t = c.get("template")
    try:
        if t == "headline":
            return {"template": "headline"}
        if t == "stat":
            value = float(str(c.get("value")).replace(",", "").replace("$", ""))
            out = {"template": "stat", "value": value, "label": _short(c.get("label", ""), 48),
                   "prefix": _short(c.get("prefix") or "", 4), "suffix": _short(c.get("suffix") or "", 8)}
            out["decimals"] = int(c.get("decimals") or (0 if value.is_integer() else 1))
            return out if out["label"] else None
        if t == "compare":
            keys = ("leftLabel", "leftValue", "rightLabel", "rightValue")
            if not all(str(c.get(k, "")).strip() for k in keys):
                return None
            out = {"template": "compare", **{k: _short(c[k], 16) for k in keys}}
            if c.get("title"):
                out["title"] = _short(c["title"], 34)
            return out
        if t == "list":
            items = [_short(x, 36) for x in c.get("items", []) if str(x).strip()][:4]
            return {"template": "list", "title": _short(c.get("title", "Key points"), 34), "items": items} \
                if len(items) >= 2 else None
        if t == "map":
            lat, lon = float(c.get("lat")), float(c.get("lon"))
            if not (-85 <= lat <= 85 and -180 <= lon <= 180):
                return None
            return {"template": "map", "label": _short(c.get("label", ""), 30) or "Here", "lat": lat, "lon": lon,
                    "zoom": max(1.0, min(9.0, float(c.get("zoom") or 4))),
                    "highlight": [_short(x, 40) for x in c.get("highlight", []) if str(x).strip()][:3]}
        if t == "timeline":
            ev = [{"year": _short(e.get("year", ""), 10), "label": _short(e.get("label", ""), 34)}
                  for e in c.get("events", []) if isinstance(e, dict) and str(e.get("year", "")).strip()][:4]
            return {"template": "timeline", "title": _short(c.get("title", ""), 34), "events": ev} if len(ev) >= 2 else None
        if t == "chart":
            bars = []
            for b in c.get("bars", [])[:5]:
                if isinstance(b, dict):
                    bars.append({"label": _short(b.get("label", ""), 16),
                                 "value": float(str(b.get("value")).replace(",", "").replace("$", ""))})
            return {"template": "chart", "title": _short(c.get("title", ""), 34), "bars": bars,
                    "unit": _short(c.get("unit") or "", 6), "prefix": _short(c.get("prefix") or "", 3)} \
                if len(bars) >= 2 and all(b["label"] for b in bars) else None
        if t == "slam":
            text = _short(c.get("text", ""), 40)
            return {"template": "slam", "text": text} if 1 <= len(text.split()) <= 5 else None
        if t == "quote":
            text, who = _short(c.get("text", ""), 170), _short(c.get("who", ""), 40)
            return {"template": "quote", "text": text.strip('"“”'), "who": who,
                    "where": _short(c.get("where") or "", 40)} if text and who else None
    except (TypeError, ValueError):
        return None
    return None


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def verify_cards(scenes: list[dict], facts: str) -> list[dict]:
    """Quotes must appear word for word in the sources, and numbers must appear there too. Else: no card."""
    plain = _squash(facts)
    for s in scenes:
        c = s.get("card")
        if not c:
            continue
        if c["template"] == "quote" and _squash(c["text"]) not in plain:
            print(f"  [cards] dropped a quote not found in the sources: {c['text'][:60]}")
            s["card"] = None
        elif c["template"] == "stat":
            v = c["value"]
            forms = {f"{v:,.0f}", f"{v:.0f}", f"{v:,.{c['decimals']}f}", f"{v:.{c['decimals']}f}"}
            if not any(_squash(f) in plain for f in forms):
                print(f"  [cards] dropped a number not found in the sources: {v}")
                s["card"] = None
        elif c["template"] == "chart":
            def found(v):
                return any(_squash(f) in plain for f in {f"{v:,.0f}", f"{v:.0f}", f"{v:g}"})
            if not all(found(b["value"]) for b in c["bars"]):
                print(f"  [cards] dropped a chart with numbers not found in the sources: {c['title']}")
                s["card"] = None
        elif c["template"] == "timeline":
            if not all(_squash(e["year"]) in plain for e in c["events"]):
                print(f"  [cards] dropped a timeline with dates not found in the sources: {c['title']}")
                s["card"] = None
    return scenes


DANGLING = {"because", "and", "but", "so", "or", "that", "which", "while", "since", "if", "when", "the", "a"}


def is_unfinished(text: str) -> bool:
    text = text.strip()
    last_word = re.sub(r"[^a-z]", "", text.split()[-1].lower()) if text.split() else ""
    return text.endswith(("...", "…")) or not text.endswith((".", "!", "?", '"')) or last_word in DANGLING


def finish_ending(scenes: list[dict], question: str = "") -> list[dict]:
    """Safety net: cut an unfinished last line back to its last full sentence, so a video never ends mid-word."""
    if not scenes or not is_unfinished(scenes[-1]["text"]):
        return scenes
    text = re.sub(r"(\.\.\.|…)\s*$", "", scenes[-1]["text"].strip())
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|$)", text)]
    if ends:
        text = text[:ends[-1]]
    elif question.strip().endswith("?"):
        text = question.strip()
    else:
        text = text.rstrip(",;: ") + "?"
    scenes[-1]["text"] = text + " Tell me in the comments."
    return scenes


def _check_picks(r):
    if not isinstance(r.get("picks"), list) or not r["picks"]:
        raise ValueError("no picks")


def _check_short(r):
    _check_scenes(r.get("scenes"), 4)
    if is_unfinished(r["scenes"][-1]["text"]):
        raise ValueError("the last line is unfinished")
    if not str(r.get("youtube_title", "")).strip():
        raise ValueError("missing youtube_title")
    title = r["youtube_title"]
    r.setdefault("hook_text", "")
    if r.get("music_mood") not in ("energetic", "upbeat", "curious", "inspiring"):
        r["music_mood"] = "upbeat"
    r.setdefault("youtube_description", title)
    r.setdefault("instagram_caption", title)
    r.setdefault("tiktok_caption", title)
    if not isinstance(r.get("tags"), list):
        r["tags"] = []


def _check_long(r):
    for key in ("title", "thumbnail_text"):
        if not str(r.get(key, "")).strip():
            raise ValueError(f"missing {key}")
    _check_scenes(r.get("intro"), 1)
    _check_scenes(r.get("outro"), 1)
    if is_unfinished(r["outro"][-1]["text"]):
        raise ValueError("the outro ends unfinished")
    segs = r.get("segments")
    if not isinstance(segs, list) or len(segs) < 2:
        raise ValueError("needs at least 2 segments")
    for seg in segs:
        if not isinstance(seg, dict):
            raise ValueError("bad segment")
        _check_scenes(seg.get("scenes"), 3)
        if not str(seg.get("chapter", "")).strip():
            seg["chapter"] = "Next story"
    r.setdefault("description", "{CHAPTERS}")
    if not isinstance(r.get("tags"), list):
        r["tags"] = []
    words = sum(len(s["text"].split()) for part in [r["intro"], r["outro"]] + [g["scenes"] for g in segs]
                for s in part)
    need = CFG["long"]["target_minutes"][0] * 135
    if words < need:
        raise ValueError(f"script too short: {words} words, need at least {need}")


def pick_stories(candidates: list[dict], n: int) -> list[dict]:
    listing = "\n".join(
        f"{i}. {c['title']}  [sources: {len(c['sources'])}, age: {c['age_hours']}h, score: {c['score']}]"
        for i, c in enumerate(candidates))
    prompt = f"""Here are trending stories from the last hours (more sources + higher score = spreading faster):

{listing}

Pick the {n + 5} best stories for our niche ({CH['niche']}). Score each 1-10 on:
- MATTERS: will a normal viewer care? Does it change their life, money, job, or the future?
- PROOF: can we show it (a real headline, real numbers, real footage of the thing)?
- ANGLE: can we add a fresh point of view beyond the headline?
- RISING: is it spreading right now?
Skip: off-niche, politics fights, crime, tragedy, celebrity gossip, paywalled-only, minor software releases,
developer-only news, stories with too little information, duplicates. Prefer variety across topics.

Return: {{"picks": [{{"index": <number from list>, "thesis": "<one sentence: our point of view>",
"angle": "<the one idea the video is about>", "viral_score": <average of the 4 scores>}}]}} ordered best first."""
    picks = ask_json(SYSTEM, prompt, temperature=0.4, validate=_check_picks)["picks"]
    stories = []
    for p in picks:
        if not isinstance(p, dict):
            continue
        idx = p.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(candidates):
            continue
        c = candidates[idx]
        stories.append({"title": c["title"], "angle": p.get("angle", ""), "thesis": p.get("thesis", ""),
                        "viral_score": p.get("viral_score", 5), "sources": c["sources"]})
    return stories


def gather_facts(story: dict) -> str:
    """Download the article text of up to 3 sources. Returns '' if none could be read."""
    texts = []
    for s in story["sources"]:
        text = fetch_article(s["url"])
        if len(text) > 400:
            texts.append(f"SOURCE ({s['source']}): {s['title']}\nURL: {s['url']}\n{text}")
        if len(texts) == 3:
            break
    return "\n\n---\n\n".join(texts)


def write_short(story: dict, fmt: str) -> dict:
    lo, hi = CFG["short"]["target_seconds"]
    prompt = f"""Write a vertical short video (YouTube Shorts, Instagram Reels, TikTok) about this story.

STORY: {story['title']}
ANGLE: {story['angle']}
OUR POINT OF VIEW: {story.get('thesis', '')}
SERIES FORMAT TO USE: {fmt}

SOURCES:
{story['facts']}

LENGTH: {lo}-{hi} seconds spoken = about {int(lo * 2.9)}-{int(hi * 2.6)} words in total. One idea only.

{HOOK_RULES}

STRUCTURE:
- Scene 1 = the chosen hook (spoken).
- 5-9 scenes in total. Each scene 1-2 short sentences, max 22 words. Relentless pace, no wind-up.
- Around the middle, a rehook line that raises the stakes ("But here's the part that matters...", vary it).
- Last scene: ONE complete yes/no question tied to our point of view, that also leads naturally back into the
  hook when the Short replays (e.g. hook "Amazon is funding twelve nuclear reactors." / last line "So would
  you live next to one?"). EVERY sentence must be complete. Never end with "...", "Because", "and", "but",
  "so", "that" or any unfinished sentence.
- Open a question in the first 3 seconds and answer it near the end (70-80% of the way through).

{SCRIPT_RULES}

{CARD_RULES}

{VISUAL_RULES}

METADATA:
- youtube_title: 4-6 words, max 40 characters (phones cut longer titles): the named thing + a specific
  number or change (e.g. "Nvidia's chip is 4x faster"), accurate, no hashtags in the title
- youtube_description: 2-3 short lines, then a line with #Shorts and 2-4 more hashtags, then "Sources:" and
  the source names
- music_mood: one of "energetic", "upbeat", "curious", "inspiring" (fits the story's feeling)
- tags: 8-12 search tags
- instagram_caption: 1-2 punchy lines + the question + 3-5 relevant hashtags
- tiktok_caption: max 150 characters + 3-5 hashtags

Return JSON:
{{"hook_candidates": [{{"mechanism": "...", "text": "...", "score": 0}}],
 "hook_text": "ALL CAPS FIRST FRAME TEXT",
 "scenes": [{{"text": "...", "visual": "...", "visual_alt": "...", "wiki": "...", "keywords": ["..."], "card": null}}],
 "question": "the comment question you used", "music_mood": "curious",
 "youtube_title": "...", "youtube_description": "...", "tags": ["..."],
 "instagram_caption": "...", "tiktok_caption": "..."}}"""
    return ask_json(SYSTEM, prompt, validate=_check_short)


def write_long(stories: list[dict]) -> dict:
    lo, hi = CFG["long"]["target_minutes"]
    blocks = []
    for i, s in enumerate(stories):
        blocks.append(f"STORY {i + 1}: {s['title']}\nANGLE: {s['angle']}\nVIRAL SCORE: {s['viral_score']}\n"
                      f"SOURCES:\n{s['facts'][:2600]}")
    prompt = f"""Write a horizontal YouTube video: a roundup of today's top {len(stories)} stories in our niche.

{chr(10).join(blocks)}

LENGTH: {lo}-{hi} minutes spoken. Write {lo * 175}-{hi * 160} words in total (each segment at least
{int(lo * 175 / 5)} words). This is a HARD minimum: under {lo * 140} words will be rejected. Count your words.

STRUCTURE (built for retention):
- Count DOWN from story {len(stories)} to story 1. Story 1 must be the biggest one. You choose the order.
- intro (15-25 seconds): a strong hook about the biggest story, but hold the full reveal for the end
  ("...and number one could change how you ..."). Then one line about what's coming. No "welcome back".
- segments: one per story. Each 180-280 words: what happened, why it matters, what happens next.
  Start each segment with a fresh mini-hook. End each one with a bridge that teases the next story.
  Every 60-90 seconds add a re-hook line that opens a new question.
- chapter: each chapter title is a short QUESTION (e.g. "Why is Amazon buying nuclear?").
- outro (15-25 seconds): a question for the comments, then a short ask to subscribe for daily updates.

Each scene: 1-3 spoken sentences. Intro 2-4 scenes, each segment 6-12 scenes, outro 2-3 scenes.

{SCRIPT_RULES}

{CARD_RULES}
(In the long video, use a "headline" card once per segment, in its 2nd or 3rd scene.)

{VISUAL_RULES}

METADATA:
- title: max 70 characters, curious but accurate, the biggest story's key words first
- thumbnail_text: 2-4 words, ALL CAPS, curiosity but concrete and true (no "SHOCKING")
- description: 3-4 lines summary. Write the token {{CHAPTERS}} on its own line where chapters go.
  Then "Sources:" with the source names.
- tags: 10-15
- pinned_comment: a question that starts a discussion

Return JSON:
{{"title": "...", "thumbnail_text": "...", "description": "...", "tags": ["..."], "pinned_comment": "...",
 "intro": [{{"text": "...", "visual": "...", "visual_alt": "...", "wiki": "...", "keywords": ["..."], "card": null}}],
 "segments": [{{"story": <story number from the list above>, "chapter": "short chapter title",
               "scenes": [{{"text": "...", "visual": "...", "visual_alt": "...", "wiki": "...", "keywords": ["..."], "card": null}}]}}],
 "outro": [{{"text": "...", "visual": "...", "visual_alt": "...", "wiki": "...", "keywords": ["..."], "card": null}}]}}"""
    return ask_json(SYSTEM, prompt, validate=_check_long)


def fact_check(scenes: list[dict], facts: str) -> list[dict]:
    """Second pass: fix any claim not supported by the sources. Returns the (maybe corrected) scenes."""
    if not CFG["llm"].get("fact_check") or not facts:
        return scenes
    prompt = f"""Check this video script against the SOURCES. Fix every claim, number, name or date that is not
supported by the sources (remove it, or attribute it: "according to ..."). Keep the style, length,
structure, visual, visual_alt, keywords and card fields. Also check every card: its numbers must be in the
sources, and a quote card must match the sources word for word; otherwise set that card to null.
Change as little as possible.

SOURCES:
{facts[:9000]}

SCRIPT:
{json.dumps(scenes, ensure_ascii=False)}

Return JSON: {{"issues": ["what you fixed"], "scenes": [same shape as input]}}"""
    try:
        result = ask_json(SYSTEM, prompt, temperature=0.2,
                          validate=lambda r: _check_scenes(r.get("scenes"), max(3, len(scenes) - 2)))
    except Exception as e:
        print(f"  [fact-check] skipped: {e}")
        return scenes
    fixed = result.get("scenes")
    if isinstance(fixed, list) and len(fixed) >= max(3, len(scenes) - 2) and all("text" in s for s in fixed):
        for issue in result.get("issues", [])[:10]:
            print(f"  [fact-check] fixed: {issue}")
        return fixed
    return scenes


# ---------- long videos in stand-alone chapters (the multi-channel factory) ----------

def _check_doc(r):
    for key in ("title", "thumbnail_text"):
        if not str(r.get(key, "")).strip():
            raise ValueError(f"missing {key}")
    _check_scenes(r.get("intro"), 2)
    _check_scenes(r.get("outro"), 1)
    chs = r.get("chapters")
    lo, hi = CFG["long_script"]["chapters"]
    if not isinstance(chs, list) or len(chs) < lo:
        raise ValueError(f"needs at least {lo} chapters")
    for c in chs:
        if not isinstance(c, dict):
            raise ValueError("bad chapter")
        _check_scenes(c.get("scenes"), 3)
        c["title"] = str(c.get("title") or "Next").strip()[:60]
        c["hook_text"] = str(c.get("hook_text") or c["title"]).strip()[:40]
        c["bridge"] = str(c.get("bridge") or "").strip()
        try:
            c["clip_score"] = float(c.get("clip_score", 5))
        except (TypeError, ValueError):
            c["clip_score"] = 5.0
        if is_unfinished(c["scenes"][-1]["text"]):
            raise ValueError("a chapter ends unfinished")
    if is_unfinished(r["outro"][-1]["text"]):
        raise ValueError("the outro ends unfinished")
    words = sum(len(s["text"].split()) for part in [r["intro"], r["outro"]] + [c["scenes"] for c in chs]
                for s in part)
    need = int(CFG["long_script"]["total_words"][0] * 0.9)
    if words < need:
        raise ValueError(f"script too short: {words} words, need at least {need}")
    if r.get("music_mood") not in ("energetic", "upbeat", "curious", "inspiring"):
        r["music_mood"] = "curious"
    r.setdefault("description", "{CHAPTERS}")
    if not isinstance(r.get("tags"), list):
        r["tags"] = []


def channel_system(ch: dict) -> str:
    return f"""You are the head writer of a faceless YouTube channel about {ch['niche']}.
Voice of the channel: {ch['style']}. Language: English.

TRUTH RULES (most important):
- Use ONLY facts found in the SOURCES. Never invent numbers, dates, quotes, names or claims.
- Where historians or scientists disagree, or something is uncertain, say so ("historians still debate...").
- Never write fake first-person quotes from real people. No medical, legal or financial advice.
- Titles and hooks create curiosity, but the video must deliver exactly what they promise.

Return ONLY valid JSON that matches the requested shape."""


SCENE_SHAPE = ('{"text": "...", "visual": "...", "visual_alt": "...", "wiki": "...", "keywords": ["..."], '
               '"card": null}')


def _check_outline(r):
    lo, hi = CFG["long_script"]["chapters"]
    for key in ("title", "thumbnail_text"):
        if not str(r.get(key, "")).strip():
            raise ValueError(f"missing {key}")
    chs = r.get("chapters")
    if not isinstance(chs, list) or not lo <= len(chs) <= hi + 1:
        raise ValueError(f"needs {lo}-{hi} chapters, got {len(chs) if isinstance(chs, list) else 0}")
    for c in chs:
        if not isinstance(c, dict) or not str(c.get("title", "")).strip() or not str(c.get("point", "")).strip():
            raise ValueError("every chapter needs a title and a point")


def _check_part(minimum_words: int, minimum_scenes: int = 3):
    def check(r):
        _check_scenes(r.get("scenes"), minimum_scenes)
        n = sum(len(x["text"].split()) for x in r["scenes"])
        if n < minimum_words:
            raise ValueError(f"too short: {n} words, write at least {minimum_words}")
        if is_unfinished(r["scenes"][-1]["text"]):
            raise ValueError("the last line is unfinished")
    return check


def write_doc(topic: dict, ch: dict, facts: str) -> dict:
    """A long video (8-10 min) of 4-6 stand-alone chapters. Written IN PARTS (outline, then every chapter,
    then intro/outro), because AI models only write ~700 words reliably per answer."""
    lo_c, hi_c = CFG["long_script"]["chapters"]
    lo_w, hi_w = CFG["long_script"]["chapter_words"]
    system = channel_system(ch)
    src = facts[:24000]
    base = f"""TOPIC: {topic['title']}
THE QUESTION THE VIDEO ANSWERS: {topic.get('question', '')}
OUR POINT OF VIEW: {topic.get('thesis', '')}
FAVOURITE ON-SCREEN CARDS FOR THIS CHANNEL: {ch.get('cards', '')}

SOURCES:
{src}"""

    # 1) outline
    outline = ask_json(system, f"""{base}

Plan a long YouTube video (8-10 minutes) as {lo_c}-{hi_c} chapters. Each chapter is ONE complete idea that
also works alone as a Short. Order them so curiosity builds; the main question is answered around 70-80% of the
way through, followed by a final twist or insight.

Return JSON: {{"title": "max 60 characters: the named thing + a specific number or change, curious but accurate",
"thumbnail_text": "2-4 words ALL CAPS, true", "description": "3-4 lines, then the token {{CHAPTERS}} on its own
line, then 3-5 hashtags", "tags": ["10-15 tags"], "pinned_comment": "a question that starts a discussion",
"music_mood": "energetic|upbeat|curious|inspiring",
"chapters": [{{"title": "a short QUESTION for the chapter card", "point": "the one idea of this chapter",
"facts": ["2-4 key facts with numbers/dates, copied from the SOURCES"], "hook_text": "2-6 words ALL CAPS for the
Short's first frame", "clip_score": <1-10: how well it works alone as a Short>}}]}}""",
                       temperature=0.7, validate=_check_outline)
    titles = [c["title"] for c in outline["chapters"]]

    # 2) every chapter on its own
    chapters = []
    for i, c in enumerate(outline["chapters"]):
        nxt = titles[i + 1] if i + 1 < len(titles) else ""
        part = ask_json(system, f"""{base}

THE VIDEO'S CHAPTERS: {json.dumps(titles, ensure_ascii=False)}
WRITE CHAPTER {i + 1}: "{c['title']}"
ITS POINT: {c['point']}
KEY FACTS: {json.dumps(c.get('facts', []), ensure_ascii=False)}

Write EXACTLY 6 scenes. Each scene is 2 full spoken sentences of 12-16 words each (so about 130 words in
total). It must work ALONE as a Short:
- the first line is a hook that makes sense with no context (never "as we saw", "next", "meanwhile");
- one complete idea with at least one hard number or date from the SOURCES;
- the last line is a strong, complete closing line.
Also write "bridge": ONE sentence that leads into the next chapter{f' ("{nxt}")' if nxt else ''}
{'(use "" because this is the last chapter)' if not nxt else ''}.

{SCRIPT_RULES}

{CARD_RULES}

{VISUAL_RULES}

Return JSON: {{"scenes": [{SCENE_SHAPE}], "bridge": "..."}}""", validate=_check_part(70), max_tries=5)
        chapters.append({"title": c["title"][:60], "hook_text": str(c.get("hook_text") or c["title"])[:40],
                         "clip_score": float(c.get("clip_score") or 5), "bridge": str(part.get("bridge") or ""),
                         "scenes": part["scenes"]})
        print(f"  [writer] chapter {i + 1}/{len(titles)} written")

    # 3) intro and outro
    ends = ask_json(system, f"""{base}

THE VIDEO'S CHAPTERS: {json.dumps(titles, ensure_ascii=False)}
Write the INTRO and the OUTRO of this long video.
- intro: EXACTLY 4 scenes of 2 sentences each (about 110 words). Open cold on the most surprising TRUE detail,
  pose the question, promise the payoff. No "welcome", no "in this video".
- outro: EXACTLY 3 scenes of 2 sentences each (about 70 words): a question for the comments tied to our point of
  view, then ask to subscribe.

{SCRIPT_RULES}

{VISUAL_RULES}

Return JSON: {{"intro": [{SCENE_SHAPE}], "outro": [{SCENE_SHAPE}]}}""",
                   validate=lambda r: (_check_part(80)({"scenes": r.get("intro")}),
                                       _check_part(35, 2)({"scenes": r.get("outro")})), max_tries=5)
    doc = {k: outline.get(k) for k in ("title", "thumbnail_text", "description", "tags", "pinned_comment",
                                         "music_mood")}
    doc.update({"intro": ends["intro"], "outro": ends["outro"], "chapters": chapters})
    _check_doc(doc)
    return doc


def check_doc(doc: dict, facts: str) -> dict:
    """Fact-check the whole long script against the sources in 3 batches (fewer AI requests), then check every
    card's numbers and quotes. A batch that comes back in the wrong shape keeps its original scenes."""
    parts = [doc["intro"]] + [c["scenes"] for c in doc["chapters"]] + [doc["outro"]]
    n = len(parts)
    groups = [list(range(i, min(n, i + (n + 2) // 3))) for i in range(0, n, (n + 2) // 3)]
    for g in groups:
        flat = [s for i in g for s in parts[i]]
        checked = fact_check(flat, facts)
        if len(checked) == len(flat):
            k = 0
            for i in g:
                parts[i][:] = checked[k:k + len(parts[i])]
                k += len(parts[i])
    doc["intro"], doc["outro"] = verify_cards(parts[0], facts), verify_cards(parts[-1], facts)
    for c, p in zip(doc["chapters"], parts[1:-1]):
        c["scenes"] = verify_cards(p, facts)
    return doc
