# v2 architecture

```
                 05:30 IST  workflow "1 - Produce"                         every 30 min "2 - Publish due"
 ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐   ┌───────────────────────┐
 │A Research    │→│B Select      │→│C Write       │→│D/E Render     │   │G Publisher             │
 │sources.py    │  │research.py   │  │writer.py     │  │carousel.py    │   │publisher.py            │
 │9 RSS feeds + │  │14 ideas,     │  │3 hooks→pick, │  │reel.py        │   │slots, 'stop' veto,     │
 │7 subreddits, │  │7 scores,     │  │full script,  │  │visuals.py     │   │duplicate guard,        │
 │audience Qs,  │  │dedupe vs     │  │claims+source │  │(screenshots,  │   │retry log → Instagram   │
 │full articles │  │history       │  │ids           │  │diagrams, TTS) │   └───────────┬───────────┘
 └──────────────┘  └──────────────┘  └──────────────┘  └───────┬───────┘               │
        ▲                                                       ▼                       ▼
        │                                              ┌───────────────┐   ┌───────────────────────┐
        │                                              │F Quality gate │   │H Insights (23:00 IST)  │
        │                                              │qc.py: rules + │   │insights.py: per-post   │
        │                                              │model review of│   │metrics vs own baseline │
        │                                              │text & images, │   └───────────┬───────────┘
        │                                              │claims check;  │               ▼
        │                                              │≤3 tries, else │   ┌───────────────────────┐
        └──────────── data/learnings.md ◄──────────────│draft          │   │I Learnings + report    │
                                                       └───────────────┘   │learnings.md, Telegram  │
                                                                           └───────────────────────┘
```

## Data (all in the repo)
| File | Purpose |
|---|---|
| `data/history.json` | Every produced or published item: topic, hook, format, keywords, status, media id. Used for duplicate detection |
| `data/queue.json` | Approved items with their slot, status (queued/published/stopped/failed/expired) and a retry log |
| `data/performance.json` | Insights per media + daily follower count |
| `data/learnings.md` | Auto-written findings, fed back into research |
| `data/control.json` | Master switch for production and publishing (`publishing_enabled`) |
| `output/<date>/<id>/tryN/` | Rendered assets for each attempt + `item.json` (script, scores, reasons) |
| `output/<date>/production.json` | The day's ideas, scores, rejections, results and model-call counts |
| `prompts/*.md` | Writing rules and the format library (editable without touching code) |

## Quality gate (src/qc.py)
1. **Code checks:** banned phrases, hook length, scene/slide counts, words per scene or slide, 3–5 hashtags, caption length,
   screenshot URLs must come from the sources, claims must cite a valid source, last carousel slide must be useful,
   similarity to the last 60 days of content.
2. **Model review (Gemini, multimodal):** sees the script, the source text and the **rendered images** (every carousel
   slide; one frame per Reel scene). Scores 10 categories, verifies each claim against the sources, lists
   spelling and visual problems.
3. **Pass rule:** hook, originality, practical value, natural language, accuracy, narrative and visual integrity must each be ≥ 8;
   pacing, brand and readiness ≥ 7; zero unsupported claims; zero spelling errors; at most 1 Reel scene that lost its real visual.
4. **Fail:** the review becomes feedback, and the piece is rewritten and re-rendered (up to 3 tries). After that it's a **draft**:
   saved, sent to Telegram with the reasons, never published.

"Visual inspection" means an automated vision-model review of the actual rendered frames. No human checks a piece
unless you look at the Telegram preview.
