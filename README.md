# @automatei_q — Automated Instagram Carousels & Reels

This repo posts one daily carousel **and a Reel** for **"AI & Automation for Real-World Businesses"**, written for Indian small business owners, contractors and traders. It runs for free on GitHub Actions.

## How a day works

| Time (IST) | What happens |
|---|---|
| 7:00 AM | Fetches headlines from TechCrunch AI, The Verge AI, Hacker News, r/automation, r/smallbusiness and r/ChatGPT. Gemini picks the most useful topic, skipping anything covered in the last 30 days, and writes the hook, 5–7 slides, the caption and 10 hashtags, using only facts from the headlines. Pillow draws the 1080×1350 slides. The same slides become a 1080×1920 Reel with an Indian English male voiceover. The carousel and Reel previews go to you on Telegram. |
| before 9:00 AM | Reply on Telegram: **yes** = both, **carousel** = carousel only, **reel** = Reel only. No reply means skip. |
| 9:00 AM | If you said yes, the carousel is posted with the Instagram API (child containers → carousel container → publish). |
| 6:00 PM | If approved, the Reel is posted (video served from GitHub Pages). |
| always | Every day is logged in `data/posts.csv` (date, topic, carousel + Reel status and links, sources). |
| every Sunday | The Instagram token is refreshed, so it never hits its 60-day expiry. |

If any step fails, the bot sends you a Telegram message with a link to the logs.

## Folders

```
src/main.py        entry point (prepare / publish / publish-reel / refresh-token)
src/sources.py     RSS + Reddit headlines
src/ai.py          Gemini prompt, JSON schema, rule checks
src/render.py      carousel design (brand colours, logo, layout)
src/reel.py        Reel video (voiceover + ffmpeg)
src/telegram.py    preview + approval
src/instagram.py   publishing + token refresh
output/YYYY-MM-DD/ the day's slides (public URLs used by Instagram)
data/posts.csv     post log
```

## GitHub Secrets (Settings → Secrets and variables → Actions)

`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `IG_ACCESS_TOKEN`, `IG_USER_ID`, `GH_PAT`

`GH_PAT` is a fine-grained GitHub token limited to this repo with **Secrets: Read and write**. The weekly job uses it to save the refreshed Instagram token.

## Switches

- **Dry run:** go to Actions → *0 - Dry run* → Run workflow. It sends a preview to Telegram and never posts.
- **Turn daily posting on:** Settings → Secrets and variables → Actions → **Variables** → add `POSTING_ENABLED` = `true`.
- **Pause:** change that variable to `false`.
- **Post right now:** Actions → *1 - Prepare* → Run workflow. Reply yes, then run *2 - Publish* (and *4 - Publish Reel*).

## Notes

- GitHub Pages must stay **on** (Settings → Pages → Deploy from branch `main`, folder `/root`). Instagram downloads the Reel video from there.
- Output folders older than 10 days are deleted automatically, to keep the repo small.
- The repo must stay **public**, because Instagram downloads the slide images from their GitHub URLs. No keys are ever stored in the code.
- GitHub can start scheduled jobs 5–30 minutes late at busy times.
- To change the Reel voice, edit `VOICE` at the top of `src/reel.py` (e.g. `en-IN-NeerjaNeural` for a female voice).
- To change the colours, handle or logo, edit the constants at the top of `src/render.py`.
- Fonts: Poppins (SIL Open Font License).
