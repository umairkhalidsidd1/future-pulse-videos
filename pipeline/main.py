"""The daily machine.

  python -m pipeline auto            do the next unfinished job of today (what GitHub runs)
  python -m pipeline plan            only pick today's stories and write the scripts
  python -m pipeline render short:0  render one job without uploading (also: long)
  python -m pipeline test            offline test: sample scripts, no keys, no uploads
  python -m pipeline rewrite [short:2 ... long]   rewrite today's scripts with the current rules (same stories)
  python -m pipeline batch           render ALL of today's videos without uploading (for review)
"""
import json
import random
import sys
from datetime import date
from pathlib import Path

from . import align, captions, remotion_render, render, thumbnail, trends, tts, writer
from .config import CFG, DATA, OUT, safe_err, today
from .stock import Stock
from .upload import instagram, tiktok, youtube

MAX_ATTEMPTS = 3
CREDIT = ("Footage: Pixabay and NASA (where marked). Voice: AI narration.\n"
          + CFG["audio"].get("music_credit", ""))


# ---------- plan ----------

def plan_path(day: str) -> Path:
    return DATA / "plans" / f"{day}.json"


def load_plan(day: str) -> dict | None:
    p = plan_path(day)
    return json.loads(p.read_text()) if p.exists() else None


def save_plan(plan: dict):
    plan_path(plan["date"]).write_text(json.dumps(plan, indent=1, ensure_ascii=False))


def make_plan(day: str) -> dict:
    n = CFG["channel"]["stories_per_day"]
    print("[plan] finding trending stories")
    candidates = trends.collect()
    if len(candidates) < n:
        raise RuntimeError(f"Only {len(candidates)} trending stories found")
    picks = writer.pick_stories(candidates, n)

    stories = []
    for s in picks:
        if len(stories) == n:
            break
        s["facts"] = writer.gather_facts(s)
        if len(s["facts"]) < 600:
            print(f"  [plan] skipped (could not read sources): {s['title'][:70]}")
            continue
        stories.append(s)
    if len(stories) < 2:
        raise RuntimeError(f"Only {len(stories)} stories had readable sources")
    if len(stories) < n:
        print(f"  [plan] only {len(stories)} stories had readable sources; making fewer Shorts today")

    plan = {"date": day, "stories": stories}
    write_scripts(plan, [f"short:{i}" for i in range(len(stories))] + ["long"])
    plan.update({
            "jobs": [{"id": j, "attempts": 0, "status": {}, "links": {}} for j in CFG["channel"]["job_order"]
                     if j == "long" or int(j.split(":")[1]) < len(stories)]})
    save_plan(plan)
    trends.add_history([s["title"] for s in stories])
    return plan


def save_safe(plan: dict):
    """Save the plan without the downloaded article text (the repo is public)."""
    save_plan({**plan, "stories": [{k: v for k, v in s.items() if k != "facts"} for s in plan["stories"]]})


def write_scripts(plan: dict, which: list[str]):
    """Write (or rewrite) the scripts of the given jobs with the current rules. Downloads the sources again
    if needed; the article text is never saved (the repo is public)."""
    stories = plan["stories"]
    formats = CFG["short"]["formats"]
    need = {int(j.split(":")[1]) for j in which if j.startswith("short:")}
    if "long" in which:
        need |= set(range(len(stories)))
    for i in sorted(need):
        if not stories[i].get("facts"):
            stories[i]["facts"] = writer.gather_facts(stories[i])
    for j in which:
        if not j.startswith("short:"):
            continue
        i = int(j.split(":")[1])
        s, fmt = stories[i], formats[series_of(plan, i)]
        print(f"[plan] writing short {i}: {s['title'][:70]}  ({fmt.split(':')[0]})")
        s["short"] = writer.write_short(s, fmt)
        s["short"]["scenes"] = writer.verify_cards(writer.fact_check(s["short"]["scenes"], s["facts"]), s["facts"])
        if plan.get("jobs"):
            save_safe(plan)       # keep each finished script even if a later one fails
    if "long" in which:
        print("[plan] writing the long video")
        long = writer.write_long(stories)
        for seg in long.get("segments", []):
            try:
                idx = int(seg.get("story", 1)) - 1
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(stories):
                seg["scenes"] = writer.verify_cards(writer.fact_check(seg["scenes"], stories[idx]["facts"]),
                                                    stories[idx]["facts"])
        plan["long"] = long
    for s in stories:  # the repo is public: keep the downloaded article text out of it
        s.pop("facts", None)


