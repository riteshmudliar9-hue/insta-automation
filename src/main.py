"""Entry point.

python src/main.py prepare          # 7:00 IST - make carousel, send Telegram preview
python src/main.py prepare --dry-run # same, but clearly marked and never published
python src/main.py publish          # 9:00 IST - post if owner replied "yes"
python src/main.py refresh-token    # writes new IG token to $NEW_TOKEN_FILE
"""
import csv
import datetime as dt
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai  # noqa: E402
import instagram  # noqa: E402
import render  # noqa: E402
import sources  # noqa: E402
import telegram  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_CSV = os.path.join(ROOT, "data", "posts.csv")
PENDING = os.path.join(ROOT, "data", "pending.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
FIELDS = ["date", "topic", "status", "post_link", "sources"]


def today():
    return dt.datetime.now(IST).strftime("%Y-%m-%d")


def read_log():
    if not os.path.exists(LOG_CSV):
        return []
    with open(LOG_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_log(rows):
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def recent_topics(days=30):
    cutoff = (dt.datetime.now(IST) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    return [r["topic"] for r in read_log() if r["date"] >= cutoff]


def pixabay_photo(query):
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or not query:
        return None
    try:
        r = requests.get("https://pixabay.com/api/", params={
            "key": key, "q": query, "image_type": "photo", "orientation": "horizontal",
            "safesearch": "true", "per_page": 5}, timeout=30)
        hits = r.json().get("hits", [])
        if not hits:
            return None
        return requests.get(hits[0]["largeImageURL"], timeout=60).content
    except Exception as ex:
        print("[pixabay] skipped:", ex)
        return None


def full_caption(post):
    return post["caption"].strip() + "\n.\n.\n" + " ".join(post["hashtags"])


def prepare(dry_run=False):
    date = today()
    headlines = sources.fetch_all()
    if len(headlines) < 3:
        raise RuntimeError("Too few headlines fetched; aborting today.")
    post = ai.generate_post(headlines, recent_topics(), os.environ["GEMINI_API_KEY"])
    print(json.dumps(post, indent=2, ensure_ascii=False))
    folder = os.path.join(ROOT, "output", "dry-run" if dry_run else date)
    paths = render.render_carousel(post, folder, pixabay_photo(post.get("image_query")))

    offset = telegram.latest_update_id()
    sent_at = int(dt.datetime.now().timestamp())
    tag = "DRY RUN (will NOT be posted)" if dry_run else f"Preview for {date}"
    telegram.send_text(f"{tag}\nTopic: {post['topic']}")
    telegram.send_album(paths)
    src = "\n".join(f"- {s['source']}: {s['title']}" for s in post.get("sources", []))
    telegram.send_text(f"CAPTION:\n\n{full_caption(post)}\n\nSources used:\n{src or '-'}")
    if dry_run:
        telegram.send_text("Dry run complete. Nothing will be posted.")
        return

    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump({"date": date, "post": post, "files": [os.path.relpath(p, ROOT) for p in paths],
                   "tg_offset": offset, "sent_at": sent_at}, f, indent=2, ensure_ascii=False)
    rows = [r for r in read_log() if r["date"] != date]
    rows.append({"date": date, "topic": post["topic"], "status": "pending", "post_link": "",
                 "sources": " | ".join(s["link"] for s in post.get("sources", []))})
    write_log(rows)
    telegram.send_text('Reply "yes" before 9:00 AM to post this. No reply = skip.')


def publish():
    if not os.path.exists(PENDING):
        print("Nothing pending.")
        return
    with open(PENDING, encoding="utf-8") as f:
        pend = json.load(f)
    date = pend["date"]
    rows = read_log()
    row = next((r for r in rows if r["date"] == date), None)
    if date != today():
        print(f"Pending post is from {date}, not today; skipping.")
        return
    if row and row["status"] != "pending":
        print("Already handled today.")
        return
    if not telegram.approved_since(pend["tg_offset"], pend["sent_at"]):
        if row:
            row["status"] = "skipped"
        write_log(rows)
        telegram.send_text(f"No 'yes' received - skipped today's post ({pend['post']['topic']}).")
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    urls = [f"https://raw.githubusercontent.com/{repo}/{branch}/{p}" for p in pend["files"]]
    media_id, link = instagram.publish_carousel(urls, full_caption(pend["post"]))
    if row:
        row["status"], row["post_link"] = "posted", link
    write_log(rows)
    telegram.send_text(f"Posted! {link}")


def refresh_token():
    token, expires = instagram.refresh_token()
    out = os.environ.get("NEW_TOKEN_FILE", "new_token.txt")
    with open(out, "w") as f:
        f.write(token)
    print(f"Token refreshed; valid for {int(expires or 0) // 86400} days.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "prepare":
        prepare(dry_run="--dry-run" in sys.argv)
    elif cmd == "publish":
        publish()
    elif cmd == "refresh-token":
        refresh_token()
    else:
        print(__doc__)
        sys.exit(1)
