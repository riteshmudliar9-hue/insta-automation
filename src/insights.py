"""Performance feedback loop: collect Insights, compare to the account's own baseline, write learnings."""
import datetime as dt
import json
import os
import statistics

import config
import history
import instagram

PERF = os.path.join(config.DATA, "performance.json")
LEARN = os.path.join(config.DATA, "learnings.md")
MIN_POSTS = 8  # don't draw conclusions before this many published items


def load():
    if os.path.exists(PERF):
        with open(PERF, encoding="utf-8") as f:
            return json.load(f)
    return {"media": {}, "account": []}


def collect():
    perf = load()
    try:
        info = instagram.account_info()
        perf["account"].append({"date": dt.date.today().isoformat(), **info})
    except Exception as ex:
        print("[insights] account info failed:", ex)
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    for h in history.load():
        if h.get("status") != "published" or not h.get("media_id") or h.get("date", "") < cutoff:
            continue
        try:
            m = instagram.media_insights(h["media_id"], h["kind"] == "reel")
        except Exception as ex:
            print("[insights]", h["id"], ex)
            continue
        perf["media"][h["media_id"]] = {"id": h["id"], "kind": h["kind"], "format": h["format"], "hook": h["hook"],
                                        "topic": h["topic"], "date": h["date"], "metrics": m,
                                        "fetched": dt.datetime.utcnow().isoformat()}
    with open(PERF, "w", encoding="utf-8") as f:
        json.dump(perf, f, indent=1, ensure_ascii=False)
    return perf


def _rate(m, key):
    reach = m.get("reach") or 0
    return (m.get(key) or 0) / reach if reach else 0


def score(m, kind):
    """Account-objective score: shares and saves per reach weigh most; watch time for reels."""
    s = 3 * _rate(m, "shares") + 2 * _rate(m, "saved") + _rate(m, "comments") + 0.5 * _rate(m, "likes")
    if kind == "reel" and m.get("ig_reels_avg_watch_time"):
        s += min(m["ig_reels_avg_watch_time"] / 1000 / 30, 1) * 0.05
    return s


def learn(perf):
    rows = list(perf["media"].values())
    lines = [f"# Learnings (auto-generated {dt.date.today().isoformat()})", ""]
    if len(rows) < MIN_POSTS:
        lines.append(f"Only {len(rows)} published items with data; need {MIN_POSTS}+ before drawing conclusions. "
                     "Keep varying formats.")
    else:
        for kind in ("reel", "carousel"):
            ks = [r for r in rows if r["kind"] == kind and r["metrics"].get("reach")]
            if len(ks) < 3:
                continue
            base = statistics.median(score(r["metrics"], kind) for r in ks) or 1e-9
            reach_med = statistics.median(r["metrics"]["reach"] for r in ks)
            lines.append(f"## {kind}s (n={len(ks)}, median reach {reach_med:.0f})")
            by_fmt = {}
            for r in ks:
                by_fmt.setdefault(r["format"], []).append(score(r["metrics"], kind) / base)
            for f, v in sorted(by_fmt.items(), key=lambda x: -statistics.mean(x[1])):
                lines.append(f"- format {f}: {statistics.mean(v):.2f}x account median (n={len(v)})")
            top = sorted(ks, key=lambda r: -score(r["metrics"], kind))[:3]
            low = sorted(ks, key=lambda r: score(r["metrics"], kind))[:2]
            lines.append("- best hooks: " + " | ".join(r["hook"] for r in top))
            lines.append("- weakest hooks: " + " | ".join(r["hook"] for r in low))
            if kind == "reel":
                wt = [r["metrics"].get("ig_reels_avg_watch_time") for r in ks if r["metrics"].get("ig_reels_avg_watch_time")]
                if wt:
                    lines.append(f"- median avg watch time: {statistics.median(wt) / 1000:.1f}s")
            lines.append("")
    with open(LEARN, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return "\n".join(lines)


def highlights(perf):
    rows = sorted(perf["media"].values(), key=lambda r: r["date"], reverse=True)[:6]
    out = []
    for r in rows:
        m = r["metrics"]
        out.append(f"{r['id'].split('-')[0]} {r['date']} {r['format']}: reach {m.get('reach', '-')}, "
                   f"shares {m.get('shares', '-')}, saves {m.get('saved', '-')}, likes {m.get('likes', '-')}"
                   + (f", avg watch {m['ig_reels_avg_watch_time'] / 1000:.1f}s" if m.get('ig_reels_avg_watch_time') else ""))
    acc = perf["account"][-1] if perf["account"] else {}
    return out, acc
