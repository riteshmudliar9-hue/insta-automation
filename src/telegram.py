"""Telegram: previews, daily report, and 'stop' commands from the owner."""
import json
import os
import re

import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{TOKEN}"


def send_text(text):
    for i in range(0, len(text), 4000):
        r = requests.post(f"{API}/sendMessage", data={"chat_id": CHAT_ID, "text": text[i:i + 4000],
                                                       "disable_web_page_preview": True}, timeout=30)
        r.raise_for_status()


def send_album(paths, caption=""):
    for start in range(0, len(paths), 10):
        chunk = paths[start:start + 10]
        files, media = {}, []
        for i, p in enumerate(chunk):
            files[f"p{i}"] = open(p, "rb")
            m = {"type": "photo", "media": f"attach://p{i}"}
            if i == 0 and start == 0 and caption:
                m["caption"] = caption[:1000]
            media.append(m)
        try:
            requests.post(f"{API}/sendMediaGroup", data={"chat_id": CHAT_ID, "media": json.dumps(media)},
                          files=files, timeout=120).raise_for_status()
        finally:
            for f in files.values():
                f.close()


def send_video(path, caption=""):
    with open(path, "rb") as f:
        requests.post(f"{API}/sendVideo", data={"chat_id": CHAT_ID, "caption": caption[:1000],
                                                "supports_streaming": "true"},
                      files={"video": f}, timeout=300).raise_for_status()


def messages_since(ts):
    """Owner's text messages after unix time ts."""
    r = requests.get(f"{API}/getUpdates", params={"timeout": 0}, timeout=30)
    r.raise_for_status()
    out = []
    for u in r.json().get("result", []):
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) == str(CHAT_ID) and m.get("date", 0) >= ts:
            out.append((m.get("date"), (m.get("text") or "").strip()))
    return out


def stop_commands(ts):
    """Returns (stop_all, set_of_ids). 'stop' / 'stop all' / 'stop R2' / 'stop C1 R3'."""
    stop_all, ids = False, set()
    for _, text in messages_since(ts):
        t = text.lower()
        if t in ("stop", "stop all", "pause"):
            stop_all = True
        elif t.startswith("stop"):
            ids |= {x.upper() for x in re.findall(r"\b[rc]\d\b", t)}
        elif t in ("resume", "go"):
            stop_all = False
    return stop_all, ids
