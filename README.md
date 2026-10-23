# @automatei_q — content system v2

Practical AI and automation for Indian small businesses. Researched, written, rendered, quality-checked, published and measured automatically on GitHub Actions. v1 is preserved on the `backup-v1` branch.

## Daily cycle (IST)
| When | Workflow | What happens |
|---|---|---|
| 05:30 | 1 - Produce | Research 9 news feeds + 7 subreddits. Score 14 ideas. Write, render and quality-check up to 4 Reels + 4 carousels. Approved items get slots. Previews and drafts go to Telegram |
| every 30 min, 08:00–22:00 | 2 - Publish due | Posts the next due item of each type (carousels 08:30/12:30/16:30/20:30, Reels 10:00/14:00/18:30/21:30) |
| 23:00 | 3 - Insights + report | Collects Insights, updates `data/learnings.md`, sends the daily report |
| Sunday | Refresh Instagram token | Renews the token |
| manual | 0 - Pilot batch | Makes N Reels + N carousels through the full gate. **Never publishes** |

## Telegram commands
`stop` cancels all of today's queued posts · `stop R2` or `stop C1 R3` cancels specific items · `resume` undoes `stop`.

## Switches
- `data/control.json` → `"publishing_enabled": true/false` is the master switch for production and publishing.
- `MAX_REELS` / `MAX_CAROUSELS` in the produce workflow set the daily maximum (a target, not a quota).
- Change the voice or thresholds in `src/config.py`. Change the writing style in `prompts/writing_rules.md`. Change formats in `prompts/formats.md`.

## Docs
`docs/AUDIT.md` (what was wrong with v1) · `docs/ARCHITECTURE.md` (modules, data, quality gate) · `docs/VISUAL_IDENTITY.md` (brand, library, character bible)

## Secrets
`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GH_PAT`. These are never written to code, logs or output files.
