"""Lets the owner see what the factory is doing: Mac notifications, a live status file, an event log,
daily usage counters (free AI limits) and a self-refreshing dashboard page (out/dashboard.html)."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

from .config import CFG, DATA, OUT

STATUS = OUT / "status.json"
EVENTS = OUT / "events.jsonl"
USAGE = OUT / "usage"
PAUSE = DATA / "PAUSE"          # if this file exists, nothing new starts (the kill switch)


def notify(title: str, message: str):
    """A normal macOS notification (top-right corner). Does nothing on other systems."""
    if sys.platform != "darwin" or os.environ.get("FACTORY_QUIET"):
        return
    safe = lambda s: s.replace("\\", "").replace('"', "'")[:180]
    subprocess.run(["osascript", "-e", f'display notification "{safe(message)}" with title "{safe(title)}"'],
                   capture_output=True)


def event(kind: str, message: str, **extra):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(EVENTS, "a") as f:
        f.write(json.dumps({"t": time.time(), "kind": kind, "msg": message, **extra}) + "\n")


def set_status(state: str, *, job: str = "", step: str = "", detail: str = ""):
    """state: working | idle | paused | waiting. Rewrites the dashboard every time."""
    old = read_status()
    started = old.get("started") if old.get("job") == job and old.get("state") == "working" else time.time()
    data = {"state": state, "job": job, "step": step, "detail": detail, "updated": time.time(),
            "started": started if state == "working" else None, "pid": os.getpid()}
    OUT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(data))
    try:
        from .dashboard import write_dashboard
        write_dashboard()
    except Exception as e:  # the dashboard must never break a render
        print(f"  [dashboard] not updated: {e.__class__.__name__}: {e}")


def step(job: str, name: str, detail: str = ""):
    print(f"  [step] {name} {detail}".rstrip())
    set_status("working", job=job, step=name, detail=detail)


def read_status() -> dict:
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def count(kind: str, n: int = 1):
    """Daily counters, e.g. count('tts:gemini-3.8-flash-tts'), shown on the dashboard."""
    USAGE.mkdir(parents=True, exist_ok=True)
    path = USAGE / f"{datetime.now().strftime('%Y-%m-%d')}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    data[kind] = data.get(kind, 0) + n
    path.write_text(json.dumps(data))


def paused() -> bool:
    return PAUSE.exists()


def mac_load() -> tuple[float, int]:
    return os.getloadavg()[0], os.cpu_count() or 1
