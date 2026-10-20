"""The multi-channel daily factory.

Every day, for each channel in config.yaml: pick fresh topics, research them, write long videos made of
stand-alone chapters, fact-check them, render the long videos, and cut the best chapters into vertical
Shorts (they reuse the long video's voice and word timings). Uploads are scheduled with publishAt, so the
Mac can render whenever it is free and YouTube publishes at the planned US peak times.
"""
import json
import random
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import soundfile as sf

from . import align, main as base, render, status, thumbnail, topics, tts, writer
from .config import CFG, OUT, safe_err, today
from .upload import youtube

MAX_ATTEMPTS = 3


def channels() -> dict:
    return {k: v for k, v in CFG.get("channels", {}).items() if v.get("enabled", True)}


# ---------- planning ----------

def _post_at(day: str, hour: int) -> str:
    tz = ZoneInfo(CFG["channel"]["timezone"])
    local = datetime.fromisoformat(day).replace(hour=hour % 24, tzinfo=tz)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_plan(day: str) -> dict:
    plan = base.load_plan(day) or {"date": day, "factory": True, "videos": [], "jobs": []}
    for name, ch in channels().items():
        if name in plan.setdefault("planned_channels", []):
            continue
        status.step(f"plan:{name}", "choosing topics", ch.get("name", name))
        n = ch["long_per_day"]
        made = 0
        for t in topics.pick(name, ch, n):
            if made == n:
                break
            status.step(f"plan:{name}", "researching", t["title"][:60])
            facts = topics.research(t)
            if not facts:
                print(f"  [plan] skipped (too little to research): {t['title']}")
                continue
            status.step(f"plan:{name}", "writing script", t["title"][:60])
            try:
                doc = writer.check_doc(writer.write_doc(t, ch, facts), facts)
            except Exception as e:
                print(f"  [plan] could not write '{t['title']}': {safe_err(e)}")
                continue
            plan["videos"].append({"id": f"{name}-{made}", "channel": name, "topic": t, "doc": doc})
            topics.remember(name, t)
            made += 1
            base.save_plan(plan)                      # keep every finished script, even if a later one fails
        plan["planned_channels"].append(name)
        base.save_plan(plan)
        status.event("info", f"{ch.get('name', name)}: {made} long video scripts written")
    plan["jobs"] = _jobs(plan)
    base.save_plan(plan)
    return plan


def _jobs(plan: dict) -> list[dict]:
    old = {j["id"]: j for j in plan.get("jobs", [])}
    longs, shorts = [], []
    for name, ch in channels().items():
        vids = [v for v in plan["videos"] if v["channel"] == name]
        hours = sorted(ch.get("post_hours", [12, 18]))
        slot = 0
        for v in vids:
            longs.append({"id": f"long:{v['id']}", "channel": name, "title": v["doc"]["title"],
                          "post_at": _post_at(plan["date"], hours[slot % len(hours)])})
            slot += 1
        best = sorted(((c["clip_score"], v["id"], ci) for v in vids for ci, c in enumerate(v["doc"]["chapters"])),
                      reverse=True)
        per_video: dict[str, int] = {}
        for score, vid, ci in best:
            if sum(per_video.values()) >= ch.get("shorts_per_day", 0):
                break
            if per_video.get(vid, 0) >= 2:                # at most 2 Shorts from one long video
                continue
            per_video[vid] = per_video.get(vid, 0) + 1
            chap = next(v for v in vids if v["id"] == vid)["doc"]["chapters"][ci]
            shorts.append({"id": f"short:{vid}:{ci}", "channel": name, "title": chap["title"],
                           "post_at": _post_at(plan["date"], hours[slot % len(hours)])})
            slot += 1
    jobs = []
    for j in longs + shorts:                              # a Short always comes after its long video
        jobs.append({**{"attempts": 0, "status": {}, "links": {}}, **old.get(j["id"], {}), **j})
    return jobs


# ---------- building ----------

def _work(plan: dict, vid: str) -> Path:
    return OUT / plan["date"] / vid


def _video(plan: dict, vid: str) -> dict:
    return next(v for v in plan["videos"] if v["id"] == vid)


