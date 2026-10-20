"""The video factory on Modal (a rented cloud computer, paid per second from the free monthly credits).

  modal run modal_app.py::job --job-id long:history-0   make ONE job now, never posted (for review)
  modal run modal_app.py::plan                          plan today's videos (topics + scripts) only
  modal run modal_app.py::show                          download the dashboard to out/modal_dashboard.html
  FACTORY_DEPLOY=1 modal deploy modal_app.py            switch on the timer (checks every 20 minutes)

Stored on the Modal volume "video-factory": data/ (plans, topic memory), out/ (videos), cache/ (footage),
models/ (voice + timing models). Keys come from the Modal secret "video-factory-keys"
(made by scripts/modal_secrets.py, only with the owner's OK).

Switches (files on the volume):
  modal run modal_app.py::switch --name PAUSE --on         the timer does nothing   (--no-on: works again)
  modal run modal_app.py::switch --name POSTING_ON --on    finished videos are uploaded; without this file
                                                           they are only made and held for review
Do not run a manual `job` while the timer is deployed: both would edit the same plan.
"""
import os
import subprocess
import sys
from pathlib import Path

import modal

APP = Path("/app")
VOL = Path("/vol")
HERE = Path(__file__).resolve().parent
SKIP = {".venv", ".git", ".github", ".claude", "out", "cache", "models", "data", "docs", "node_modules"}


def _skip(p: Path) -> bool:
    """Files never sent to Modal: secrets, local caches and big folders the cloud makes itself."""
    parts = Path(p).parts
    name = parts[-1] if parts else ""
    return bool(set(parts) & SKIP) or "__pycache__" in parts or parts[:3] == ("remotion", "public", "runs") \
        or parts[:2] == ("remotion", "out") or name == ".env" or name.startswith("client_secret") \
        or (name.startswith("token") and name.endswith(".json")) or name == ".DS_Store" or name.endswith(".md")


image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "curl", "ca-certificates", "tzdata", "libnss3", "libdbus-1-3", "libatk1.0-0",
                 "libgbm-dev", "libxrandr2", "libxkbcommon-dev", "libxfixes3", "libxcomposite1", "libxdamage1",
                 "libatk-bridge2.0-0", "libpango-1.0-0", "libcairo2", "libcups2")
    .run_commands("apt-get install -y libasound2 || apt-get install -y libasound2t64",
                  "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -", "apt-get install -y nodejs")
    .pip_install("torch", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install_from_requirements(str(HERE / "requirements.txt"))
    .add_local_file(str(HERE / "remotion/package.json"), "/app/remotion/package.json", copy=True)
    .add_local_file(str(HERE / "remotion/package-lock.json"), "/app/remotion/package-lock.json", copy=True)
    .run_commands("cd /app/remotion && npm install --no-audit --no-fund && npx remotion browser ensure")
    .env({"FACTORY_QUIET": "1", "PYTHONUNBUFFERED": "1", "TZ": "UTC"})
    .add_local_dir(str(HERE), "/app", copy=True, ignore=_skip)
)

app = modal.App("video-factory", image=image)
volume = modal.Volume.from_name("video-factory", create_if_missing=True)
keys = modal.Secret.from_name("video-factory-keys")
# A program sees only the cores REQUESTED (cpu=(1, 8) showed Remotion 1 core), so the video machine asks for 8.
BIG = dict(volumes={str(VOL): volume}, secrets=[keys], cpu=8.0, memory=(4096, 32768), timeout=3 * 3600,
           max_containers=1, retries=0)
SMALL = {**BIG, "cpu": 1.0, "memory": (1024, 4096)}
WORK_MINUTES = 150                                    # one worker run makes jobs for at most this long


