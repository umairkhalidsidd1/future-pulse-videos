"""Run once on your Mac to get the YouTube refresh token.

1. Put the OAuth file you downloaded from Google Cloud next to this project as client_secret.json
2. .venv/bin/python scripts/youtube_auth.py
3. A browser opens. Log in with the Google account that owns the channel and allow access.
4. Copy the three printed values into GitHub Secrets.
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
secret_file = Path(__file__).resolve().parent.parent / "client_secret.json"

flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print("\nAdd these as GitHub Secrets:\n")
print(f"YT_CLIENT_ID      = {creds.client_id}")
print(f"YT_CLIENT_SECRET  = {creds.client_secret}")
print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
