"""Real visual assets: live page screenshots (Playwright), Pixabay photos, optional approved library images."""
import io
import json
import os
from urllib.parse import urlparse

import requests
from PIL import Image

import config

HIDE_CSS = """
[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[class*=gdpr i],[id*=onetrust i],
[class*=newsletter i],[class*=popup i],[class*=modal i],[aria-modal=true],[class*=banner i][class*=cookie i]
{display:none !important;} body{overflow:auto !important;}
"""
_cache = {}


def domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def screenshot(url, width=430, height=1100, scale=2.5):
    """Mobile-view screenshot of a real page. Returns PIL image or None."""
    if not url or not url.startswith("http"):
        return None
    if url in _cache:
        return _cache[url]
    img = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale,
                                is_mobile=True, has_touch=True, locale="en-IN",
                                user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                                           "(KHTML, like Gecko) Chrome/130 Mobile Safari/537.36")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            page.add_style_tag(content=HIDE_CSS)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            png = page.screenshot(full_page=False)
            b.close()
        img = Image.open(io.BytesIO(png)).convert("RGB")
        # reject near-blank pages (blocked, captcha, error)
        small = img.resize((40, 100)).convert("L")
        px = list(small.getdata())
        mean = sum(px) / len(px)
        var = sum((v - mean) ** 2 for v in px) / len(px)
        if var < 60:
            print(f"[visuals] screenshot looks blank, skipped: {url}")
            img = None
    except Exception as ex:
        print(f"[visuals] screenshot failed {url}: {ex}")
    _cache[url] = img
    return img


def pixabay(query):
    key = (os.environ.get("PIXABAY_API_KEY") or "").strip()
    if not key or not query:
        return None
    try:
        r = requests.get("https://pixabay.com/api/", params={"key": key, "q": query, "image_type": "photo",
                                                            "safesearch": "true", "per_page": 5}, timeout=30)
        if r.status_code != 200 or not r.text.startswith("{"):
            print(f"[visuals] pixabay HTTP {r.status_code}: {r.text[:100]} (key length {len(key)})")
            return None
        hits = r.json().get("hits", [])
        if not hits:
            return None
        return Image.open(io.BytesIO(requests.get(hits[0]["largeImageURL"], timeout=60).content)).convert("RGB")
    except Exception as ex:
        print("[visuals] pixabay failed:", ex)
        return None


def library(query):
    """Approved images in assets/library with an index.json of {file: [tags]}. Returns (image, is_ai) or (None, False)."""
    idx = os.path.join(config.LIBRARY, "index.json")
    if not query or not os.path.exists(idx):
        return None, False
    with open(idx, encoding="utf-8") as f:
        index = json.load(f)
    q = set(query.lower().split())
    best, score = None, 0
    for fname, meta in index.items():
        s = len(q & set(t.lower() for t in meta.get("tags", [])))
        if s > score:
            best, score = (fname, meta), s
    if not best:
        return None, False
    try:
        return Image.open(os.path.join(config.LIBRARY, best[0])).convert("RGB"), bool(best[1].get("ai", True))
    except Exception:
        return None, False


def photo(query):
    """Library first (approved), then Pixabay. Returns (image, is_ai_generated)."""
    img, ai = library(query)
    if img is not None:
        return img, ai
    return pixabay(query), False