def batch(plan: dict):
    """Renders every job of the day without uploading, then prints a summary for review."""
    rows = []
    for job in plan["jobs"]:
        try:
            built = run_job(plan, {"id": job["id"], "attempts": 0, "status": {}, "links": {}}, upload=False)
            rows.append((job["id"], f"{built['duration']:.0f} s", str(built["video"])))
        except Exception as e:
            rows.append((job["id"], "FAILED", safe_err(e)))
    print("\n[batch] summary")
    for r in rows:
        print("  ", *r)


# ---------- build one video ----------

def theme_for(day: str) -> dict:
    themes = CFG["captions"]["themes"]
    try:
        n = date.fromisoformat(day).toordinal()
    except ValueError:
        n = 0
    return themes[n % len(themes)]


LOOKS = [  # one look per series (index in config short.formats); long videos use LONG_LOOK
    {"cardStyle": "light", "captionY": 0.60, "hookTilt": -2},
    {"cardStyle": "dark", "captionY": 0.62, "hookTilt": 2},
    {"cardStyle": "dark", "captionY": 0.58, "hookTilt": -1},
    {"cardStyle": "accent", "captionY": 0.60, "hookTilt": 0},
    {"cardStyle": "light", "captionY": 0.63, "hookTilt": 2},
]
LONG_LOOK = {"cardStyle": "dark", "captionY": 0.6, "hookTilt": 0}


def series_of(plan: dict, index: int) -> int:
    n = len(CFG["short"]["formats"])
    try:
        return (date.fromisoformat(plan["date"]).toordinal() + index) % n
    except ValueError:
        return index % n


def headline_card(story: dict, day: str, scenes: list[dict] | None = None) -> dict:
    """The REAL headline of the story's best source, for the on-screen headline card."""
    srcs = story.get("sources") or [{"title": story["title"], "source": "", "url": ""}]
    best = next((x for x in srcs if x.get("source") not in remotion_render.AGGREGATORS), srcs[0])
    try:
        when = date.fromisoformat(day).strftime("%b %-d")
    except ValueError:
        when = ""
    title = " ".join(best["title"].split())[:110]
    keys = {k.lower() for sc in scenes or [] for kw in sc.get("keywords", []) for k in kw.split()}
    words = [w for w in title.split() if len(w) > 3]
    marked = [w for w in words if w.lower().strip(".,:;'\"") in keys][:3] or sorted(words, key=len)[-2:]
    return {"template": "headline", "source": remotion_render.publisher(best) or "News", "title": title,
            "date": when, "highlight": marked}


def fill_cards(scenes: list[dict], story: dict | None, day: str) -> list[dict]:
    for sc in scenes:
        card = sc.get("card")
        if card and card.get("template") == "headline":
            sc["card"] = headline_card(story, day, scenes) if story else None
    return scenes


def draw(*, kind: str, scenes, timings, total, words, wav, work: Path, out: Path, seed: str, day: str,
         hook: str, extra_cards: list | None = None, overlays: list | None = None, whoosh=None,
         mood: str | None = None, look: dict | None = None) -> tuple[list, list]:
    """Make the picture + sound. Pro engine first; if it fails, the simple FFmpeg engine so the day isn't lost.
    Returns (clean footage files for the thumbnail, credit lines for the description)."""
    stock = Stock(vertical=kind == "short", seed=seed)
    theme = theme_for(day)
    try:
        if CFG.get("render", {}).get("engine", "remotion") == "remotion":
            clips = remotion_render.render(kind=kind, scenes=scenes, timings=timings, total=total, words=words,
                                           voice_wav=wav, stock=stock, work=work, out_path=out, seed=seed,
                                           theme=theme, hook=hook, extra_cards=extra_cards, whoosh_scenes=whoosh,
                                           mood=mood, look=look)
            stock.save_used()
            return clips, stock.credits()
    except Exception as e:
        print(f"  [render] pro engine failed, using the simple engine: {safe_err(e)}")
    s = CFG[kind]
    ass = work / "captions.ass"
    captions.build_ass(words, ass, width=s["width"], height=s["height"], vertical=kind == "short", theme=theme,
                       total=total + 0.5, overlays=overlays or [],
                       progress_bar=kind == "short" and CFG["captions"].get("progress_bar", False))
    segments = render.render(kind=kind, scenes=scenes, timings=timings, total=total, voice_wav=wav,
                             ass_path=ass, stock=stock, work=work, out_path=out, seed=seed, whoosh_scenes=whoosh)
    stock.save_used()
    return segments, stock.credits()


