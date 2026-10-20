"""out/dashboard.html: one page that shows what the factory is doing. Open it in any browser; it refreshes
itself every 15 seconds. It is a plain file (no server, no port), rewritten whenever something changes."""
import html
import json
import time
from datetime import datetime
from pathlib import Path

from .config import CFG, DATA, OUT, today

CHIP = {"done": ("#1f9d55", "done"), "failed": ("#d64545", "failed"), "rendering": ("#e6a700", "working"),
        "planned": ("#5b6475", "planned"), "waiting": ("#7b61ff", "waiting"), "not set up": ("#5b6475", "no upload")}


def _esc(x) -> str:
    return html.escape(str(x))


def _ago(t: float | None) -> str:
    if not t:
        return ""
    s = int(time.time() - t)
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s"


def _job_state(job: dict, running: str) -> str:
    if job["id"] == running:
        return "rendering"
    st = job.get("status") or {}
    if st and all(v in ("done", "not set up") for v in st.values()):
        return "done" if "done" in st.values() else "not set up"
    if job.get("built"):
        return "done"
    if "failed" in st.values() or job.get("attempts", 0) >= 3:
        return "failed"
    if job.get("waiting"):
        return "waiting"
    return "planned"


def write_dashboard():
    from .status import EVENTS, USAGE, mac_load, paused, read_status
    st = read_status()
    load, cores = mac_load()
    state = "paused" if paused() else st.get("state", "idle")
    running = st.get("job", "") if state == "working" else ""
    color = {"working": "#1f9d55", "paused": "#d64545", "waiting": "#7b61ff"}.get(state, "#5b6475")
    title = {"working": "WORKING NOW", "paused": "PAUSED", "waiting": "WAITING"}.get(state, "IDLE")

    # today's plan, grouped by channel
    plan_file = DATA / "plans" / f"{today()}.json"
    rows = ""
    try:
        plan = json.loads(plan_file.read_text())
        for job in plan.get("jobs", []):
            s = _job_state(job, running)
            c, label = CHIP.get(s, CHIP["planned"])
            links = " ".join(f'<a href="{_esc(u)}">{_esc(k)}</a>' for k, u in (job.get("links") or {}).items())
            rows += (f"<tr><td>{_esc(job['id'])}</td><td>{_esc(job.get('title', ''))[:70]}</td>"
                     f"<td><span class='chip' style='background:{c}'>{label}</span></td><td>{links}</td></tr>")
    except (OSError, ValueError):
        rows = "<tr><td colspan=4>No plan for today yet.</td></tr>"

    # free-limit usage today
    usage = ""
    try:
        data = json.loads((USAGE / f"{datetime.now().strftime('%Y-%m-%d')}.json").read_text())
        usage = "".join(f"<tr><td>{_esc(k)}</td><td>{v}</td></tr>" for k, v in sorted(data.items()))
    except (OSError, ValueError):
        usage = "<tr><td colspan=2>Nothing used yet today.</td></tr>"

    # last events and problems
    events = []
    try:
        events = [json.loads(x) for x in EVENTS.read_text().splitlines()[-200:]]
    except (OSError, ValueError):
        pass
    recent = "".join(
        f"<tr><td>{datetime.fromtimestamp(e['t']).strftime('%H:%M')}</td><td>{_esc(e['kind'])}</td>"
        f"<td>{_esc(e['msg'])[:160]}"
        + (f' · <a href="file://{_esc(e["file"])}">open video</a>' if e.get("file") else "") + "</td></tr>"
        for e in reversed(events[-25:]))
    problems = [e for e in events if e["kind"] in ("failed", "error")][-5:]
    prob = "".join(f"<li>{datetime.fromtimestamp(e['t']).strftime('%b %d %H:%M')} — {_esc(e['msg'])[:220]}</li>"
                   for e in reversed(problems)) or "<li>None.</li>"

    busy = load / cores
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="15">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Video factory</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--ink:#e6edf3;--muted:#8b949e;--line:#30363d}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:20px 16px}}
.top{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:16px}}
.state{{background:{color};color:#fff;font-weight:800;padding:8px 14px;border-radius:999px;letter-spacing:.5px}}
.pulse{{animation:p 1.4s infinite}}@keyframes p{{50%{{opacity:.55}}}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin:0 0 8px}}
table{{width:100%;border-collapse:collapse}}td{{padding:6px 4px;border-top:1px solid var(--line);vertical-align:top}}
.chip{{color:#fff;font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px}}
.bar{{height:10px;background:#21262d;border-radius:6px;overflow:hidden}}
.bar i{{display:block;height:100%;width:{min(100, busy * 100):.0f}%;background:{'#d64545' if busy > 1 else '#1f9d55'}}}
a{{color:#58a6ff}} code{{background:#21262d;padding:1px 5px;border-radius:4px}} .muted{{color:var(--muted)}}
</style></head><body><main>
<div class="top"><span class="state {'pulse' if state == 'working' else ''}">{title}</span>
<span class="muted">Updated {datetime.now().strftime('%H:%M:%S')} · refreshes every 15 s</span></div>
<div class="grid">
 <div class="card"><h2>Right now</h2>
  {'<b>' + _esc(st.get('job', '')) + '</b><br>Step: ' + _esc(st.get('step', '')) + ' ' + _esc(st.get('detail', ''))
   + '<br><span class=muted>running for ' + _ago(st.get('started')) + '</span>' if state == 'working'
   else '<span class=muted>Nothing running.</span>'}
 </div>
 <div class="card"><h2>Mac load</h2><div class="bar"><i></i></div>
  <p>{load:.1f} of {cores} cores busy{' — factory is using your Mac' if state == 'working' else ''}.<br>
  <span class="muted">The factory waits when the load is above {cores}.</span></p></div>
 <div class="card"><h2>Pause switch</h2>
  <p>Pause everything: <code>touch {_esc(DATA / 'PAUSE')}</code><br>Resume: delete that file.</p></div>
</div>
<div class="card"><h2>Today's videos ({_esc(today())})</h2><table>{rows}</table></div>
<div class="grid">
 <div class="card"><h2>Free limits used today</h2><table>{usage}</table></div>
 <div class="card"><h2>Problems</h2><ul>{prob}</ul></div>
</div>
<div class="card"><h2>Recent activity</h2><table>{recent}</table></div>
</main></body></html>"""
    (OUT / "dashboard.html").write_text(page)
