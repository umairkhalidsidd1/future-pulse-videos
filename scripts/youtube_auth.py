"""Run once on your Mac to log in to YouTube. Saves the keys straight into .env (prints no secrets).

1. Put the OAuth file you downloaded from Google Cloud in this project as client_secret.json
2. .venv/bin/python scripts/youtube_auth.py
3. A browser opens. Pick the Google account that owns the channel and allow access.
   If Google says the app isn't verified, click Advanced -> Go to Future Pulse Uploader.
4. Then run scripts/push_secrets.py to copy the keys to GitHub.
"""
import re
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ROOT = Path(__file__).resolve().parent.parent
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]


def save_env(values: dict):
    env = ROOT / ".env"
    text = env.read_text() if env.exists() else ""
    for key, value in values.items():
        line = f"{key}={value}"
        if re.search(rf"^{key}=.*$", text, re.M):
            text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
        else:
            text += f"\n{line}"
    env.write_text(text if text.endswith("\n") else text + "\n")
    env.chmod(0o600)


flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / "client_secret.json"), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent",
                              success_message="Done! You can close this tab and go back to Claude.")
if not creds.refresh_token:
    raise SystemExit("Google gave no refresh token. Run this script again.")
save_env({"YT_CLIENT_ID": creds.client_id, "YT_CLIENT_SECRET": creds.client_secret,
          "YT_REFRESH_TOKEN": creds.refresh_token})
print("Saved YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN into .env")
