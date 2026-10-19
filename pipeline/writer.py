"""Writes scripts with the free AI. Rules for hooks, retention and truth are baked into the prompts.

Hook and Shorts rules are adapted from the MIT-licensed social-media-skills/skills
pack (hook-writer, youtube-shorts).
"""
import json
import re

from .config import CFG
from .llm import ask_json
from .trends import fetch_article

CH = CFG["channel"]

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
  WORD FOR WORD in the SOURCES. Max 20 words. Otherwise no quote card."""

VISUAL_RULES = """VISUAL RULES: every scene has "visual": a 1-3 word STOCK FOOTAGE search query for something concrete and
filmable that MATCHES what is being said (e.g. "electric car highway", "robot arm factory", "rocket launch",
"server room", "smartphone hand"). Put the main noun FIRST. Also "visual_alt": a broader 1-2 word backup query
that surely exists on free stock sites (e.g. "rocket", "laboratory", "computer", "city night", "astronaut").
Never a person's name, brand logo or specific product name (stock sites don't have those).
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
- Last scene: a short question that makes people comment, then ONE short, complete closing sentence
  (for example "Tell me in the comments."). EVERY sentence must be complete. Never end with "...",
  "Because", "and", "but", "so", "that" or any unfinished sentence.

{SCRIPT_RULES}

{CARD_RULES}

{VISUAL_RULES}

METADATA:
- youtube_title: max 70 characters, the key search words first, concrete and accurate, ends with " #Shorts"
- youtube_description: 2-3 short lines, then "Sources:" and the source names
- tags: 8-12 search tags
- instagram_caption: 1-2 punchy lines + the question + 5-8 relevant hashtags
- tiktok_caption: max 150 characters + 3-5 hashtags

Return JSON:
{{"hook_candidates": [{{"mechanism": "...", "text": "...", "score": 0}}],
 "hook_text": "ALL CAPS FIRST FRAME TEXT",
 "scenes": [{{"text": "...", "visual": "...", "visual_alt": "...", "keywords": ["..."], "card": null}}],
 "question": "the comment question you used",
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

LENGTH: {lo}-{hi} minutes spoken = about {lo * 155}-{hi * 150} words in total.

STRUCTURE (built for retention):
- Count DOWN from story {len(stories)} to story 1. Story 1 must be the biggest one. You choose the order.
- intro (15-25 seconds): a strong hook about the biggest story, but hold the full reveal for the end
  ("...and number one could change how you ..."). Then one line about what's coming. No "welcome back".
- segments: one per story. Each 150-260 words: what happened, why it matters, what happens next.
  Start each segment with a fresh mini-hook. End each one with a bridge that teases the next story.
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
 "intro": [{{"text": "...", "visual": "...", "visual_alt": "...", "keywords": ["..."], "card": null}}],
 "segments": [{{"story": <story number from the list above>, "chapter": "short chapter title",
               "scenes": [{{"text": "...", "visual": "...", "visual_alt": "...", "keywords": ["..."], "card": null}}]}}],
 "outro": [{{"text": "...", "visual": "...", "visual_alt": "...", "keywords": ["..."], "card": null}}]}}"""
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
