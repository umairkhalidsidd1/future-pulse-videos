"""Writes scripts with the free AI. Rules for hooks, retention and truth are baked into the prompts.

Hook and Shorts rules are adapted from the MIT-licensed social-media-skills/skills
pack (hook-writer, youtube-shorts).
"""
import json

from .config import CFG
from .llm import ask_json
from .trends import fetch_article

CH = CFG["channel"]

SYSTEM = f"""You are the head writer of "{CH['name']}", a faceless YouTube / TikTok / Instagram channel about
{CH['niche']}. Language: {CH['language']}.

Voice: an energetic, smart friend explaining the news. Short, punchy, spoken sentences. No fluff, no filler,
no emojis in narration, no "In today's video", no "Hey guys".

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

VISUAL_RULES = """VISUAL RULES: every scene has "visual": a 1-3 word STOCK FOOTAGE search query for something concrete and
filmable (e.g. "electric car highway", "robot arm factory", "rocket launch night", "server room", "smartphone hand").
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
        if not isinstance(s.get("keywords"), list):
            s["keywords"] = []


def _check_picks(r):
    if not isinstance(r.get("picks"), list) or not r["picks"]:
        raise ValueError("no picks")


def _check_short(r):
    _check_scenes(r.get("scenes"), 4)
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

Pick the {n + 5} stories with the best chance of going viral as short videos for our niche
({CH['niche']}). Prefer: rising right now, big curiosity, clear visual idea, broad appeal, a real "what this
means for you" angle. Skip: off-niche, politics fights, crime, tragedy, celebrity gossip, paywalled-only,
stories with too little information, duplicates of each other.

Return: {{"picks": [{{"index": <number from list>, "angle": "<the one idea the video is about>",
"why_viral": "<short reason>", "viral_score": <1-10>}}]}} ordered best first."""
    picks = ask_json(SYSTEM, prompt, temperature=0.4, validate=_check_picks)["picks"]
    stories = []
    for p in picks:
        if not isinstance(p, dict):
            continue
        idx = p.get("index")
        if not isinstance(idx, int) or not 0 <= idx < len(candidates):
            continue
        c = candidates[idx]
        stories.append({"title": c["title"], "angle": p.get("angle", ""), "viral_score": p.get("viral_score", 5),
                        "sources": c["sources"]})
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
FORMAT TO USE: {fmt}

SOURCES:
{story['facts']}

LENGTH: {lo}-{hi} seconds spoken = about {int(lo * 2.9)}-{int(hi * 2.6)} words in total. One idea only.

{HOOK_RULES}

STRUCTURE:
- Scene 1 = the chosen hook (spoken).
- 5-9 scenes in total. Each scene 1-2 short sentences, max 22 words. Relentless pace, no wind-up.
- Around the middle, a rehook line that raises the stakes ("But here's the part that matters...", vary it).
- Last scene: a short question that makes people comment, then a final line that flows naturally back into
  the first words of the hook, so the video loops seamlessly when it replays.

{VISUAL_RULES}

METADATA:
- youtube_title: max 70 characters, the key search words first, accurate, ends with " #Shorts"
- youtube_description: 2-3 short lines, then "Sources:" and the source names
- tags: 8-12 search tags
- instagram_caption: 1-2 punchy lines + the question + 5-8 relevant hashtags
- tiktok_caption: max 150 characters + 3-5 hashtags

Return JSON:
{{"hook_candidates": [{{"mechanism": "...", "text": "...", "score": 0}}],
 "hook_text": "ALL CAPS FIRST FRAME TEXT",
 "scenes": [{{"text": "...", "visual": "...", "keywords": ["..."]}}],
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

{VISUAL_RULES}

METADATA:
- title: max 70 characters, curious but accurate, the biggest story's key words first
- thumbnail_text: 2-4 words, ALL CAPS, huge emotion/curiosity, must be true
- description: 3-4 lines summary. Write the token {{CHAPTERS}} on its own line where chapters go.
  Then "Sources:" with the source names.
- tags: 10-15
- pinned_comment: a question that starts a discussion

Return JSON:
{{"title": "...", "thumbnail_text": "...", "description": "...", "tags": ["..."], "pinned_comment": "...",
 "intro": [{{"text": "...", "visual": "...", "keywords": ["..."]}}],
 "segments": [{{"story": <story number from the list above>, "chapter": "short chapter title",
               "scenes": [{{"text": "...", "visual": "...", "keywords": ["..."]}}]}}],
 "outro": [{{"text": "...", "visual": "...", "keywords": ["..."]}}]}}"""
    return ask_json(SYSTEM, prompt, validate=_check_long)


def fact_check(scenes: list[dict], facts: str) -> list[dict]:
    """Second pass: fix any claim not supported by the sources. Returns the (maybe corrected) scenes."""
    if not CFG["llm"].get("fact_check") or not facts:
        return scenes
    prompt = f"""Check this video script against the SOURCES. Fix every claim, number, name or date that is not
supported by the sources (remove it, or attribute it: "according to ..."). Keep the style, length,
structure, visual and keywords fields. Change as little as possible.

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
