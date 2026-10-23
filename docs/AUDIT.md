# Audit of v1 (22–23 Oct 2026)

Account state at audit: **0 posts, 0 followers** (checked through the Instagram API), so no live posts or Insights existed to review.
Reviewed instead: the pipeline code, 3 dry runs, and the real 23 Oct carousel and Reel ("Tasket++ Windows automation").

## Root causes (in order of impact)

| # | Problem | Evidence | Root cause in v1 |
|---|---|---|---|
| 1 | **Weak topic choice** | Topic was one self-promotional Reddit post about a niche Windows macro tool, with one source and no verification | One LLM call picks a topic from headline titles and 220-character summaries. No scoring, no evidence check |
| 2 | **Generic writing** | "Stop wasting hours…", "boring tasks", "saving you time and preventing manual errors", "essentially acting as an extra set of hands" | The prompt asks for "plain English" but has no voice rules, no banned-phrase list, no hook alternatives and no examples |
| 3 | **No depth** | Never says how to install it, when macro tools break, or what to try first | The writer only sees the headline, not the article. "Use only facts from headlines" makes the content thin |
| 4 | **One template for everything** | Every slide is a number, a title and a paragraph card; the last slide is "Follow for daily AI tips" | A single layout and no format library |
| 5 | **Visuals unrelated to the topic** | Stock photo of an iMac on a desk for a Windows tool | Random Pixabay keyword search. No screenshots of the real product |
| 6 | **Reel = slideshow read aloud** | 75 s, a static slide every ~8 s, one voice reading paragraphs, no subtitles | The Reel was built by re-using the carousel images |
| 7 | **No quality gate** | Anything generated could be published | No critic, no fact check, no visual inspection, no retry/reject |
| 8 | **Weak duplicate control** | Only the topic strings from the last 30 days were passed to the prompt | No history database of hooks, formats or keywords |
| 9 | **No learning** | Nothing measured after posting | No Insights collection |
| 10 | **Generic hashtags** | #DigitalIndia #StartupIndia #ProductivityHacks ×10 | Hard rule of exactly 10 hashtags; captions not written for keyword search |

## Constraints found during the audit
- Gemini API on this key (free tier): text works but is often overloaded (503) → needs retries and fallbacks.
  **TTS works free** (natural voice). **Image generation, Google Search grounding and Veo video are not free** (429 or paid only).
- A Google AI Pro subscription covers the Gemini app and Flow, not API calls.
- The Instagram API works with this token: publishing, media insights and account insights.
- Other creators' Instagram posts cannot be read by API with this login type. Reddit, Hacker News and RSS are used for audience research instead.
- GitHub Actions minutes are unlimited for this public repo.
