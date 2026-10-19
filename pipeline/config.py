"""Loads config.yaml and secrets (environment variables or a local .env file)."""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
OUT = ROOT / "out"
MODELS = ROOT / "models"
ASSETS = ROOT / "assets"


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

with open(ROOT / "config.yaml") as f:
    CFG = yaml.safe_load(f)

for d in (DATA / "plans", CACHE, OUT, MODELS):
    d.mkdir(parents=True, exist_ok=True)


def secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def safe_err(e: BaseException) -> str:
    """Error text with any key/token in a URL blanked out, safe for public logs."""
    import re
    text = f"{type(e).__name__}: {e}"
    return re.sub(r"((?:key|access_token|token|client_secret)=)[^&\s'\"]+", r"\1***", text)[:400]


def today() -> str:
    """The channel's date (in its own timezone), e.g. 2026-10-19."""
    return datetime.now(ZoneInfo(CFG["channel"]["timezone"])).strftime("%Y-%m-%d")
