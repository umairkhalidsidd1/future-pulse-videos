"""Checks every key and account, one line each. Safe: it posts nothing.

  .venv/bin/python scripts/check_setup.py
"""
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import CFG, safe_err, secret  # noqa: E402


def check(name, fn):
    try:
        print(f"  OK    {name}: {fn()}")
    except Exception as e:
        print(f"  FAIL  {name}: {safe_err(e)}")


def gemini():
    from pipeline.llm import ask_json
    return ask_json("Return JSON.", 'Return {"ok": true}', temperature=0)


def pexels():
    if not secret("PEXELS_API_KEY"):
        raise RuntimeError("PEXELS_API_KEY missing")
    r = requests.get("https://api.pexels.com/videos/search", params={"query": "robot", "per_page": 1},
                     headers={"Authorization": secret("PEXELS_API_KEY")}, timeout=20)
    r.raise_for_status()
    return f"{r.json().get('total_results')} robot clips"


def pixabay():
    if not secret("PIXABAY_API_KEY"):
        return "not set (optional)"
    r = requests.get("https://pixabay.com/api/videos/", params={"key": secret("PIXABAY_API_KEY"), "q": "robot"},
                     timeout=20)
    r.raise_for_status()
    return f"{r.json().get('totalHits')} robot clips"


def youtube():
    from pipeline.upload import youtube as yt
    if not yt.ready():
        return "not set up yet"
    items = yt._client().channels().list(part="snippet", mine=True).execute().get("items", [])
    return f"channel '{items[0]['snippet']['title']}'" if items else "no channel on this account"


def instagram():
    from pipeline.upload import instagram as ig
    if not ig.ready():
        return "not set up yet"
    v = CFG["upload"]["instagram"]["graph_version"]
    auth = {"Authorization": f"Bearer {secret('IG_ACCESS_TOKEN')}"}
    r = requests.get(f"https://graph.facebook.com/{v}/{secret('IG_USER_ID')}", params={"fields": "username"},
                     headers=auth, timeout=20)
    r.raise_for_status()
    lim = requests.get(f"https://graph.facebook.com/{v}/{secret('IG_USER_ID')}/content_publishing_limit",
                       headers=auth, timeout=20).json()
    return f"@{r.json().get('username')}, publishing limit info: {lim.get('data', lim)}"


def tiktok():
    from pipeline.upload import tiktok as tt
    if not tt.ready():
        return "not set up yet"
    token = tt._access_token()
    info = requests.post(f"{tt.API}/post/publish/creator_info/query/", json={},
                         headers={"Authorization": f"Bearer {token}"}, timeout=20).json()
    data = info.get("data", {})
    return f"@{data.get('creator_username')}, allowed privacy: {data.get('privacy_level_options')}"


print("Checking setup:")
for name, fn in [("AI (Gemini/Groq)", gemini), ("Pexels", pexels), ("Pixabay", pixabay), ("YouTube", youtube),
                 ("Instagram", instagram), ("TikTok", tiktok)]:
    check(name, fn)
