"""Copies the factory's keys from .env into the Modal secret "video-factory-keys" (run only with the owner's OK).

  .venv/bin/python scripts/modal_secrets.py                 AI + footage keys only (videos can't be posted)
  .venv/bin/python scripts/modal_secrets.py --with-youtube  also the YouTube login (needed before posting)

The keys go straight from .env to Modal through a private temp file that is deleted at once; only the key
NAMES are printed.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ["GEMINI_API_KEY", "GROQ_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY"]


def read_env() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    env = read_env()
    names = BASE + ([k for k in env if k.startswith("YT_")] if "--with-youtube" in sys.argv else [])
    chosen = {k: env[k] for k in names if env.get(k)}
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "keys.json"
        f.touch(mode=0o600)
        f.write_text(json.dumps(chosen))
        subprocess.run([str(ROOT / ".venv/bin/modal"), "secret", "create", "video-factory-keys",
                        "--from-json", str(f), "--force"], check=True, stdout=subprocess.DEVNULL)
    print("Modal secret video-factory-keys now holds:", ", ".join(chosen) or "nothing")


if __name__ == "__main__":
    main()
