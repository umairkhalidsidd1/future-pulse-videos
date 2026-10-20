"""YouTube upload with the official Data API v3 (OAuth refresh token, no browser needed)."""
from pathlib import Path

from ..config import CFG, secret

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]   # the learning loop reads channel statistics


def _token(channel: str | None) -> str | None:
    """Each channel has its own login: YT_REFRESH_TOKEN_<SECRETS> (falls back to YT_REFRESH_TOKEN)."""
    key = (CFG.get("channels", {}).get(channel or "", {}) or {}).get("secrets")
    return (secret(f"YT_REFRESH_TOKEN_{key}") if key else None) or secret("YT_REFRESH_TOKEN")


def ready(channel: str | None = None) -> bool:
    return CFG["upload"]["youtube"]["enabled"] and bool(
        secret("YT_CLIENT_ID") and secret("YT_CLIENT_SECRET") and _token(channel))


def _client(channel: str | None = None):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=_token(channel), client_id=secret("YT_CLIENT_ID"),
                        client_secret=secret("YT_CLIENT_SECRET"), token_uri="https://oauth2.googleapis.com/token",
                        scopes=SCOPES[:2])   # upload only: older logins don't include the statistics permission
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def upload(video: Path, *, title: str, description: str, tags: list[str], thumbnail: Path | None = None,
           comment: str | None = None, channel: str | None = None, publish_at: str | None = None,
           category: str | None = None) -> str:
    """publish_at: RFC 3339 time (e.g. 2026-10-21T15:00:00Z). The video is uploaded as private and YouTube
    publishes it by itself at that time, so rendering can happen whenever the Mac is free."""
    from googleapiclient.http import MediaFileUpload
    cfg = CFG["upload"]["youtube"]
    yt = _client(channel)
    status = {"privacyStatus": cfg["privacy"], "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(cfg.get("ai_disclosure"))}
    if publish_at:
        status.update({"privacyStatus": "private", "publishAt": publish_at})
    body = {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:30],
                    "categoryId": category or cfg["category_id"], "defaultLanguage": CFG["channel"]["language"],
                    "defaultAudioLanguage": CFG["channel"]["language"]},
        "status": status,
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=5)
    video_id = response["id"]
    got = response.get("status", {}).get("privacyStatus")
    print(f"  [youtube] uploaded https://youtu.be/{video_id} (privacy: {got}{', publishes ' + publish_at if publish_at else ''})")
    if got != ("private" if publish_at else cfg["privacy"]):
        print("  [youtube] NOTE: YouTube changed the privacy. Your API project may need Google's audit.")

    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
        except Exception as e:  # custom thumbnails need a phone-verified channel
            print(f"  [youtube] thumbnail not set: {str(e)[:200]}")
    if comment and cfg.get("post_question_comment"):
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {
                "videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": comment}}}}).execute()
        except Exception as e:
            print(f"  [youtube] comment not posted: {str(e)[:200]}")
    return video_id
