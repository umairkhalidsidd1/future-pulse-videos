"""The Mac's own timer for the video factory (launchd). It does nothing until you install it.

  .venv/bin/python scripts/mac_timer.py install     every 15 minutes: do the next video job (if not busy/paused)
  .venv/bin/python scripts/mac_timer.py uninstall   stop the timer completely
  .venv/bin/python scripts/mac_timer.py status      is it installed? is a job running?
  .venv/bin/python scripts/mac_timer.py run-once    what the timer runs (one job, with lock + keep-awake)

Pause without uninstalling:  touch data/PAUSE      Resume:  rm data/PAUSE
"""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABEL = "com.videofactory.runner"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOCK = ROOT / "out" / "runner.lock"
LOG = ROOT / "out" / "runner.log"
PY = ROOT / ".venv" / "bin" / "python"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_once():
    """One job, never two at once, Mac kept awake only while it works."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            if _alive(int(LOCK.read_text().strip() or 0)):
                return                                    # a job is already running
        except ValueError:
            pass
    LOCK.write_text(str(os.getpid()))
    try:
        with open(LOG, "a") as log:
            subprocess.run(["caffeinate", "-i", str(PY), "-u", "-m", "pipeline", "factory"], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT)
    finally:
        LOCK.unlink(missing_ok=True)


def install():
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    plist = {"Label": LABEL, "ProgramArguments": [str(PY), str(Path(__file__).resolve()), "run-once"],
             "WorkingDirectory": str(ROOT), "StartInterval": 900, "RunAtLoad": True,
             "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG), "ProcessType": "Background",
             "LowPriorityIO": True, "Nice": 10}             # be gentle with the owner's other work
    PLIST.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
    subprocess.run(["launchctl", "load", str(PLIST)], check=True)
    print(f"Installed. The factory checks for work every 15 minutes. Log: {LOG}")


def uninstall():
    if PLIST.exists():
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()
    print("Removed. The factory will not start by itself any more.")


def status():
    print("timer installed:", PLIST.exists())
    pid = LOCK.read_text().strip() if LOCK.exists() else ""
    print("job running:", bool(pid) and _alive(int(pid)), f"(pid {pid})" if pid else "")
    print("paused:", (ROOT / "data" / "PAUSE").exists())


if __name__ == "__main__":
    {"install": install, "uninstall": uninstall, "status": status, "run-once": run_once}.get(
        sys.argv[1] if len(sys.argv) > 1 else "status", status)()
