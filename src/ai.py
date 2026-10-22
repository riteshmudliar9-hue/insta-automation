"""Ask Gemini to pick a topic and write the carousel as JSON."""
import json
import os
import time
import requests

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topic": {"type": "STRING"},
        "headline_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "hook": {"type": "STRING"},
        "slides": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {"title": {"type": "STRING"}, "text": {"type": "STRING"}},
            "required": ["title", "text"]}},
        "caption": {"type": "STRING"},
        "hashtags": {"type": "ARRAY", "items": {"type": "STRING"}},
        "image_query": {"type": "STRING"},
    },
    "required": ["topic", "headline_ids", "hook", "slides", "caption", "hashtags", "image_query"],
}

PROMPT = """You run the Instagram page @automatei_q: "AI & Automation for Real-World Businesses".
Audience: Indian small business owners, contractors and traders (shops, workshops, civil/electrical
contractors, distributors). They are busy, practical, not technical. Plain simple English.

TODAY'S HEADLINES (id | source | title | summary):
{headlines}

TOPICS ALREADY COVERED IN THE LAST 30 DAYS (do NOT repeat these or close variants):
{history}

TASK: Pick the ONE headline/topic that is most useful and actionable for this audience, then write
an Instagram carousel about it.

STRICT RULES:
- Use ONLY facts stated in the headlines/summaries above. Never invent tool prices, plans, features,
  statistics, dates or company claims. If a detail is not in the headlines, do not state it.
  You may add general, non-factual practical advice (e.g. "start with one repetitive task").
- hook: a scroll-stopping cover line, max 12 words.
- slides: 5 to 7 slides. Each slide has a short title (max 6 words) and text; title + text together
  MAX 25 words. Explain what happened, why it matters to an Indian small business, and 1-3 practical
  ways to use it. No emojis on slides.
- caption: 120 to 180 words, conversational, relevant to Indian businesses, MUST end with a question
  to the reader. Do not put hashtags inside the caption.
- hashtags: exactly 10 niche hashtags (each starting with #), mix of AI/automation and Indian
  small-business tags. No spaces inside a hashtag.
- image_query: 2-3 generic English words for a stock photo (e.g. "office laptop", "warehouse").
- headline_ids: ids of the headlines you used.
- topic: a short 4-10 word label for this post (used to avoid repeats).
{feedback}"""


def _words(s):
    return len(s.split())


def validate(p):
    errs = []
    n = len(p.get("slides", []))
    if not 5 <= n <= 7:
        errs.append(f"slides must be 5-7, got {n}")
    for i, s in enumerate(p.get("slides", []), 1):
        w = _words(s["title"]) + _words(s["text"])
        if w > 25:
            errs.append(f"slide {i} has {w} words (max 25 incl. title)")
    cw = _words(p.get("caption", ""))
    if not 120 <= cw <= 180:
        errs.append(f"caption has {cw} words, need 120-180")
    if not p.get("caption", "").rstrip().endswith("?"):
        errs.append("caption must end with a question mark")
    if len(p.get("hashtags", [])) != 10:
        errs.append(f"need exactly 10 hashtags, got {len(p.get('hashtags', []))}")
    if _words(p.get("hook", "")) > 12:
        errs.append("hook longer than 12 words")
    return errs


def _call(prompt, api_key):
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "temperature": 0.7},
    }
    for attempt in range(4):
        r = requests.post(URL, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                          json=body, timeout=120)
        if r.status_code in (429, 500, 503):
            wait = 20 * (attempt + 1)
            print(f"[gemini] HTTP {r.status_code}, retrying in {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    raise RuntimeError("Gemini unavailable after retries")


def generate_post(headlines, history_topics, api_key):
    listing = "\n".join(
        f"{i} | {h['source']} | {h['title']} | {h['summary'][:220]}" for i, h in enumerate(headlines[:60]))
    history = "\n".join(f"- {t}" for t in history_topics) or "- (none)"
    feedback = ""
    post = None
    for attempt in range(3):
        post = _call(PROMPT.format(headlines=listing, history=history, feedback=feedback), api_key)
        errs = validate(post)
        if not errs:
            break
        print(f"[gemini] attempt {attempt + 1} problems: {errs}")
        feedback = "\nYOUR PREVIOUS ANSWER BROKE THESE RULES, FIX THEM:\n- " + "\n- ".join(errs)
    # last-resort tidy-ups so a minor miss never blocks the day
    post["slides"] = post["slides"][:7]
    post["hashtags"] = ["#" + h.lstrip("#").replace(" ", "") for h in post["hashtags"]][:10]
    post["sources"] = [headlines[i] for i in post.get("headline_ids", []) if 0 <= i < len(headlines)]
    return post
