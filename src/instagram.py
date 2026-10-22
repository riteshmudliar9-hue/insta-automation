"""Instagram API (Instagram Login) carousel publishing + token refresh."""
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
        raise RuntimeError(f"IG {path} -> {r.status_code}: {r.text}")
    return r.json()


def _wait_ready(container_id, tries=30):
    for _ in range(tries):
        r = requests.get(f"{GRAPH}/{container_id}", headers=_h(),
                         params={"fields": "status_code,status"}, timeout=30).json()
        code = r.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"container {container_id} failed: {r}")
        time.sleep(5)
    raise RuntimeError(f"container {container_id} not ready in time")


def publish_carousel(image_urls, caption):
    # 1) child containers
    children = []
    for url in image_urls:
        c = _post(f"{IG_USER_ID}/media", {"image_url": url, "is_carousel_item": "true"})
        children.append(c["id"])
    for cid in children:
        _wait_ready(cid)
    # 2) carousel container
    parent = _post(f"{IG_USER_ID}/media", {"media_type": "CAROUSEL",
                                            "children": ",".join(children), "caption": caption})
    _wait_ready(parent["id"])
    # 3) publish
    pub = _post(f"{IG_USER_ID}/media_publish", {"creation_id": parent["id"]})
    media_id = pub["id"]
    link = requests.get(f"{GRAPH}/{media_id}", headers=_h(),
                        params={"fields": "permalink"}, timeout=30).json().get("permalink", "")
    return media_id, link


def refresh_token():
    """Extends a long-lived token by 60 days (token must be >24h old)."""
    r = requests.get("https://graph.instagram.com/refresh_access_token",
                     params={"grant_type": "ig_refresh_token", "access_token": TOKEN}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"refresh failed {r.status_code}: {r.text}")
    j = r.json()
    return j["access_token"], j.get("expires_in")