def build_short(plan: dict, index: int, work: Path) -> dict:
    story = plan["stories"][index]
    sc = story["short"]
    scenes = fill_cards(writer.finish_ending(sc["scenes"], sc.get("question", "")), story, plan["date"])
    if not scenes[-1].get("card") and sc.get("question"):
        scenes[-1]["card"] = {"template": "outro", "question": sc["question"], "cta": "Follow for daily tech news"}
    seed = f"{plan['date']}-short-{index}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"[short {index}] voice")
    wav = work / "voice.wav"
    spans, total = tts.synth(scenes, wav, "short")
    print(f"[short {index}] {total:.1f} s, exact caption timing")
    words, timings = align.align_script(wav, scenes, spans)
    print(f"[short {index}] video")
    out = work / f"short_{index}.mp4"
    hook = sc.get("hook_text", "")
    _, credits = draw(kind="short", scenes=scenes, timings=timings, total=total, words=words, wav=wav, work=work, out=out,
         seed=seed, day=plan["date"], hook=hook, mood=sc.get("music_mood"), look=LOOKS[series_of(plan, index)],
         overlays=[{"text": hook, "start": 0, "end": 2.6, "style": "Hook"}])
    sources = "\n".join(f"- {x['source']}: {x['url']}" for x in story["sources"][:4] if x.get("url"))
    return {"video": out, "duration": total,
            "youtube": {"title": sc["youtube_title"],
                        "description": f"{sc['youtube_description']}\n\n{sources}\n\n{CREDIT}" +
                                       "".join(f"\n{c}" for c in credits),
                        "tags": sc.get("tags", []), "comment": sc.get("question")},
            "instagram": sc.get("instagram_caption", sc["youtube_title"]),
            "tiktok": sc.get("tiktok_caption", sc["youtube_title"])}


def build_long(plan: dict, work: Path) -> dict:
    lg = plan["long"]
    scenes, overlays_at, chapters, whoosh = [], [], [], set()
    chapters.append(("Intro", 0))
    scenes += [{**x, "card": None} for x in lg["intro"]]
    total_segments = len(lg["segments"])
    for n, seg in enumerate(lg["segments"]):
        number = total_segments - n
        chapters.append((f"#{number} {seg['chapter']}", len(scenes)))
        overlays_at.append((len(scenes), f"#{number}", seg["chapter"]))
        whoosh.add(len(scenes))
        try:
            story = plan["stories"][int(seg.get("story", 1)) - 1]
        except (TypeError, ValueError, IndexError):
            story = None
        seg_scenes = fill_cards([dict(x) for x in seg["scenes"]], story, plan["date"])
        seg_scenes[0]["card"] = None          # the chapter title shows at the start of each segment
        scenes += seg_scenes
    chapters.append(("What do you think?", len(scenes)))
    whoosh.add(len(scenes))
    outro = [dict(x) for x in writer.finish_ending(lg["outro"])]
    for x in outro:
        x["card"] = None
    if lg.get("pinned_comment"):
        outro[-1]["card"] = {"template": "outro", "question": lg["pinned_comment"],
                             "cta": "Subscribe for daily tech news"}
    scenes += outro

    seed = f"{plan['date']}-long"
    work.mkdir(parents=True, exist_ok=True)
    print(f"[long] voice for {len(scenes)} scenes")
    wav = work / "voice.wav"
    spans, total = tts.synth(scenes, wav, "long")
    print(f"[long] {total / 60:.1f} min, exact caption timing")
    words, timings = align.align_script(wav, scenes, spans)
    fps = CFG["long"]["fps"]
    overlays = [{"text": lg["thumbnail_text"], "start": 0, "end": 2.8, "style": "Hook"}]
    overlays += [{"text": f"{num}  {title.upper()}", "start": timings[i][0], "end": timings[i][0] + 3.5, "style": "Tag"}
                 for i, num, title in overlays_at]
    chapter_cards = [{"from": round(timings[i][0] * fps), "duration": round(3.5 * fps), "template": "chapter",
                      "data": {"number": num, "title": title}} for i, num, title in overlays_at]
    print("[long] video")
    out = work / "long.mp4"
    clips, credits = draw(kind="long", scenes=scenes, timings=timings, total=total, words=words, wav=wav, work=work, out=out,
                 seed=seed, day=plan["date"], hook=lg["thumbnail_text"], extra_cards=chapter_cards,
                 overlays=overlays, whoosh=whoosh, mood="inspiring", look=LONG_LOOK)
    source = clips[min(len(clips) - 1, round(len(clips) * 0.8))] if clips else out   # story #1 is near the end
    at = 0.0 if source.suffix.lower() in render.IMAGE_EXT else 1.0
    thumb = thumbnail.make(source, lg["thumbnail_text"], work / "thumbnail.jpg", at=at)
    chapter_text = render.chapter_times(timings, chapters)
    sources = "\n".join(f"- {x['source']}: {x['url']}" for st in plan["stories"] for x in st["sources"][:2]
                        if x.get("url"))
    desc = lg["description"].replace("{CHAPTERS}", "Chapters:\n" + chapter_text)
    if "Chapters:" not in desc:
        desc += "\n\nChapters:\n" + chapter_text
    return {"video": out, "thumbnail": thumb, "duration": total,
            "youtube": {"title": lg["title"], "description": f"{desc}\n\n{sources}\n\n{CREDIT}" +
                                                         "".join(f"\n{c}" for c in credits),
                        "tags": lg.get("tags", []), "comment": lg.get("pinned_comment")}}


