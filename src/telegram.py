"""Minimal Telegram Bot API helpers."""
import json
import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"

YES_WORDS = {"yes", "y", "yes.", "yes!", "ok post", "post", "haan", "ha", "han"}


def send_text(text):
    r = requests.post(f"{API}/sendMessage", data={"chat_id": CHAT_ID, "text": text[:4096],
                                                   "disable_web_page_preview": True}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]


def send_album(paths):
    """Send up to 10 images as one album."""
    for start in range(0, len(paths), 10):
        chunk = paths[start:start + 10]
        files, media = {}, []
        for i, p in enumerate(chunk):
            key = f"p{i}"
            files[key] = open(p, "rb")
            media.append({"type": "photo", "media": f"attach://{key}"})
        try:
            r = requests.post(f"{API}/sendMediaGroup",
                              data={"chat_id": CHAT_ID, "media": json.dumps(media)},
                              files=files, timeout=120)
            r.raise_for_status()
        finally:
            for f in files.values():
                f.close()


def latest_update_id():
    r = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=30)
    r.raise_for_status()
    res = r.json()["result"]
    return res[-1]["update_id"] if res else 0


def approved_since(offset, since_ts):
    """True if the owner replied yes after the preview was sent."""
    r = requests.get(f"{API}/getUpdates", params={"offset": offset + 1, "timeout": 0}, timeout=30)
    r.raise_for_status()
    decision = None
    for u in r.json()["result"]:
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != str(CHAT_ID) or m.get("date", 0) < since_ts:
            continue
        text = (m.get("text") or "").strip().lower()
        if text in YES_WORDS:
            decision = True
        elif text in {"no", "n", "skip", "nahi"}:
            decision = False
    return bool(decision)
