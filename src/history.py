"""Content history database (data/history.json): duplicate detection across topics, hooks and angles."""
import datetime as dt
import json
import os
import re

import config

PATH = os.path.join(config.DATA, "history.json")
STOP = set("""a an the and or but to of in on for with at by from is are was were be been it its this that these
those you your we our they their i my me as how what why when which who can will just not no more most very into
about over than then so if do does did use using new now get got make makes made one two three ai""".split())


def load():
    if not os.path.exists(PATH):
        return []
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def save(items):
    os.makedirs(config.DATA, exist_ok=True)
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)


def words(text):
    return {w for w in re.findall(r"[a-z0-9+#]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def similarity(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def recent(days=60):
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    return [h for h in load() if h.get("date", "") >= cutoff]


def most_similar(text, days=60, extra=None):
    """(score, item) of the closest past/planned item."""
    w = words(text)
    best = (0.0, None)
    for h in recent(days) + (extra or []):
        s = similarity(w, words(" ".join([h.get("topic", ""), h.get("hook", ""), " ".join(h.get("keywords", []))])))
        if s > best[0]:
            best = (s, h)
    return best


def summary_for_prompt(days=45, limit=60):
    rows = recent(days)[-limit:]
    return "\n".join(f"- [{h.get('format')}] {h.get('topic')} | hook: {h.get('hook')}" for h in rows) or "- (none yet)"


def add(item):
    items = load()
    items = [h for h in items if h.get("id") != item.get("id")]
    items.append(item)
    save(items)


def update(item_id, **fields):
    items = load()
    for h in items:
        if h.get("id") == item_id:
            h.update(fields)
    save(items)