# ---------- upload ----------

def publish(job: dict, built: dict, kind: str, save=lambda: None):
    """Posts to every set-up platform not yet done. Upload ids are saved in job["pending"] first,
    so a retry checks the earlier upload instead of posting the same video twice."""
    pending = job.setdefault("pending", {})
    targets = {"youtube": youtube} if kind == "long" else {"youtube": youtube, "instagram": instagram,
                                                           "tiktok": tiktok}
    for name, mod in targets.items():
        if job["status"].get(name) == "done":
            continue
        if not mod.ready():
            job["status"][name] = "not set up"
            continue
        try:
            if name == "youtube":
                y = built["youtube"]
                job["links"][name] = "https://youtu.be/" + youtube.upload(
                    built["video"], title=y["title"], description=y["description"], tags=y["tags"],
                    thumbnail=built.get("thumbnail"), comment=y.get("comment"))
            else:
                job["links"][name] = mod.upload(built["video"], built[name], pending, save)
            job["status"][name] = "done"
        except Exception as e:
            job["status"][name] = "failed"
            print(f"  [{name}] FAILED: {safe_err(e)}")
        save()


def run_job(plan: dict, job: dict, upload: bool = True, save=lambda: None) -> dict:
    kind, _, idx = job["id"].partition(":")
    work = OUT / plan["date"] / job["id"].replace(":", "_")
    built = build_long(plan, work) if kind == "long" else build_short(plan, int(idx), work)
    print(f"[done] {built['video']}  ({built['duration']:.1f} s)")
    if upload:
        publish(job, built, kind, save)
    return built


def auto():
    day = today()
    plan = load_plan(day) or make_plan(day)
    # Fewest attempts first: every job gets its first try before any failed job is retried.
    for job in sorted(plan["jobs"], key=lambda j: j["attempts"]):
        finished = job["status"] and all(v in ("done", "not set up") for v in job["status"].values())
        if finished or job["attempts"] >= MAX_ATTEMPTS:
            continue
        job["attempts"] += 1
        save_plan(plan)
        try:
            run_job(plan, job, save=lambda: save_plan(plan))
        finally:
            save_plan(plan)
        print(f"[auto] {job['id']}: {job['status']}")
        return
    print("[auto] all of today's jobs are finished")


# ---------- offline test ----------

def test():
    """Renders 1 short + 1 short long video from sample scripts. No keys needed, nothing is uploaded."""
    sample = json.loads((Path(__file__).parent / "sample_plan.json").read_text())
    CFG["voice"]["gemini_models"] = []   # the test uses the backup voice: Gemini's daily voice limit is small
    sample["date"] = "test"
    for job_id in ("short:0", "long"):
        built = run_job(sample, {"id": job_id, "attempts": 0, "status": {}, "links": {}}, upload=False)
        print(f"[test] OK {job_id}: {built['video']}")


def main(argv: list[str]):
    cmd = argv[0] if argv else "auto"
    if cmd == "auto":
        auto()
    elif cmd == "plan":
        day = today()
        if load_plan(day):
            print(f"[plan] today's plan already exists: {plan_path(day)}")
        else:
            make_plan(day)
    elif cmd == "render":
        day = today()
        plan = load_plan(day) or make_plan(day)
        run_job(plan, {"id": argv[1], "attempts": 0, "status": {}, "links": {}}, upload=False)
    elif cmd == "test":
        test()
    elif cmd == "rewrite":
        plan = load_plan(today())
        which = argv[1:] or [j["id"] for j in plan["jobs"]]
        write_scripts(plan, which)
        save_plan(plan)
    elif cmd == "batch":
        day = today()
        batch(load_plan(day) or make_plan(day))
    else:
        print(__doc__)
        sys.exit(1)
