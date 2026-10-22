"""Fetch AI/automation headlines from RSS feeds and Reddit."""
import time
import feedparser
import requests

UA = "Mozilla/5.0 (insta-automation bot; +https://github.com)"

RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Hacker News": "https://hnrss.org/frontpage?points=100",
}
SUBREDDITS = ["automation", "smallbusiness", "ChatGPT"]


def _clean(text, n=300):
    import re
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:n]


def fetch_rss(per_feed=12):
    items = []
    for name, url in RSS_FEEDS.items():
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            feed = feedparser.parse(resp.content)
            for e in feed.entries[:per_feed]:
                items.append({
                    "source": name,
                    "title": _clean(e.get("title"), 200),
                    "summary": _clean(e.get("summary") or e.get("description")),
                    "link": e.get("link", ""),
                })
        except Exception as ex:
            print(f"[rss] {name} failed: {ex}")
    return items


def fetch_reddit(per_sub=10):
    items = []
    for sub in SUBREDDITS:
        got = False
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top.json?t=day&limit={per_sub}",
                             headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200:
                for c in r.json()["data"]["children"]:
                    d = c["data"]
                    if d.get("stickied"):
                        continue
                    items.append({
                        "source": f"r/{sub}",
                        "title": _clean(d.get("title"), 200),
                        "summary": _clean(d.get("selftext")),
                        "link": "https://www.reddit.com" + d.get("permalink", ""),
                    })
                got = True
            else:
                print(f"[reddit] r/{sub} json HTTP {r.status_code}, trying RSS")
        except Exception as ex:
            print(f"[reddit] r/{sub} json failed: {ex}")
        if not got:  # Reddit often blocks cloud IPs for JSON; RSS is a fallback
            try:
                r = requests.get(f"https://www.reddit.com/r/{sub}/top/.rss?t=day",
                                 headers={"User-Agent": UA}, timeout=20)
                feed = feedparser.parse(r.content)
                for e in feed.entries[:per_sub]:
                    items.append({"source": f"r/{sub}", "title": _clean(e.get("title"), 200),
                                  "summary": _clean(e.get("summary")), "link": e.get("link", "")})
            except Exception as ex:
                print(f"[reddit] r/{sub} rss failed: {ex}")
        time.sleep(1)
    return items


def fetch_all():
    items = fetch_rss() + fetch_reddit()
    seen, out = set(), []
    for it in items:
        key = it["title"].lower()
        if it["title"] and key not in seen:
            seen.add(key)
            out.append(it)
    print(f"[sources] {len(out)} headlines")
    return out