def build_long(plan: dict, video: dict, job_id: str) -> dict:
    ch = CFG["channels"][video["channel"]]
    doc, topic = video["doc"], video["topic"]
    work = _work(plan, video["id"]) / "long"
    work.mkdir(parents=True, exist_ok=True)
    scenes, chapter_marks, chapter_spans, whoosh = [], [("Intro", 0)], [], set()
    scenes += [{**x, "card": None if (x.get("card") or {}).get("template") == "headline" else x.get("card")}
               for x in doc["intro"]]
    for ci, c in enumerate(doc["chapters"]):
        start = len(scenes)
        whoosh.add(start)
        chapter_marks.append((c["title"], start))
        cs = [dict(x) for x in c["scenes"]]
        cs[0]["card"] = None                               # the chapter title card shows here
        for x in cs:
            if (x.get("card") or {}).get("template") == "headline":
                x["card"] = base.headline_card(topic, plan["date"], cs) if topic.get("url") else None
        scenes += cs
        chapter_spans.append((start, len(scenes)))
        if c.get("bridge"):                                # spoken in the long video only
            scenes.append({"text": c["bridge"], "visual": cs[-1].get("visual", ""), "visual_alt": cs[-1].get(
                "visual_alt", ""), "wiki": cs[-1].get("wiki", ""), "keywords": [], "card": None})
    chapter_marks.append(("Final thoughts", len(scenes)))
    whoosh.add(len(scenes))
    outro = [{**x, "card": None} for x in writer.finish_ending(doc["outro"])]
    if doc.get("pinned_comment"):
        outro[-1]["card"] = {"template": "outro", "question": doc["pinned_comment"], "cta": "Subscribe for more"}
    scenes += outro

    status.step(job_id, "voice", f"{sum(len(s['text'].split()) for s in scenes)} words")
    wav = work / "voice.wav"
    spans, total = tts.synth(scenes, wav, "long", voice=ch["voice"])
    status.step(job_id, "exact caption timing", f"{total / 60:.1f} min")
    words, timings = align.align_script(wav, scenes, spans)
    fps = CFG["long"]["fps"]
    cards = [{"from": round(timings[s][0] * fps), "duration": round(3.5 * fps), "template": "chapter",
              "data": {"number": str(ci + 1), "title": doc["chapters"][ci]["title"]}}
             for ci, (s, _) in enumerate(chapter_spans)]
    (work / "meta.json").write_text(json.dumps({"scenes": scenes, "timings": timings, "words": words,
                                                "chapter_spans": chapter_spans, "total": total}))
    status.step(job_id, "footage + drawing the video", "this is the longest step")
    out = work / "long.mp4"
    clips, credits = base.draw(kind="long", scenes=scenes, timings=timings, total=total, words=words, wav=wav,
                               work=work, out=out, seed=video["id"] + plan["date"], day=plan["date"],
                               hook=doc["thumbnail_text"], extra_cards=cards, whoosh=whoosh,
                               mood=doc.get("music_mood"), look=ch.get("look"))
    status.step(job_id, "thumbnail")
    source = clips[0] if clips else out
    thumb = thumbnail.make(source, doc["thumbnail_text"], work / "thumbnail.jpg", badge="",
                           at=0.0 if source.suffix.lower() in render.IMAGE_EXT else 1.0)
    chapters_txt = render.chapter_times(timings, chapter_marks)
    desc = doc["description"].replace("{CHAPTERS}", "Chapters:\n" + chapters_txt)
    if "Chapters:" not in desc:
        desc += "\n\nChapters:\n" + chapters_txt
    sources = "\n".join(f"- {s['source']}: {s['url']}" for s in topic.get("sources", [])[:5])
    return {"video": out, "thumbnail": thumb, "duration": total,
            "youtube": {"title": doc["title"], "tags": doc.get("tags", []), "comment": doc.get("pinned_comment"),
                        "description": f"{desc}\n\nSources:\n{sources}\n\n{base.CREDIT}" +
                                       "".join(f"\n{c}" for c in credits)}}


