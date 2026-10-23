"""Daily production: research → select → write → render → quality gate → queue (or draft)."""
import datetime as dt
import json
import os

import carousel
import config
import history
import llm
import qc
import reel
import research
import sources
import visuals
import writer

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist():
    return dt.datetime.now(IST)


def chosen_hook(piece):
    h = piece.get("hooks", [])
    i = piece.get("chosen_hook", 0)
    return h[i] if h and 0 <= i < len(h) else (h[0] if h else "")


def final_caption(piece, ai_visuals):
    import re
    cap = piece["caption"].strip()
    # the writer sometimes puts hashtags inside the caption too; keep only the clean set at the end
    cap = re.sub(r"(\s*#[A-Za-z0-9_]+)+\s*$", "", cap).strip()
    if ai_visuals:
        cap += "\n\n(Some visuals in this post are AI-generated.)"
    return cap + "\n\n" + " ".join(qc.clean_tags(piece.get("hashtags", [])))


def make_one(kind, idea, items, folder, recent_hooks):
    """Up to MAX_ATTEMPTS write→render→review cycles. Returns a result dict (approved or draft)."""
    material = writer.material(items, idea["source_ids"])
    urls = [items[i]["link"] for i in idea["source_ids"]]
    feedback, log = "", []
    best = None
    for attempt in range(1, config.MAX_ATTEMPTS + 1):
        try:
            piece = (writer.write_reel if kind == "reel" else writer.write_carousel)(
                idea, items, recent_hooks, feedback)
        except Exception as ex:
            log.append(f"attempt {attempt}: writer failed ({ex})")
            break
        piece["hashtags"] = qc.clean_tags(piece.get("hashtags", []))
        rules = qc.rule_checks(piece, kind, urls, len(items))
        if len(rules) >= 2:                    # cheap reject: rewrite before spending a render + review
            log.append(f"attempt {attempt}: rules failed: {rules}")
            print("   " + log[-1])
            feedback = qc.feedback_text(rules, None)
            continue
        adir = os.path.join(folder, f"try{attempt}")
        meta = {}
        try:
            if kind == "reel":
                meta = reel.build(piece, os.path.join(adir, "reel.mp4"), preview_dir=adir)
                images = meta["scene_previews"]
            else:
                shot = None
                for u in urls:
                    if not config.is_news(u):          # only real product pages, never article/news pages
                        shot = visuals.screenshot(u)
                        if shot is not None:
                            break
                images = carousel.render(piece, adir, idea["format"], shot)
                meta = {"ai_visuals": False, "slides": len(images)}
        except Exception as ex:
            log.append(f"attempt {attempt}: render failed ({ex})")
            feedback = f"The previous draft could not be rendered ({ex}). Simplify visuals."
            continue
        try:
            rev = qc.review(piece, kind, material, images)
        except Exception as ex:
            log.append(f"attempt {attempt}: review unavailable ({ex})")
            break
        ok, reasons = qc.verdict(rules, rev, meta if kind == "reel" else None)
        res = {"kind": kind, "idea": idea, "piece": piece, "review": rev, "rules": rules, "reasons": reasons,
               "meta": meta, "dir": adir, "attempt": attempt, "approved": ok,
               "hook": chosen_hook(piece), "images": images}
        log.append(f"attempt {attempt}: {'PASS' if ok else 'fail'} {rev['scores']} {reasons[:4]}")
        print("   " + log[-1])
        for v in rev.get("visual_issues", [])[:3]:
            print("      visual:", v)
        if best is None or sum(rev["scores"].values()) > sum(best["review"]["scores"].values()):
            best = res
        if ok:
            best = res
            break
        feedback = qc.feedback_text(rules, rev)
    if best is None:
        return {"kind": kind, "idea": idea, "approved": False,
                "reasons": ["no usable draft: " + (log[-1] if log else "writer unavailable")], "log": log}
    best["log"] = log
    return best


def produce(n_reels, n_cars, pilot=False):
    date = now_ist().strftime("%Y-%m-%d")
    tag = ("pilot-" + now_ist().strftime("%Y%m%d-%H%M")) if pilot else date
    base = os.path.join(config.OUT, tag)
    items = sources.fetch_all()
    ideas = research.candidates(items, research.learnings_text())
    reels, cars, rejected = research.select(ideas, n_reels, n_cars)
    for idea in reels + cars:
        for i in idea["source_ids"]:
            if "text" not in items[i]:
                items[i]["text"] = sources.article_text(items[i]["link"]) or items[i]["summary"]
    recent_hooks = "\n".join(f"- {h.get('hook')}" for h in history.recent(30)[-40:])
    results = []
    for kind, group in (("reel", reels), ("carousel", cars)):
        for n, idea in enumerate(group, 1):
            iid = f"{'R' if kind == 'reel' else 'C'}{n}-{tag}"
            folder = os.path.join(base, iid)
            os.makedirs(folder, exist_ok=True)
            print(f"\n=== {iid}: {idea['format']} — {idea['idea']}")
            r = make_one(kind, idea, items, folder, recent_hooks)
            r["id"] = iid
            r["caption_final"] = final_caption(r["piece"], r.get("meta", {}).get("ai_visuals")) if r.get("piece") else ""
            recent_hooks += f"\n- {r.get('hook', '')}"
            results.append(r)
            with open(os.path.join(folder, "item.json"), "w", encoding="utf-8") as f:
                json.dump({k: v for k, v in r.items() if k not in ("images",)}, f, indent=1, ensure_ascii=False,
                          default=str)
    summary = {"date": date, "tag": tag, "pilot": pilot, "sources": len(items), "ideas": len(ideas),
               "idea_list": [{"idea": i["idea"], "format": i["format"], "total": i["total"], "scores": i["scores"]}
                             for i in ideas],
               "rejected_ideas": rejected,
               "items": [{"id": r["id"], "kind": r["kind"], "format": r["idea"]["format"], "topic": r["idea"]["idea"],
                          "hook": r.get("hook"), "approved": r["approved"], "attempts": r.get("attempt"),
                          "scores": r.get("review", {}).get("scores"), "reasons": r.get("reasons"),
                          "log": r.get("log"), "dir": os.path.relpath(r["dir"], config.ROOT) if r.get("dir") else None,
                          "duration": r.get("meta", {}).get("duration"), "voice": r.get("meta", {}).get("voice")}
                         for r in results],
               "llm_calls": dict(llm.CALLS)}
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "production.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1, ensure_ascii=False)
    return results, summary
