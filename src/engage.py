"""Comment-to-DM: when someone comments a Reel's keyword (e.g. "LIST"), send them the promised resource by DM
(Instagram private reply) and reply publicly so others see it works. Runs with every publish job.

Needs two Instagram permissions on the token: instagram_business_manage_comments and
instagram_business_manage_messages. Without them it logs a note once a day and does nothing.
"""
import datetime as dt
import json
import os
import re

import config
import instagram
import publisher
import telegram

STATE = os.path.join(config.DATA, "engage.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PUBLIC_REPLIES = ["DM bhej diya, check karo 📩", "Sent! Apne DMs check karo 📩", "Done, DM mein bheja hai 📩"]


def _load():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"done": {}, "errors": [], "last_permission_note": ""}


def _save(s):
    s["errors"] = s["errors"][-30:]
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1, ensure_ascii=False)


def _matches(text, keyword):
    words = re.findall(r"[A-Za-z0-9]+", (text or "").upper())
    return keyword.upper() in words


def run():
    if not publisher.enabled():
        print("engage: switched off")
        return
    s = _load()
    now = dt.datetime.now(IST)
    cutoff = (now - dt.timedelta(days=6)).strftime("%Y-%m-%d")
    posts = [e for e in publisher.load() if e.get("status") == "published" and e.get("media_id")
             and e.get("dm_keyword") and e.get("dm_text") and e["date"] >= cutoff]
    sent = 0
    for e in posts:
        try:
            comments = instagram.media_comments(e["media_id"])
        except Exception as ex:
            msg = str(ex)
            print("engage: cannot read comments:", msg[:200])
            if ("permission" in msg.lower() or "(#10)" in msg or "(#200)" in msg) and \
                    s.get("last_permission_note") != now.strftime("%Y-%m-%d"):
                s["last_permission_note"] = now.strftime("%Y-%m-%d")
                telegram.send_text("Comment-to-DM is waiting for Instagram permission (comments + messages). "
                                   "Until you approve it, people who comment the keyword won't get a DM.")
            break
        for c in comments:
            cid = c.get("id")
            if not cid or cid in s["done"]:
                continue
            if (c.get("username") or "").lower() == config.HANDLE.lstrip("@").lower():
                continue
            if not _matches(c.get("text"), e["dm_keyword"]):
                continue
            text = f"Hi! Ye raha aapka {e['dm_keyword']} 👇\n\n{e['dm_text']}\n\n— @{config.HANDLE.lstrip('@')}"
            try:
                instagram.private_reply(cid, text)
                s["done"][cid] = {"post": e["id"], "at": now.isoformat(), "dm": True}
                sent += 1
            except Exception as ex:
                s["done"][cid] = {"post": e["id"], "at": now.isoformat(), "dm": False, "error": str(ex)[:200]}
                s["errors"].append(f"{now.isoformat()} {e['id']} DM failed: {str(ex)[:200]}")
                continue
            try:
                instagram.reply_comment(cid, PUBLIC_REPLIES[sent % len(PUBLIC_REPLIES)])
            except Exception as ex:
                s["errors"].append(f"{now.isoformat()} {e['id']} public reply failed: {str(ex)[:200]}")
    _save(s)
    print(f"engage: {sent} DMs sent")
    return sent