def build_short(plan: dict, video: dict, ci: int, job_id: str) -> dict:
    """A vertical Short from one chapter of the long video: same voice and exact word times, new tall layout."""
    ch = CFG["channels"][video["channel"]]
    doc = video["doc"]
    chap = doc["chapters"][ci]
    meta_file = _work(plan, video["id"]) / "long" / "meta.json"
    if not meta_file.exists():
        raise RuntimeError("the long video for this Short has not been made yet")
    meta = json.loads(meta_file.read_text())
    s, e = meta["chapter_spans"][ci]
    t0 = max(0.0, meta["timings"][s][0] - 0.12)
    t1 = meta["timings"][e - 1][1] + 0.35
    work = _work(plan, video["id"]) / f"short_{ci}"
    work.mkdir(parents=True, exist_ok=True)

    status.step(job_id, "cutting the chapter's voice", f"{t1 - t0:.0f} s")
    audio, rate = sf.read(str(_work(plan, video["id"]) / "long" / "voice.wav"), dtype="float32")
    piece = audio[int(t0 * rate):int(t1 * rate)].copy()
    fade = int(0.01 * rate)
    piece[:fade] *= np.linspace(0, 1, fade)
    piece[-fade:] *= np.linspace(1, 0, fade)
    wav = work / "voice.wav"
    sf.write(wav, piece, rate)
    total = len(piece) / rate
    scenes = [dict(x) for x in meta["scenes"][s:e]]
    if not scenes[-1].get("card"):
        q = chap["title"] if chap["title"].endswith("?") else doc.get("pinned_comment", "")
        if q:
            scenes[-1]["card"] = {"template": "outro", "question": q, "cta": "Full video on the channel"}
    timings = [(a - t0, b - t0) for a, b in meta["timings"][s:e]]
    words = [{**w, "s": w["s"] - t0, "e": w["e"] - t0, "scene": w["scene"] - s}
             for w in meta["words"] if s <= w["scene"] < e]

    status.step(job_id, "footage + drawing the Short")
    out = work / f"short_{ci}.mp4"
    _, credits = base.draw(kind="short", scenes=scenes, timings=timings, total=total, words=words, wav=wav,
                           work=work, out=out, seed=f"{video['id']}-{ci}{plan['date']}", day=plan["date"],
                           hook=chap["hook_text"], mood=doc.get("music_mood"), look=ch.get("look"))
    tags = [t for t in doc.get("tags", [])][:8]
    title = chap.get("short_title") or chap["title"]
    desc = (f"{chap['title']}\nFull video: \"{doc['title']}\" on our channel.\n\n#Shorts "
            + " ".join("#" + "".join(w.title() for w in t.split())[:28] for t in tags[:3]) + "\n\n"
            + "\n".join(f"- {s['source']}: {s['url']}" for s in video["topic"].get("sources", [])[:3])
            + f"\n\n{base.CREDIT}" + "".join(f"\n{c}" for c in credits))
    return {"video": out, "duration": total,
            "youtube": {"title": title[:60], "tags": tags, "comment": None, "description": desc}}


# ---------- running jobs ----------

def run(plan: dict, job: dict, upload: bool = True) -> dict:
    kind, _, rest = job["id"].partition(":")
    ch = CFG["channels"][job["channel"]]
    label = f"{ch.get('name', job['channel'])} · {'long video' if kind == 'long' else 'Short'}"
    status.notify("Video factory: started", f"{label}: {job.get('title', '')}")
    status.event("start", f"{label}: {job.get('title', '')}")
    if kind == "long":
        built = build_long(plan, _video(plan, rest), job["id"])
    else:
        vid, _, ci = rest.rpartition(":")
        built = build_short(plan, _video(plan, vid), int(ci), job["id"])
    job["built"] = str(built["video"])
    if upload:
        status.step(job["id"], "uploading to YouTube")
        publish(job, built)
    status.event("done", f"{label} finished ({built['duration'] / 60:.1f} min)", file=str(built["video"]))
    status.notify("Video factory: finished", f"{label} ready ({built['duration'] / 60:.1f} min)")
    return built


