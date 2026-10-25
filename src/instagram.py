"""Instagram API (Instagram Login): carousel + reel publishing, insights, token refresh."""
import os
import time

import requests

GRAPH = "https://graph.instagram.com/v23.0"
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "")
IG_USER_ID = os.environ.get("IG_USER_ID", "")


def _h():
    return {"Authorization": f"Bearer {TOKEN}"}


def _post(path, data):
    r = requests.post(f"{GRAPH}/{path}", headers=_h(), data=data, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"IG {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def _get(path, params=None):
    r = requests.get(f"{GRAPH}/{path}", headers=_h(), params=params or {}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"IG GET {path} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def _wait_ready(cid, tries=30):
    for _ in range(tries):
        code = _get(cid, {"fields": "status_code,status"}).get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {cid} failed: {code}")
        time.sleep(5)
    raise RuntimeError(f"container {cid} not ready in time")


def _permalink(mid):
    try:
        return _get(mid, {"fields": "permalink"}).get("permalink", "")
    except Exception:
        return ""


def publish_carousel(image_urls, caption):
    kids = [_post(f"{IG_USER_ID}/media", {"image_url": u, "is_carousel_item": "true"})["id"] for u in image_urls]
    for k in kids:
        _wait_ready(k)
    parent = _post(f"{IG_USER_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})
    _wait_ready(parent["id"])
    mid = _post(f"{IG_USER_ID}/media_publish", {"creation_id": parent["id"]})["id"]
    return mid, _permalink(mid)


def publish_reel(video_url, caption):
    c = _post(f"{IG_USER_ID}/media", {"media_type": "REELS", "video_url": video_url, "caption": caption,
                                       "share_to_feed": "true"})
    _wait_ready(c["id"], tries=72)
    mid = _post(f"{IG_USER_ID}/media_publish", {"creation_id": c["id"]})["id"]
    return mid, _permalink(mid)


def recent_media(limit=15):
    return _get(f"{IG_USER_ID}/media", {"fields": "id,caption,media_type,timestamp,permalink", "limit": limit}).get(
        "data", [])


REEL_METRICS = ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
POST_METRICS = ["reach", "views", "likes", "comments", "shares", "saved", "total_interactions",
                "profile_visits", "follows"]


def media_insights(mid, is_reel):
    """Dict of metric -> value. Unsupported metrics are skipped, never invented."""
    metrics = REEL_METRICS if is_reel else POST_METRICS
    out = {}
    try:
        data = _get(f"{mid}/insights", {"metric": ",".join(metrics)}).get("data", [])
        for d in data:
            out[d["name"]] = (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
        return out
    except Exception:
        pass
    for m in metrics:
        try:
            d = _get(f"{mid}/insights", {"metric": m}).get("data", [])
            if d:
                out[m] = (d[0].get("values") or [{}])[0].get("value", d[0].get("total_value", {}).get("value"))
        except Exception:
            continue
    return out


def account_info():
    return _get(IG_USER_ID, {"fields": "followers_count,media_count"})


def refresh_token():
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": TOKEN}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"refresh failed {r.status_code}: {r.text}")
    j = r.json()
    return j["access_token"], j.get("expires_in")


# ---------------- comments + private replies (comment-to-DM) ----------------
def media_comments(mid, limit=50):
    """Top-level comments on a post. Needs the instagram_business_manage_comments permission."""
    return _get(f"{mid}/comments", {"fields": "id,text,timestamp,from,username", "limit": limit}).get("data", [])


def reply_comment(comment_id, text):
    return _post(f"{comment_id}/replies", {"message": text})


def private_reply(comment_id, text):
    """One DM to the person who wrote the comment (allowed once per comment, within 7 days).
    Needs the instagram_business_manage_messages permission."""
    r = requests.post(f"{GRAPH}/{IG_USER_ID}/messages", headers={**_h(), "Content-Type": "application/json"},
                      json={"recipient": {"comment_id": comment_id}, "message": {"text": text[:1000]}}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"IG messages -> {r.status_code}: {r.text[:300]}")
    return r.json()
