"""Entry point.

python src/main.py prepare           # 7:00 AM IST - carousel + reel, Telegram preview
python src/main.py prepare --dry-run # same, clearly marked, never published
python src/main.py publish           # 9:00 AM IST - post carousel if approved
python src/main.py publish-reel      # 6:00 PM IST - post reel if approved
python src/main.py refresh-token     # writes new IG token to $NEW_TOKEN_FILE
"""
import csv
import datetime as dt
import json
import os
import shutil
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
FIELDS = ["date", "topic", "status", "post_link", "reel_status", "reel_link", "sources"]
KEEP_DAYS = 10  # older output folders are deleted to keep the repo/Pages site small


def today():
    return dt.datetime.now(IST).strftime("%Y-%m-%d")


def read_log():
    if not os.path.exists(LOG_CSV):
        return []
    with open(LOG_CSV, newline="", encoding="utf-8") as f:
        return [{k: (v or "") for k, v in r.items() if k in FIELDS} for r in csv.DictReader(f)]


def write_log(rows):
    with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        w.writeheader()
        w.writerows(rows)


def recent_topics(days=30):
    cutoff = (dt.datetime.now(IST) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    return [r["topic"] for r in read_log() if r["date"] >= cutoff]


def cleanup_old_output():
    cutoff = (dt.datetime.now(IST) - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    out = os.path.join(ROOT, "output")
    for name in os.listdir(out) if os.path.isdir(out) else []:
        if len(name) == 10 and name[4] == "-" and name < cutoff:
            shutil.rmtree(os.path.join(out, name), ignore_errors=True)


def pixabay_photo(query):
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key or not query:
        return None
    try:
        r = requests.get("https://pixabay.com/api/", params={
            "key": key, "q": query, "image_type": "photo", "orientation": "horizontal",
            "safesearch": "true", "per_page": 5}, timeout=30)
        if r.status_code != 200 or not r.text.startswith("{"):
            print(f"[pixabay] HTTP {r.status_code}: {r.text[:120]} (key length {len(key)})")
            return None
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

    reel_path = None
    try:
        import reel
        reel_path = reel.build_reel(post, paths, os.path.join(folder, "reel.mp4"))
    except Exception as ex:  # a reel problem must never block the carousel
        print("[reel] failed:", ex)

    offset = telegram.latest_update_id()
    sent_at = int(dt.datetime.now().timestamp())
    tag = "DRY RUN (will NOT be posted)" if dry_run else f"Preview for {date}"
    telegram.send_text(f"{tag}\nTopic: {post['topic']}")
    telegram.send_album(paths)
    if reel_path:
        telegram.send_video(reel_path, "Reel preview")
    else:
        telegram.send_text("(Reel could not be made today - carousel only.)")
    src = "\n".join(f"- {s['source']}: {s['title']}" for s in post.get("sources", []))
    telegram.send_text(f"CAPTION:\n\n{full_caption(post)}\n\nSources used:\n{src or '-'}")
    if dry_run:
        telegram.send_text("Dry run complete. Nothing will be posted.")
        return

    cleanup_old_output()
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump({"date": date, "post": post, "files": [os.path.relpath(p, ROOT) for p in paths],
                   "reel": os.path.relpath(reel_path, ROOT) if reel_path else None,
                   "tg_offset": offset, "sent_at": sent_at, "decision": None},
                  f, indent=2, ensure_ascii=False)
    rows = [r for r in read_log() if r["date"] != date]
    rows.append({"date": date, "topic": post["topic"], "status": "pending",
                 "reel_status": "pending" if reel_path else "none",
                 "sources": " | ".join(s["link"] for s in post.get("sources", []))})
    write_log(rows)
    telegram.send_text(
        'Reply before 9:00 AM:\n'
        '"yes" = post carousel at 9 AM + reel at 6 PM\n'
        '"carousel" = carousel only\n"reel" = reel only (6 PM)\n'
        'No reply = skip today.')


def _load_today():
    if not os.path.exists(PENDING):
        print("Nothing pending.")
        return None, None, None
    with open(PENDING, encoding="utf-8") as f:
        pend = json.load(f)
    if pend["date"] != today():
        print(f"Pending post is from {pend['date']}, not today; skipping.")
        return None, None, None
    rows = read_log()
    row = next((r for r in rows if r["date"] == pend["date"]), None)
    if row is None:
        row = {"date": pend["date"], "topic": pend["post"]["topic"]}
        rows.append(row)
    return pend, rows, row


def _decision(pend):
    """Use the stored decision, or read Telegram (replies after 9 AM still count for the reel)."""
    d = telegram.decision_since(pend["tg_offset"], pend["sent_at"]) or pend.get("decision")
    pend["decision"] = d
    with open(PENDING, "w", encoding="utf-8") as f:
        json.dump(pend, f, indent=2, ensure_ascii=False)
    return d


def _pages_url(rel_path):
    owner, repo = os.environ["GITHUB_REPOSITORY"].split("/")
    return f"https://{owner.lower()}.github.io/{repo}/{rel_path}"


def publish():
    pend, rows, row = _load_today()
    if not pend or row.get("status") not in ("pending", "", None):
        return
    d = _decision(pend)
    if d not in ("both", "carousel"):
        row["status"] = "skipped"
        write_log(rows)
        msg = "Carousel skipped (no 'yes' received)." if d is None else f"Carousel skipped (you said '{d}')."
        telegram.send_text(msg)
        return
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    urls = [f"https://raw.githubusercontent.com/{repo}/{branch}/{p}" for p in pend["files"]]
    _, link = instagram.publish_carousel(urls, full_caption(pend["post"]))
    row["status"], row["post_link"] = "posted", link
    write_log(rows)
    telegram.send_text(f"Carousel posted! {link}")


def publish_reel():
    pend, rows, row = _load_today()
    if not pend or not pend.get("reel") or row.get("reel_status") not in ("pending", "", None):
        return
    d = _decision(pend)
    if d not in ("both", "reel"):
        row["reel_status"] = "skipped"
        write_log(rows)
        telegram.send_text("Reel skipped today.")
        return
    url = _pages_url(pend["reel"])
    r = requests.head(url, timeout=30, allow_redirects=True)
    if r.status_code != 200:
        raise RuntimeError(f"Reel video not reachable on GitHub Pages yet ({r.status_code}): {url}")
    _, link = instagram.publish_reel(url, full_caption(pend["post"]))
    row["reel_status"], row["reel_link"] = "posted", link
    write_log(rows)
    telegram.send_text(f"Reel posted! {link}")


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
    elif cmd == "publish-reel":
        publish_reel()
    elif cmd == "refresh-token":
        refresh_token()
    else:
        print(__doc__)
        sys.exit(1)
