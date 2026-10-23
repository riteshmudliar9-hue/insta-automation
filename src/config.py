"""Central settings for the v2 content system."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "output")
PROMPTS = os.path.join(ROOT, "prompts")
LIBRARY = os.path.join(ROOT, "assets", "library")  # optional approved images (see docs/VISUAL_IDENTITY.md)

HANDLE = "@automatei_q"
BRAND = "Automate India"  # short name shown on cards

# Daily maximums (targets, not quotas: low-quality items are dropped, never forced through)
MAX_REELS = int(os.environ.get("MAX_REELS", "4"))
MAX_CAROUSELS = int(os.environ.get("MAX_CAROUSELS", "4"))

# Publishing slots (IST, 24h). Items are queued into the earliest free slots by quality score.
CAROUSEL_SLOTS = ["08:30", "12:30", "16:30", "20:30"]
REEL_SLOTS = ["10:00", "14:00", "18:30", "21:30"]

# Quality gate
CRITICAL = ["hook", "originality", "practical_value", "natural_language", "accuracy",
            "narrative", "visual_integrity"]
OTHER = ["pacing", "brand_consistency", "publish_readiness"]
MIN_CRITICAL = 8
MIN_OTHER = 7
MAX_ATTEMPTS = 3          # generate → check → regenerate with feedback; after this it becomes a draft
DUP_THRESHOLD = 0.45      # keyword similarity to any item in the last 60 days that counts as a repeat

# Voice: Gemini TTS first (natural), edge-tts as fallback
GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]
GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Charon")
VOICE_STYLE = ("Read this like a calm, knowledgeable Indian friend explaining something useful over chai. "
               "Natural Indian English accent, conversational pace, slight warmth, no announcer tone. Text: ")
EDGE_VOICE = "en-IN-PrabhatNeural"

TEXT_MODELS = [m for m in [os.environ.get("GEMINI_MODEL")] if m] + [
    "gemini-3.5-flash", "gemini-3.8-flash", "gemini-flash-latest", "gemini-3.1-flash-lite"]

BANNED = ["fast-paced", "digital age", "unlock", "unleash", "revolutioni", "game-changer", "game changer",
          "game-changing", "supercharge", "level up", "elevate", "harness the power", "dive in", "delve",
          "seamless", "cutting-edge", "in conclusion", "let's explore", "are you ready", "look no further",
          "don't forget to", "like, share", "like and share", "boring tasks", "valuable time",
          "next level", "in today's", "ever-evolving", "landscape of", "embark", "tapestry"]


# Never screenshot these (article pages = logos, ads, clutter). Screenshots only for real product/tool pages.
NEWS_DOMAINS = ["techcrunch.com", "theverge.com", "technologyreview.com", "yourstory.com", "inc42.com",
                "news.ycombinator.com", "reddit.com", "hnrss.org", "zapier.com/blog", "blog.google",
                "openai.com/news", "openai.com/index"]


def is_news(url):
    u = (url or "").lower()
    return any(d in u for d in NEWS_DOMAINS)


def prompt_file(name):
    with open(os.path.join(PROMPTS, name), encoding="utf-8") as f:
        return f.read()
