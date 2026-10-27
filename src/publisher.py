"""Queue + scheduled publishing with duplicate protection, retry log and owner 'stop' veto."""
import datetime as dt
import json
import os

import config
import history
import instagram
import requests
import telegram

QUEUE = os.path.join(config.DATA, "queue.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load():
    if not os.path.exists(QUEUE):
        return []
    with open(QUEUE, encoding="utf-8") as f:
        return json.load(f)


def save(q):
    os.makedirs(config.DATA, exist_ok=True)
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(q, f, indent=1, ensure_ascii=False)


def enqueue(results, produced_at):
    """Approved results → slots by score. Returns queued entries."""
    q = load()
    date = dt.datetime.fromtimestamp(produced_at, IST).strftime("%Y-%m-%d")
    out = []
    for kind, slots in (("reel", config.REEL_SLOTS), ("carousel", config.CAROUSEL_SLOTS)):
        ok = sorted([r for r in results if r["kind"] == kind and r["approved"]],
                    key=lambda r: -sum(r["review"]["scores"].values()))
        for r, slot in zip(ok, slots):
            rel = os.path.relpath(r["dir"], config.ROOT)
            files = sorted(f for f in os.listdir(r["dir"]) if f.startswith("slide_")) if kind == "carousel" else ["reel.mp4"]
            e = {"id": r["id"], "kind": kind, "date": date, "slot": f"{date}T{slot}", "dir": rel, "files": files,
                 "caption": r["caption_final"], "topic": r["idea"]["idea"], "format": r["idea"]["format"],
                 "hook": r["hook"], "keywords": r["piece"].get("keywords", []), "scores": r["review"]["scores"],
                 "status": "queued", "produced_at": produced_at, "log": [],
                 "dm_keyword": (r["piece"].get("dm_keyword") or "").strip().upper(),
                 "dm_text": (r["piece"].get("dm_text") or "").strip()}
            q.append(e)
            out.append(e)
            history.add({"id": e["id"], "date": date, "kind": kind, "format": e["format"], "topic": e["topic"],
                         "hook": e["hook"], "keywords": e["keywords"], "status": "queued"})
    save(q)
    return out


def _urls(e):
    repo = os.environ["GITHUB_REPOSITORY"]
    owner, name = repo.split("/")
    if e["kind"] == "reel":
        return [f"https://{owner.lower()}.github.io/{name}/{e['dir']}/{(e.get('files') or ['reel.mp4'])[0]}"]
    return [f"https://raw.githubusercontent.com/{repo}/main/{e['dir']}/{f}" for f in e["files"]]


def _already_live(e):
    """Duplicate guard: was this caption already published (e.g. a crashed previous run)?"""
    head = e["caption"][:80]
    for m in instagram.recent_media(15):
        if (m.get("caption") or "")[:80] == head:
            return m
    return None


def enabled():
    path = os.path.join(config.DATA, "control.json")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        return bool(json.load(f).get("publishing_enabled"))


def publish_due():
    if not enabled():
        print("publishing is switched off in data/control.json")
        return []
    q = load()
    now = dt.datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    try:
        import presenter
        if presenter.process(q, today):
            save(q)
    except Exception as ex:
        print("[presenter] processing failed:", ex)
        presenter = None
    slot_of = (lambda e: presenter.effective_slot(e)) if presenter else (lambda e: e["slot"])
    pending = [e for e in q if e["status"] in ("queued", "publishing") and e["date"] == today]
    if not pending:
        print("nothing due")
        return []
    stop_all, stop_ids = telegram.stop_commands(min(e["produced_at"] for e in pending))
    done = []
    for kind in ("carousel", "reel"):            # at most one of each kind per run → natural spacing
        due = [e for e in pending if e["kind"] == kind and slot_of(e) <= now.strftime("%Y-%m-%dT%H:%M")]
        if not due:
            continue
        e = sorted(due, key=lambda x: x["slot"])[0]
        short = e["id"].split("-")[0]
        if stop_all or short in stop_ids:
            e["status"] = "stopped"
            e["log"].append(f"{now.isoformat()} stopped by owner")
            history.update(e["id"], status="stopped")
            telegram.send_text(f"Stopped {short} as you asked: {e['topic']}")
            continue
        live = _already_live(e)
        if live:
            e.update(status="published", media_id=live["id"], permalink=live.get("permalink", ""))
            e["log"].append(f"{now.isoformat()} found already published; not posting again")
            continue
        e["status"] = "publishing"
        save(q)
        try:
            urls = _urls(e)
            if kind == "reel":
                r = requests.head(urls[0], timeout=30, allow_redirects=True)
                if r.status_code != 200:            # Pages still deploying: try next run, not a failed attempt
                    e["status"] = "queued"
                    e["log"].append(f"{now.isoformat()} waiting for GitHub Pages ({r.status_code})")
                    save(q)
                    continue
                mid, link = instagram.publish_reel(urls[0], e["caption"])
            else:
                mid, link = instagram.publish_carousel(urls, e["caption"])
            e.update(status="published", media_id=mid, permalink=link, published_at=now.isoformat())
            e["log"].append(f"{now.isoformat()} published {link}")
            history.update(e["id"], status="published", media_id=mid, permalink=link)
            telegram.send_text(f"Posted {short} ({e['format']}): {link}")
            done.append(e)
        except Exception as ex:
            e["status"] = "queued"
            e.setdefault("attempts", 0)
            e["attempts"] += 1
            e["log"].append(f"{now.isoformat()} error: {str(ex)[:300]}")
            if e["attempts"] >= 3:
                e["status"] = "failed"
                history.update(e["id"], status="failed")
                telegram.send_text(f"Could not publish {short} after 3 tries. Last error: {str(ex)[:300]}")
        save(q)
    # expire anything left from previous days
    for e in q:
        if e["status"] == "queued" and e["date"] < today:
            e["status"] = "expired"
    save(q)
    return done
