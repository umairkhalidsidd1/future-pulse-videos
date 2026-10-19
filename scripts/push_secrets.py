"""Copies every filled-in key from .env into this repo's GitHub Secrets.

  .venv/bin/python scripts/push_secrets.py

Prints only the key NAMES, never the values.
"""
import subprocess
import sys
from pathlib import Path

env = Path(__file__).resolve().parent.parent / ".env"
if not env.exists():
    sys.exit("No .env file yet. Copy .env.example to .env and fill it in.")

SKIP = {"TIKTOK_REDIRECT_URI"}  # only used on your Mac
done = 0
for line in env.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = (x.strip() for x in line.split("=", 1))
    value = value.strip('"').strip("'")
    if not value or name in SKIP:
        continue
    p = subprocess.run(["gh", "secret", "set", name], input=value, text=True, capture_output=True)
    print(f"  {'saved ' if p.returncode == 0 else 'FAILED'} {name}" + ("" if p.returncode == 0 else f": {p.stderr.strip()[:150]}"))
    done += p.returncode == 0
print(f"{done} secrets saved to GitHub.")
