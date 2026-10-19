"""TikTok with the official Content Posting API.

Until TikTok audits your app, posts can only be private (SELF_ONLY), and only to a private account.
mode "inbox" sends the video to your TikTok inbox as a draft instead; you then tap Post in the app.
"""
import os
import subprocess
import time
from pathlib import Path

import requests

from ..config import CFG, secret

API = "https://open.tiktokapis.com/v2"


def ready() -> bool:
    return CFG["upload"]["tiktok"]["enabled"] and all(
        secret(k) for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN"))


def _check(r: requests.Response) -> dict:
    data = r.json() if r.content else {}
    err = data.get("error", {})
    if r.status_code >= 400 or (err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok HTTP {r.status_code}: {r.text[:400]}")
    return data


def _access_token() -> str:
    r = requests.post(f"{API}/oauth/token/", headers={"Content-Type": "application/x-www-form-urlencoded"}, data={
        "client_key": secret("TIKTOK_CLIENT_KEY"), "client_secret": secret("TIKTOK_CLIENT_SECRET"),
        "grant_type": "refresh_token", "refresh_token": secret("TIKTOK_REFRESH_TOKEN")}, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"TikTok token refresh failed: {r.text[:300]}")
    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != secret("TIKTOK_REFRESH_TOKEN"):
        _save_refresh_token(new_refresh)
    return data["access_token"]


def _save_refresh_token(token: str):
    """TikTok may hand out a new refresh token. Store it back into GitHub Secrets if we can."""
    os.environ["TIKTOK_REFRESH_TOKEN"] = token
    if secret("GH_PAT") and secret("GITHUB_REPOSITORY"):
        p = subprocess.run(["gh", "secret", "set", "TIKTOK_REFRESH_TOKEN", "--repo", secret("GITHUB_REPOSITORY")],
                           input=token, text=True, capture_output=True, env={**os.environ, "GH_TOKEN": secret("GH_PAT")})
        print("  [tiktok] saved new refresh token" if p.returncode == 0 else f"  [tiktok] could not save token: {p.stderr[:200]}")
    else:
        print("  [tiktok] WARNING: TikTok returned a new refresh token but GH_PAT is not set to save it.")


def _wait(auth: dict, publish_id: str) -> str:
    for _ in range(40):
        st = _check(requests.post(f"{API}/post/publish/status/fetch/", headers=auth,
                                  json={"publish_id": publish_id}, timeout=30))["data"]
        status = st.get("status")
        if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
            print(f"  [tiktok] {status} ({publish_id})")
            return publish_id
        if status == "FAILED":
            raise RuntimeError(f"TikTok failed: {st.get('fail_reason')}")
        time.sleep(15)
    raise RuntimeError("TikTok processing timed out (the next run will check it again)")


def upload(video: Path, caption: str, pending: dict | None = None, save=lambda: None) -> str:
    cfg = CFG["upload"]["tiktok"]
    token = _access_token()
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}
    pending = {} if pending is None else pending
    earlier = pending.get("tiktok_publish_id")
    if earlier:  # an earlier run already uploaded: check it instead of posting twice
        try:
            return _wait(auth, earlier)
        except RuntimeError as e:
            if "timed out" in str(e):
                raise
            pending.pop("tiktok_publish_id", None)  # it failed; upload again below
    size = video.stat().st_size
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    count = max(1, size // chunk)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": count}

    if cfg["mode"] == "inbox":
        init = _check(requests.post(f"{API}/post/publish/inbox/video/init/", headers=auth,
                                    json={"source_info": source}, timeout=30))
    else:
        info = _check(requests.post(f"{API}/post/publish/creator_info/query/", headers=auth, json={}, timeout=30))
        options = info["data"].get("privacy_level_options", [])
        privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else "SELF_ONLY"
        if privacy != "PUBLIC_TO_EVERYONE":
            print("  [tiktok] NOTE: posting as private (SELF_ONLY). Public posts need TikTok's app audit.")
        post_info = {"title": caption[:2200], "privacy_level": privacy, "disable_comment": False,
                     "disable_duet": False, "disable_stitch": False, "video_cover_timestamp_ms": 1000,
                     "is_aigc": bool(cfg.get("is_aigc"))}
        init = _check(requests.post(f"{API}/post/publish/video/init/", headers=auth,
                                    json={"post_info": post_info, "source_info": source}, timeout=30))

    publish_id, upload_url = init["data"]["publish_id"], init["data"]["upload_url"]
    pending["tiktok_publish_id"] = publish_id
    save()
    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            body = f.read(end - start + 1)
            r = requests.put(upload_url, data=body, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if r.status_code not in (200, 201, 206):
                pending.pop("tiktok_publish_id", None)
                raise RuntimeError(f"TikTok chunk {i + 1}/{count} failed: HTTP {r.status_code} {r.text[:200]}")

    return _wait(auth, publish_id)