def _cores() -> int:
    """Our real CPU share, counted the way Remotion counts it (min of nproc and Node's availableParallelism).
    Python's own counts showed 24 cores on an 8-core machine."""
    counts = []
    for cmd in (["nproc"], ["node", "-e", "console.log(require('os').availableParallelism())"]):
        try:
            counts.append(int(subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return max(1, min(counts or [os.cpu_count() or 1]))


def _prepare():
    """Point the project's data/out/cache/models folders at the volume, so work survives between runs."""
    for d in ("data", "out", "cache", "models"):
        (VOL / d).mkdir(parents=True, exist_ok=True)
        link = APP / d
        if not link.is_symlink():
            link.symlink_to(VOL / d)
    os.environ["FACTORY_CPUS"] = str(_cores())
    os.chdir(APP)


def _pipeline(*args: str, env: dict | None = None) -> int:
    _prepare()
    try:
        return subprocess.run([sys.executable, "-u", "-m", "pipeline", *args], cwd=APP,
                              env={**os.environ, **(env or {})}).returncode
    finally:
        volume.commit()                               # save videos/plans even when the job failed


@app.function(**BIG)
def job(job_id: str):
    """Make one job of today's plan (e.g. long:history-0). Never uploads."""
    return _pipeline("factory-job", job_id)


@app.function(**SMALL)
def plan():
    """Plan today's videos: topics, research, chapter scripts, fact-check (AI calls, little CPU)."""
    return _pipeline("factory-plan")


@app.function(**BIG)
def work(posting: bool = False):
    """Make the next jobs of today's plan, one fresh process per job, until none is ready or time is up."""
    import time
    t0 = time.time()
    env = {"FACTORY_UPLOAD": "1" if posting else "0", "FACTORY_NO_PLAN": "1"}
    while time.time() - t0 < WORK_MINUTES * 60:
        volume.reload()
        if (VOL / "data" / "PAUSE").exists() or _pipeline("factory", env=env) == 3:   # 3 = nothing to do
            break


# The timer exists only in a real deploy (FACTORY_DEPLOY=1 modal deploy ...). Modal also fires schedules during
# `modal run` tests: a test once started planning in parallel with a test job (both edit the same plan file).
TIMER = modal.Cron("*/20 * * * *") if os.environ.get("FACTORY_DEPLOY") == "1" else None


@app.function(volumes={str(VOL): volume}, cpu=0.25, memory=1024, timeout=120, schedule=TIMER)
def tick():
    """The timer (tiny machine): start planning or the video machine when needed, else do nothing."""
    import json
    import time
    volume.reload()
    data = VOL / "data"
    if (data / "PAUSE").exists():
        return "paused"
    for f in (plan, work):
        st = f.get_current_stats()
        if st.num_total_runners or st.backlog:
            return "busy"
    _prepare()
    sys.path.insert(0, str(APP))
    from pipeline.config import CFG, today
    day = today()
    plan_file = data / "plans" / f"{day}.json"
    done = json.loads(plan_file.read_text()).get("planned_channels", []) if plan_file.exists() else []
    wanted = [k for k, v in CFG.get("channels", {}).items() if v.get("enabled", True)]
    tried = data / "plans" / f"{day}.tried"           # planning failed? try again at most every 3 hours
    if set(wanted) - set(done) and (not tried.exists() or time.time() - tried.stat().st_mtime > 3 * 3600):
        tried.touch()
        volume.commit()
        plan.spawn()
        return "planning"
    from pipeline import factory
    todo = json.loads(plan_file.read_text()) if plan_file.exists() else None
    if not todo or not any(factory._ready(j, todo) for j in todo.get("jobs", [])):
        return "nothing to do"                        # never start the 8-core machine just to find no work
    work.spawn(posting=(data / "POSTING_ON").exists())
    return "working"


@app.function(volumes={str(VOL): volume}, cpu=0.25, memory=512, timeout=60)
def switch(name: str, on: bool = True):
    """Turn a switch file on the volume on or off (only PAUSE and POSTING_ON exist)."""
    if name not in ("PAUSE", "POSTING_ON"):
        raise ValueError("switch is PAUSE or POSTING_ON")
    flag = VOL / "data" / name
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch() if on else flag.unlink(missing_ok=True)
    volume.commit()
    print(f"{name} is now {'ON' if on else 'OFF'}")


@app.function(volumes={str(VOL): volume}, cpu=0.25, memory=512, timeout=120)
def dashboard() -> str:
    volume.reload()
    _prepare()
    subprocess.run([sys.executable, "-m", "pipeline", "dashboard"], cwd=APP, check=False)
    page = APP / "out" / "dashboard.html"
    return page.read_text() if page.exists() else "<p>No dashboard yet.</p>"


@app.local_entrypoint()
def show():
    """Save the cloud dashboard on this Mac and open it."""
    out = HERE / "out" / "modal_dashboard.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(dashboard.remote())
    print(f"Dashboard saved: {out}")
    if sys.platform == "darwin":
        subprocess.run(["open", str(out)])