def publish(job: dict, built: dict):
    name = job["channel"]
    if not youtube.ready(name):
        job["status"]["youtube"] = "not set up"
        return
    when = job.get("post_at")
    future = when and datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) > \
        datetime.now(timezone.utc)
    y = built["youtube"]
    try:
        vid = youtube.upload(built["video"], title=y["title"], description=y["description"], tags=y["tags"],
                             thumbnail=built.get("thumbnail"), comment=y.get("comment"), channel=name,
                             publish_at=when if future else None, category=CFG["channels"][name].get("category_id"))
        job["links"]["youtube"] = f"https://youtu.be/{vid}"
        job["status"]["youtube"] = "done"
    except Exception as e:
        job["status"]["youtube"] = "failed"
        status.event("failed", f"upload failed for {job['id']}: {safe_err(e)}")


def _ready(job: dict, plan: dict) -> bool:
    st = job["status"]
    finished = bool(st) and all(v in ("done", "not set up") for v in st.values())
    if finished or job["attempts"] >= MAX_ATTEMPTS or job.get("waiting") == plan["date"]:
        return False
    if job["id"].startswith("short:"):
        vid = job["id"].split(":")[1]
        return (_work(plan, vid) / "long" / "meta.json").exists()
    return True


def cleanup(keep_days: int | None = None):
    """Free disk space: delete the factory's OWN rendered video folders (out/<date>) once they are older than
    keep_days AND every video of that day was uploaded successfully (failed uploads are kept for a retry).
    Also trims the stock-footage cache (files unused for 7 days). YouTube keeps the videos."""
    import shutil
    keep_days = CFG.get("cleanup", {}).get("keep_days", 2) if keep_days is None else keep_days
    freed, now = 0, time.time()
    for folder in OUT.glob("20??-??-??"):
        if not folder.is_dir() or now - folder.stat().st_mtime < keep_days * 86400:
            continue
        plan = base.load_plan(folder.name)
        jobs = (plan or {}).get("jobs", [])
        uploaded = bool(jobs) and all((j.get("status") or {}).get("youtube") == "done" for j in jobs)
        if not uploaded:
            continue                                      # something wasn't uploaded: keep it for a retry
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        freed += size
    from .stock import CLIPS
    for f in CLIPS.glob("*"):
        if f.is_file() and now - f.stat().st_atime > 7 * 86400:
            freed += f.stat().st_size
            f.unlink(missing_ok=True)
    if freed > 50_000_000:
        status.event("info", f"cleanup freed {freed / 1e9:.1f} GB of finished, uploaded videos")


def next_job(upload: bool = True) -> bool:
    """Do ONE job of today's plan. Returns True if a job ran. Waits (does nothing) when the Mac is busy or
    the factory is paused."""
    if status.paused():
        status.set_status("paused")
        return False
    try:
        cleanup()
    except Exception as e:                                # cleanup must never stop the factory
        print(f"  [cleanup] skipped: {safe_err(e)}")
    load, cores = status.mac_load()
    if load > cores:
        status.set_status("waiting", detail=f"Mac is busy (load {load:.1f} of {cores}); trying again later")
        return False
    day = today()
    plan = base.load_plan(day)
    if not plan or not plan.get("factory") or set(channels()) - set(plan.get("planned_channels", [])):
        status.step("plan", "planning today's videos")
        plan = make_plan(day)
    for job in plan["jobs"]:
        if not _ready(job, plan):
            continue
        job["attempts"] += 1
        base.save_plan(plan)
        try:
            run(plan, job, upload=upload)
        except tts.VoiceWait as e:
            job["attempts"] -= 1
            job["waiting"] = day
            status.event("waiting", f"{job['id']}: {e}")
            base.save_plan(plan)
            continue                                      # try another channel's job instead
        except Exception as e:
            status.event("failed", f"{job['id']} (try {job['attempts']}): {safe_err(e)}")
            status.notify("Video factory: problem", f"{job['id']} failed: {safe_err(e)[:120]}")
            traceback.print_exc()
        finally:
            base.save_plan(plan)
            status.set_status("idle")
        return True
    status.set_status("idle", detail="all of today's jobs are finished or waiting")
    return False


def batch(upload: bool = False):
    """Make every video of today now (for review). Nothing is uploaded unless upload=True."""
    while next_job(upload=upload):
        pass
