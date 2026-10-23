# Visual identity & writing rules (v2)

## Brand
- **Look:** a calm editorial notebook, not a "glowing AI" aesthetic. Restrained palette, generous margins, one accent.
- **Palette:** cream `#F6F3EC` (carousel background), ink `#13213C` (text), deep ink `#0D1628` (Reel background),
  saffron `#E8862A` (accent only: underlines, numbers, progress bar), muted `#6B7280`, green `#228B5E` (✓), red `#C44536` (✗).
- **Type:** Inter (Bold for headlines, Medium/Regular for body). Poppins Bold only for the big quote mark.
- **Mark:** a saffron rounded square with an "A" and an underline, beside `@automatei_q` at the top left of every asset.
- **Carousel (1080×1350):** progress bar at the bottom, slide counter top right, content vertically centred.
  8 slide kinds: cover, point, steps, checklist, compare, myth/fact, quote, summary. The last slide is always useful.
- **Reel (1080×1920):** headline at the top, a visual panel in the middle (inside the safe area), subtitles at about 75% height,
  nothing in the bottom 330 px or the right edge (Instagram UI). Hard cuts; motion comes from slow scrolls and zooms and
  from items appearing one by one, not from transitions.

## Visual hierarchy of sources (most → least preferred)
1. **Real interface screenshots** of the product or article page in the sources (captured live by Playwright, phone view).
2. **Clean diagrams, tables and checklists** generated from the script (always accurate, never "AI-looking").
3. **Approved library images** (`assets/library/`, see below).
4. **Real stock photos** (Pixabay), only when they show the actual situation.
Never: fake product UIs, glowing robot brains, random futuristic graphics, or synthetic people presented as customers.

## Optional image library (uses your Google AI Pro plan, no API cost)
Make 20–40 realistic **scene** images by hand in the Gemini app, e.g. "candid phone photo, hardware shop counter in
Nagpur, ledger and phone on the counter, natural daylight, no people's faces". Then put them in `assets/library/`
with an `index.json` like:
```json
{"shop_counter_1.jpg": {"tags": ["shop", "counter", "ledger", "retail"], "ai": true}}
```
Any post that uses an `"ai": true` image gets the line "(Some visuals in this post are AI-generated.)" in its caption automatically.

## Character bible (for a future AI presenter; NOT active)
Activate only with a paid image and video API (Veo or Nano Banana billing), and with Instagram's
**"AI-generated profile"** label switched on (required since 31 Aug 2026 for accounts featuring AI-generated people).
- **Name/role:** "Arjun" — a 29-year-old operations consultant who has helped family businesses digitise. Clearly fictional. Never presented as a real person, customer or expert witness.
- **Face:** oval face, short black hair with a side part, light stubble, medium-brown skin with natural texture
  (pores, slight unevenness), small scar above the left eyebrow, brown eyes, thin black rectangular glasses.
- **Build/wardrobe:** average build; plain cotton shirts (navy, olive, white) with sleeves rolled once;
  a steel watch on the left wrist; no logos.
- **Locations:** a small office with a steel almirah and files, a shop counter, a site office with drawings on the wall, a balcony in daylight.
- **Camera:** handheld phone look, 26–35 mm equivalent, eye level, natural window light, mild background clutter,
  shallow depth only from distance (no heavy bokeh), small framing changes between scenes.
- **Expression/body:** relaxed, half-smile, explains with one hand, glances at the phone or laptop. No exaggerated
  surprise faces or pointing at the camera.
- **Voice:** calm Indian English, medium pace, slight warmth (Gemini voice "Charon" + the style prompt in `src/config.py`).
- **Consistency rules:** always generate from the same 3 approved reference portraits, keep the glasses and watch,
  vary only location and pose. Reject any image with changed facial structure, extra fingers, warped text or a
  "plastic" skin look.

## Writing rules
See `prompts/writing_rules.md`. That file is loaded into every writing prompt, and its banned-phrase list is also
checked in code (`src/config.py` → `BANNED`).
