"""v2 entry point.

python src/main.py produce            # daily: research → write → render → quality gate → queue (05:30 IST)
python src/main.py pilot [N]          # pilot batch of N reels + N carousels, never published
python src/main.py publish-due        # every 30 min: publish queued items whose slot has arrived
python src/main.py engage             # every 30 min: DM the promised resource to people who comment the keyword
python src/main.py insights           # nightly: collect Insights, update learnings, send daily report
python src/main.py refresh-token      # weekly: renew the Instagram token
"""
import datetime as dt
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _cleanup(days=10):
    cutoff = (dt.datetime.now(IST) - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    for name in os.listdir(config.OUT) if os.path.isdir(config.OUT) else []:
        d = name.replace("pilot-", "")[:10]
        if len(d) == 10 and d[4] == "-" and d < cutoff:
            shutil.rmtree(os.path.join(config.OUT, name), ignore_errors=True)
        elif name.startswith("pilot-") and name[6:14] < cutoff.replace("-", ""):
            shutil.rmtree(os.path.join(config.OUT, name), ignore_errors=True)


def _send_previews(results, label):
    import telegram
    for r in results:
        if not r.get("dir"):
            continue
        s = r.get("review", {}).get("scores", {})
        short = r["id"].split("-")[0]
        status = r.get("slot_info") or ("APPROVED" if r["approved"] else "DRAFT (not publishing)")
        head = (f"{label} {short} · {r['kind']} · {r['idea']['format']}\n{status}\n"
                f"Hook: {r.get('hook')}\nScores: " + ", ".join(f"{k} {v}" for k, v in s.items()))
        if not r["approved"]:
            head += "\nWhy held back: " + "; ".join(r.get("reasons", [])[:4])
        try:
            if r["kind"] == "reel" and os.path.exists(os.path.join(r["dir"], "reel.mp4")):
                telegram.send_video(os.path.join(r["dir"], "reel.mp4"), head)
            else:
                imgs = sorted(os.path.join(r["dir"], f) for f in os.listdir(r["dir"]) if f.startswith("slide_"))
                telegram.send_album(imgs, head)
        except Exception as ex:
            print("[telegram] preview failed:", ex)


def produce():
    import pipeline
    import publisher
    import telegram
    if not publisher.enabled():
        print("production is switched off in data/control.json (use the pilot workflow to test)")
        return
    started = int(time.time())
    _cleanup()
    results, summary = pipeline.produce(config.MAX_REELS, config.MAX_CAROUSELS)
    queued = publisher.enqueue(results, started)
    try:
        import presenter
        planned = {e["id"] for e in presenter.plan(results, queued)}
    except Exception as ex:
        planned = set()
        print("[presenter] planning failed:", ex)
    ids = {e["id"] for e in queued}
    slots = {e["id"]: e["slot"][-5:] for e in publisher.load() if e["id"] in ids}
    for r in results:
        if r["id"] in planned:
            r["arjun"] = True
    for r in results:
        if r["id"] in slots:
            r["slot_info"] = f"Scheduled {slots[r['id']]} IST — reply 'stop {r['id'].split('-')[0]}' to cancel"
            if r.get("arjun"):
                r["slot_info"] += " (Arjun prompts come at 7 PM; his version replaces this once the clips arrive)"
    _send_previews(results, "TODAY")
    ok = sum(r["approved"] for r in results)
    telegram.send_text(f"Production {summary['date']}: {len(results)} made, {ok} approved and scheduled, "
                       f"{len(results) - ok} held back as drafts. Reply 'stop' to cancel all of today's posts.")


def pilot(n):
    import pipeline
    import telegram
    results, summary = pipeline.produce(n, n, pilot=True)
    _send_previews(results, "PILOT")
    ok = sum(r["approved"] for r in results)
    telegram.send_text(f"Pilot {summary['tag']}: {len(results)} made, {ok} passed the quality gate. "
                       f"Nothing was published.")


def publish_due():
    import publisher
    publisher.publish_due()


def daily_report():
    import insights
    import publisher
    import telegram
    perf = insights.collect()
    learn = insights.learn(perf)
    today = dt.datetime.now(IST).strftime("%Y-%m-%d")
    prod_path = os.path.join(config.OUT, today, "production.json")
    lines = [f"DAILY REPORT {today}"]
    if os.path.exists(prod_path):
        with open(prod_path, encoding="utf-8") as f:
            p = json.load(f)
        lines.append(f"Research: {p['sources']} sources → {p['ideas']} ideas, {len(p['rejected_ideas'])} rejected")
        for it in p["items"]:
            st = "approved" if it["approved"] else "draft"
            lines.append(f"- {it['id'].split('-')[0]} {it['format']} [{st}, {it.get('attempts')} tries]: {it['topic']}")
            if not it["approved"]:
                lines.append(f"    held back: {'; '.join((it.get('reasons') or [])[:3])}")
        lines.append(f"Model calls: {p.get('llm_calls')}")
    else:
        lines.append("No production run found for today.")
    q = [e for e in publisher.load() if e["date"] == today]
    if q:
        lines.append("Publishing: " + ", ".join(f"{e['id'].split('-')[0]}={e['status']}" for e in q))
        errs = [x for e in q for x in e.get("log", []) if "error" in x]
        if errs:
            lines.append("Errors: " + " | ".join(errs[-3:]))
    hl, acc = insights.highlights(perf)
    if acc:
        lines.append(f"Account: {acc.get('followers_count')} followers, {acc.get('media_count')} posts")
    if hl:
        lines.append("Recent performance:")
        lines += ["- " + h for h in hl]
    lines.append("Next cycle uses: data/learnings.md" + (" (still collecting data)" if "Only" in learn else ""))
    telegram.send_text("\n".join(lines))


def refresh_token():
    import instagram
    token, expires = instagram.refresh_token()
    with open(os.environ.get("NEW_TOKEN_FILE", "new_token.txt"), "w") as f:
        f.write(token)
    print(f"Token refreshed; valid for {int(expires or 0) // 86400} days.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "produce":
        produce()
    elif cmd == "pilot":
        pilot(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    elif cmd == "publish-due":
        publish_due()
    elif cmd == "engage":
        import engage
        engage.run()
    elif cmd == "insights":
        daily_report()
    elif cmd == "refresh-token":
        refresh_token()
    else:
        print(__doc__)
        sys.exit(1)
