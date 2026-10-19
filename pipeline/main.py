"""The daily machine.

  python -m pipeline auto            do the next unfinished job of today (what GitHub runs)
  python -m pipeline plan            only pick today's stories and write the scripts
  python -m pipeline render short:0  render one job without uploading (also: long)
  python -m pipeline test            offline test: sample scripts, no keys, no uploads
"""
import json
import random
import sys
from datetime import date
from pathlib import Path

from . import captions, render, thumbnail, trends, tts, writer
from .config import CFG, DATA, OUT, safe_err, today
from .stock import Stock
from .upload import instagram, tiktok, youtube

MAX_ATTEMPTS = 3
CREDIT = "Stock footage: Pexels & Pixabay. Voice: AI narration."


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

    formats = CFG["short"]["formats"]
    offset = date.fromisoformat(day).toordinal()
    for i, s in enumerate(stories):
        fmt = formats[(offset + i) % len(formats)]
        print(f"[plan] writing short {i}: {s['title'][:70]}  ({fmt})")
        s["short"] = writer.write_short(s, fmt)
        s["short"]["scenes"] = writer.fact_check(s["short"]["scenes"], s["facts"])

    print("[plan] writing the long video")
    long = writer.write_long(stories)
    for seg in long.get("segments", []):
        try:
            idx = int(seg.get("story", 1)) - 1
        except (TypeError, ValueError):
            idx = -1
        if 0 <= idx < len(stories):
            seg["scenes"] = writer.fact_check(seg["scenes"], stories[idx]["facts"])

    for s in stories:  # the repo is public: keep the downloaded article text out of it
        s.pop("facts", None)
    plan = {"date": day, "stories": stories, "long": long,
            "jobs": [{"id": j, "attempts": 0, "status": {}, "links": {}} for j in CFG["channel"]["job_order"]
                     if j == "long" or int(j.split(":")[1]) < len(stories)]}
    save_plan(plan)
    trends.add_history([s["title"] for s in stories])
    return plan


# ---------- build one video ----------

def theme_for(day: str) -> dict:
    themes = CFG["captions"]["themes"]
    try:
        n = date.fromisoformat(day).toordinal()
    except ValueError:
        n = 0
    return themes[n % len(themes)]


def build_short(plan: dict, index: int, work: Path) -> dict:
    story = plan["stories"][index]
    sc = story["short"]
    scenes = sc["scenes"]
    seed = f"{plan['date']}-short-{index}"
    work.mkdir(parents=True, exist_ok=True)
    print(f"[short {index}] voice")
    wav = work / "voice.wav"
    timings, total = tts.synth(scenes, wav)
    print(f"[short {index}] {total:.1f} s, captions")
    words = captions.word_timings(wav, scenes, timings)
    ass = work / "captions.ass"
    s = CFG["short"]
    captions.build_ass(words, ass, width=s["width"], height=s["height"], vertical=True, theme=theme_for(plan["date"]),
                       total=total + 0.5, overlays=[{"text": sc.get("hook_text", ""), "start": 0, "end": 2.6,
                                                     "style": "Hook"}])
    print(f"[short {index}] video")
    out = work / f"short_{index}.mp4"
    stock = Stock(vertical=True, seed=seed)
    render.render(kind="short", scenes=scenes, timings=timings, total=total, voice_wav=wav, ass_path=ass,
                  stock=stock, work=work, out_path=out, seed=seed)
    stock.save_used()
    sources = "\n".join(f"- {x['source']}: {x['url']}" for x in story["sources"][:4] if x.get("url"))
    return {"video": out, "duration": total,
            "youtube": {"title": sc["youtube_title"],
                        "description": f"{sc['youtube_description']}\n\n{sources}\n\n{CREDIT}",
                        "tags": sc.get("tags", []), "comment": sc.get("question")},
            "instagram": sc.get("instagram_caption", sc["youtube_title"]),
            "tiktok": sc.get("tiktok_caption", sc["youtube_title"])}


def build_long(plan: dict, work: Path) -> dict:
    lg = plan["long"]
    scenes, overlays_at, chapters, whoosh = [], [], [], set()
    chapters.append(("Intro", 0))
    scenes += lg["intro"]
    total_segments = len(lg["segments"])
    for n, seg in enumerate(lg["segments"]):
        number = total_segments - n
        chapters.append((f"#{number} {seg['chapter']}", len(scenes)))
        overlays_at.append((len(scenes), f"#{number}  {seg['chapter'].upper()}"))
        whoosh.add(len(scenes))
        scenes += seg["scenes"]
    chapters.append(("What do you think?", len(scenes)))
    whoosh.add(len(scenes))
    scenes += lg["outro"]

    seed = f"{plan['date']}-long"
    work.mkdir(parents=True, exist_ok=True)
    print(f"[long] voice for {len(scenes)} scenes")
    wav = work / "voice.wav"
    timings, total = tts.synth(scenes, wav)
    print(f"[long] {total / 60:.1f} min, captions")
    words = captions.word_timings(wav, scenes, timings)
    overlays = [{"text": lg["thumbnail_text"], "start": 0, "end": 2.8, "style": "Hook"}]
    overlays += [{"text": text, "start": timings[i][0], "end": timings[i][0] + 3.5, "style": "Tag"}
                 for i, text in overlays_at]
    ass = work / "captions.ass"
    s = CFG["long"]
    captions.build_ass(words, ass, width=s["width"], height=s["height"], vertical=False, theme=theme_for(plan["date"]),
                       total=total + 0.5, overlays=overlays)
    print("[long] video")
    out = work / "long.mp4"
    stock = Stock(vertical=False, seed=seed)
    segs = render.render(kind="long", scenes=scenes, timings=timings, total=total, voice_wav=wav, ass_path=ass,
                         stock=stock, work=work, out_path=out, seed=seed, whoosh_scenes=whoosh)
    stock.save_used()
    first_story_seg = segs[min(len(segs) - 1, max(0, round(len(segs) * 0.8)))]
    thumb = thumbnail.make(first_story_seg, lg["thumbnail_text"], work / "thumbnail.jpg")
    chapter_text = render.chapter_times(timings, chapters)
    sources = "\n".join(f"- {x['source']}: {x['url']}" for st in plan["stories"] for x in st["sources"][:2]
                        if x.get("url"))
    desc = lg["description"].replace("{CHAPTERS}", "Chapters:\n" + chapter_text)
    if "Chapters:" not in desc:
        desc += "\n\nChapters:\n" + chapter_text
    return {"video": out, "thumbnail": thumb, "duration": total,
            "youtube": {"title": lg["title"], "description": f"{desc}\n\n{sources}\n\n{CREDIT}",
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
    else:
        print(__doc__)
        sys.exit(1)
