"""Instagram Reels with the official Graph API (Facebook Login for Business + resumable upload).

Needs: an Instagram Business/Creator account linked to a Facebook Page, IG_USER_ID and a
non-expiring System User token in IG_ACCESS_TOKEN (see SETUP.md).
"""
import time
from pathlib import Path

import requests

from ..config import CFG, secret


def ready() -> bool:
    return CFG["upload"]["instagram"]["enabled"] and bool(secret("IG_USER_ID") and secret("IG_ACCESS_TOKEN"))


def _check(r: requests.Response) -> dict:
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def _status(graph: str, container: str, auth: dict) -> dict:
    return _check(requests.get(f"{graph}/{container}", params={"fields": "status_code,status"},
                               headers=auth, timeout=30))


def upload(video: Path, caption: str, pending: dict | None = None, save=lambda: None) -> str:
    cfg = CFG["upload"]["instagram"]
    v, ig, token = cfg["graph_version"], secret("IG_USER_ID"), secret("IG_ACCESS_TOKEN")
    graph = f"https://graph.facebook.com/{v}"
    auth = {"Authorization": f"Bearer {token}"}  # token in a header, never in a URL that could be logged
    pending = {} if pending is None else pending

    container = pending.get("instagram_container")
    if container:  # an earlier run already uploaded: finish that one instead of posting twice
        code = _status(graph, container, auth).get("status_code")
        if code == "PUBLISHED":
            print(f"  [instagram] already published by an earlier run ({container})")
            return container
        if code in ("ERROR", "EXPIRED", None):
            container = None

    if not container:
        container = _check(requests.post(f"{graph}/{ig}/media", headers=auth, data={
            "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
            "share_to_feed": "true" if cfg.get("share_to_feed") else "false"}, timeout=60))["id"]
        size = video.stat().st_size
        with open(video, "rb") as f:
            _check(requests.post(f"https://rupload.facebook.com/ig-api-upload/{v}/{container}",
                                 headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
                                 data=f, timeout=600))
        pending["instagram_container"] = container
        save()

    for _ in range(40):  # up to ~10 minutes
        status = _status(graph, container, auth)
        code = status.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            pending.pop("instagram_container", None)
            raise RuntimeError(f"Instagram processing failed: {status}")
        time.sleep(15)
    else:
        raise RuntimeError("Instagram processing timed out (the next run will check it again)")

    media_id = _check(requests.post(f"{graph}/{ig}/media_publish", headers=auth,
                                    data={"creation_id": container}, timeout=60))["id"]
    print(f"  [instagram] published reel {media_id}")
    return media_id
