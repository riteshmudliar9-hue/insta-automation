"""Script and carousel writing (hooks → selection → full piece), grounded in fetched source material."""
import config
import llm

STR = {"type": "STRING"}
ARR = lambda t: {"type": "ARRAY", "items": t}  # noqa: E731
ROW = {"type": "OBJECT", "properties": {"left": STR, "right": STR}, "required": ["left", "right"]}
CLAIM = {"type": "OBJECT", "properties": {"claim": STR, "source_id": {"type": "INTEGER"}},
         "required": ["claim", "source_id"]}

REEL_SCHEMA = {"type": "OBJECT", "properties": {
    "hooks": ARR(STR), "chosen_hook": {"type": "INTEGER"}, "hook_reason": STR, "title": STR,
    "scenes": ARR({"type": "OBJECT", "properties": {
        "purpose": STR, "narration": STR, "on_screen": STR,
        "visual_type": {"type": "STRING", "enum": ["screenshot", "diagram", "compare", "text", "checklist", "photo"]},
        "url": STR, "query": STR, "headline": STR, "steps": ARR(STR), "items": ARR(STR),
        "left_label": STR, "right_label": STR, "rows": ARR(ROW)},
        # every field required: Gemini's structured output silently drops optional fields.
        # Fields a visual does not need are returned as "" or [].
        "required": ["purpose", "narration", "on_screen", "visual_type", "url", "query", "headline", "steps",
                     "items", "left_label", "right_label", "rows"]}),
    "caption": STR, "hashtags": ARR(STR), "keywords": ARR(STR), "claims": ARR(CLAIM),
    "dm_keyword": STR, "dm_text": STR},
    "required": ["hooks", "chosen_hook", "hook_reason", "title", "scenes", "caption", "hashtags", "keywords", "claims",
                 "dm_keyword", "dm_text"]}

CAROUSEL_SCHEMA = {"type": "OBJECT", "properties": {
    "hooks": ARR(STR), "chosen_hook": {"type": "INTEGER"}, "hook_reason": STR,
    "slides": ARR({"type": "OBJECT", "properties": {
        "kind": {"type": "STRING", "enum": ["cover", "point", "steps", "checklist", "compare", "mythfact",
                                            "quote", "summary"]},
        "title": STR, "subtitle": STR, "body": STR, "items": ARR(STR), "left_label": STR, "right_label": STR,
        "rows": ARR(ROW), "myth": STR, "fact": STR, "quote": STR, "attribution": STR},
        "required": ["kind", "title", "subtitle", "body", "items", "left_label", "right_label", "rows", "myth",
                     "fact", "quote", "attribution"]}),
    "caption": STR, "hashtags": ARR(STR), "keywords": ARR(STR), "claims": ARR(CLAIM)},
    "required": ["hooks", "chosen_hook", "hook_reason", "slides", "caption", "hashtags", "keywords", "claims"]}

COMMON = """{rules}

{formats}

ORIGINALITY: avoid the obvious take. Find the specific, slightly surprising detail in the source, an honest
limitation, or a concrete Indian small-business scenario (clearly framed as an example, e.g. "say you run a
tiles shop in Nagpur with 3 staff"). Specific beats general every time.

IDEA: {idea}
ANGLE: {angle}
AUDIENCE PROBLEM: {problem}
FORMAT: {format}

SOURCE MATERIAL (the ONLY allowed source of facts; cite by id):
{material}

RECENT HOOKS TO AVOID REPEATING (style or wording):
{recent_hooks}
{feedback}"""

