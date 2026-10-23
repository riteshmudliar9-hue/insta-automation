"""Research inputs: news + practitioner discussions + real audience questions, and full article text."""
import html
import re
import time

import feedparser
import requests

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"

RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Hacker News": "https://hnrss.org/frontpage?points=100",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "OpenAI News": "https://openai.com/news/rss.xml",
    "MIT Tech Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Zapier Blog": "https://zapier.com/blog/feeds/latest/",
    "Inc42": "https://inc42.com/feed/",
    "YourStory": "https://yourstory.com/feed",
}
SUBREDDITS = ["automation", "smallbusiness", "ChatGPT", "Entrepreneur", "nocode", "StartUpIndia", "indianstartups"]
QUESTION = re.compile(r"(\?\s*$)|^(how|what|which|is there|any|anyone|should|can i|best way)\b", re.I)


def clean(text, n=400):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:n]


def _feed(url):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    return feedparser.parse(r.content)


def fetch_all(per_feed=10, per_sub=12):
    items = []
    for name, url in RSS_FEEDS.items():
        try:
            for e in _feed(url).entries[:per_feed]:
                items.append({"source": name, "title": clean(e.get("title"), 200),
                              "summary": clean(e.get("summary") or e.get("description"), 400),
                              "link": e.get("link", ""), "kind": "news"})
        except Exception as ex:
            print(f"[sources] {name}: {ex}")
    for sub in SUBREDDITS:
        try:
            for e in _feed(f"https://www.reddit.com/r/{sub}/top/.rss?t=day").entries[:per_sub]:
                title = clean(e.get("title"), 200)
                items.append({"source": f"r/{sub}", "title": title,
                              "summary": clean(e.get("summary"), 600), "link": e.get("link", ""),
                              "kind": "question" if QUESTION.search(title) else "discussion"})
        except Exception as ex:
            print(f"[sources] r/{sub}: {ex}")
        time.sleep(1)
    seen, out = set(), []
    for it in items:
        k = it["title"].lower()
        if it["title"] and k not in seen:
            seen.add(k)
            out.append(it)
    print(f"[sources] {len(out)} items ({sum(i['kind'] == 'question' for i in out)} audience questions)")
    return out


def article_text(url, limit=7000):
    """Readable text of a page (paragraphs only). Empty string on failure."""
    if not url:
        return ""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        body = re.sub(r"(?is)<(script|style|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", r.text)
        paras = [clean(p, 2000) for p in re.findall(r"(?is)<(?:p|li|h2|h3)[^>]*>(.*?)</(?:p|li|h2|h3)>", body)]
        paras = [p for p in paras if len(p) > 40]
        return "\n".join(paras)[:limit]
    except Exception as ex:
        print(f"[sources] article fetch failed {url}: {ex}")
        return ""
