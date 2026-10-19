"""Run once on your Mac to get the TikTok refresh token.

Needs TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in the .env file.
The redirect URI must be exactly the one you registered in the TikTok developer portal
(for example a page on your own website, like https://yourdomain.com/tiktok).

1. .venv/bin/python scripts/tiktok_auth.py
2. Open the printed link, log in to TikTok and allow access.
3. TikTok sends you to your redirect page. Copy the FULL address from the browser bar and paste it here.
"""
import secrets
import sys
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import secret  # noqa: E402  (also loads .env)

key, client_secret, redirect = secret("TIKTOK_CLIENT_KEY"), secret("TIKTOK_CLIENT_SECRET"), secret("TIKTOK_REDIRECT_URI")
if not (key and client_secret and redirect):
    sys.exit("Put TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in .env first.")

state = secrets.token_urlsafe(16)
url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
    "client_key": key, "scope": "user.info.basic,video.publish,video.upload", "response_type": "code",
    "redirect_uri": redirect, "state": state})
print("\n1) Open this link:\n\n" + url + "\n")
back = input("2) Paste the full address you were sent to: ").strip()
query = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
if query.get("state", [""])[0] != state:
    sys.exit("The state value does not match. Start again.")
code = query["code"][0]

r = requests.post("https://open.tiktokapis.com/v2/oauth/token/",
                  headers={"Content-Type": "application/x-www-form-urlencoded"},
                  data={"client_key": key, "client_secret": client_secret, "code": code,
                        "grant_type": "authorization_code", "redirect_uri": redirect}, timeout=30)
data = r.json()
if "refresh_token" not in data:
    sys.exit(f"Failed: {r.text}")
print("\nAdd this as a GitHub Secret:\n")
print(f"TIKTOK_REFRESH_TOKEN = {data['refresh_token']}")
print(f"(valid for {int(data.get('refresh_expires_in', 0)) // 86400} days)")