REEL_TASK = """
{playbook}

TASK: Write ONE Instagram Reel (9:16) in HINGLISH (Roman script), built to go viral with Indian business owners.
1. Write 5 genuinely different hooks (max 12 words each, spoken in the first 2 seconds), using the hook patterns.
   Pick the one most likely to stop the scroll AND that the Reel can fully pay off (chosen_hook = index); say why.
2. Scenes: 5-8 scenes. Scene 1 narration = the chosen hook exactly. Each scene 4-14 words (one new idea, 2-4 seconds).
   TOTAL narration 40-85 words (15-35 seconds). Spoken Hinglish: natural, fast, no filler, no greetings.
3. on_screen: max 5 words, big and punchy, in Hinglish or English; reinforces (does not repeat) the narration.
4. Visual per scene: 'diagram' for workflows (2-4 short labels), 'compare' for manual-vs-auto (2-3 rows),
   'checklist' (2-4 items), 'text' (headline = a short punchline DIFFERENT from on_screen).
   'screenshot' ONLY if a SOURCE URL is the product's own website (never a news article, blog post or Reddit page).
   Do NOT use 'photo'. Fill every field the chosen visual needs (steps / rows / items / headline).
   Visual labels short (max 5 words each).
5. Last scene: the payoff, then the comment hook: "Comment KEYWORD, main aapko ___ DM kar dunga."
6. dm_keyword: ONE short English word in capitals that fits the topic (e.g. LIST, TOOLS, GST, STEPS, FREE).
   dm_text: the exact message people get by DM (60-150 words, Hinglish or simple English): the promised checklist
   or steps, numbered. Only facts and links that appear in the SOURCE MATERIAL (copy URLs exactly, or no links).
7. Caption: first line = searchable English/Hinglish sentence with keywords; 40-120 words; end with
   "Comment KEYWORD for ___" (same keyword). 3-5 English hashtags. 5 search keywords.
   List every factual claim with its source id."""

CAROUSEL_TASK = """
TASK: Write ONE saveable Instagram carousel (1080x1350) in the chosen format.
1. Write 3 different cover hooks (≤10 words): specific benefit or question. Pick the best (chosen_hook) and say why.
2. Slides: 5-7 total. Slide 1 kind=cover with title = chosen hook and a subtitle that makes the promise concrete.
   Use slide kinds that fit the content. REQUIRED FIELDS (never leave them empty):
   cover: title+subtitle · point: title+body (15-35 words) · steps: title+3-5 items · checklist: title+4-6 items ·
   compare: title+left_label+right_label+3-4 rows · mythfact: myth+fact · quote: quote (exact words from a source)
   +attribution · summary: title+3-4 items.
   Fields a slide kind does not use: return "" or []. Every slide must earn its place: no filler or title-only
   slides. Short lines, phone-readable.
   The LAST slide must be useful on its own (kind=summary or checklist), never a follow request.
3. Caption + 3-5 hashtags + 5 search keywords. List every factual claim with its source id."""


def material(sources, ids):
    blocks = []
    for i in ids:
        s = sources[i]
        blocks.append(f"[{i}] {s['source']} — {s['title']}\nURL: {s['link']}\n{s.get('text') or s['summary']}")
    return "\n\n".join(blocks)


def _prompt(task, idea, sources, recent_hooks, feedback):
    return COMMON.format(rules=config.prompt_file("writing_rules.md"), formats=config.prompt_file("formats.md"),
                         idea=idea["idea"], angle=idea["angle"], problem=idea["audience_problem"],
                         format=idea["format"], material=material(sources, idea["source_ids"]),
                         recent_hooks=recent_hooks or "(none)",
                         feedback=("\nREVIEW OF YOUR PREVIOUS DRAFT — fix every issue:\n" + feedback) if feedback else "") + task


def write_reel(idea, sources, recent_hooks="", feedback=""):
    task = REEL_TASK.replace("{playbook}", config.prompt_file("viral_playbook.md"))
    return llm.generate_json(_prompt(task, idea, sources, recent_hooks, feedback), REEL_SCHEMA, temperature=0.85)


def write_carousel(idea, sources, recent_hooks="", feedback=""):
    return llm.generate_json(_prompt(CAROUSEL_TASK, idea, sources, recent_hooks, feedback), CAROUSEL_SCHEMA,
                             temperature=0.85)
