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
        "required": ["purpose", "narration", "on_screen", "visual_type"]}),
    "caption": STR, "hashtags": ARR(STR), "keywords": ARR(STR), "claims": ARR(CLAIM)},
    "required": ["hooks", "chosen_hook", "hook_reason", "title", "scenes", "caption", "hashtags", "keywords", "claims"]}

CAROUSEL_SCHEMA = {"type": "OBJECT", "properties": {
    "hooks": ARR(STR), "chosen_hook": {"type": "INTEGER"}, "hook_reason": STR,
    "slides": ARR({"type": "OBJECT", "properties": {
        "kind": {"type": "STRING", "enum": ["cover", "point", "steps", "checklist", "compare", "mythfact",
                                            "quote", "summary"]},
        "title": STR, "subtitle": STR, "body": STR, "items": ARR(STR), "left_label": STR, "right_label": STR,
        "rows": ARR(ROW), "myth": STR, "fact": STR, "quote": STR, "attribution": STR},
        "required": ["kind"]}),
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
TASK: Write ONE Instagram Reel (9:16) in the chosen format.
1. Write 3 genuinely different opening hooks (≤14 words each, spoken in the first 3 seconds): e.g. a problem,
   a surprising fact from the source, a strong opinion, a result. Pick the strongest (chosen_hook = index) and say why.
2. Write the scenes. Scene 1 narration = the chosen hook exactly. Each later scene must add new information,
   a demonstration, or move the story; cut anything redundant. 4-7 scenes. Narration 6-25 words per scene,
   TOTAL narration 55-110 words (about 22-45 seconds). Written to be SPOKEN (contractions, natural rhythm).
3. on_screen: ≤6 words that reinforce (not repeat) the narration.
4. Visual per scene: 'diagram' for workflows (2-4 short labels), 'compare' for manual-vs-auto (3 rows),
   'checklist' (3-5 items), 'text' (headline = a short punchline DIFFERENT from on_screen).
   'screenshot' ONLY if a SOURCE URL is the product's own website (never a news article, blog post or Reddit page).
   'photo' (query) only for a real-world setting like "shop counter India". Never fake interfaces or people.
   Fill every field the chosen visual needs (steps / rows / items / headline).
5. Last scene: the practical takeaway or next step. No "follow for more", no "like and share".
6. Caption + 3-5 hashtags + 5 search keywords. List every factual claim with its source id."""

CAROUSEL_TASK = """
TASK: Write ONE saveable Instagram carousel (1080x1350) in the chosen format.
1. Write 3 different cover hooks (≤10 words): specific benefit or question. Pick the best (chosen_hook) and say why.
2. Slides: 5-7 total. Slide 1 kind=cover with title = chosen hook and a subtitle that makes the promise concrete.
   Use slide kinds that fit the content. REQUIRED FIELDS (never leave them empty):
   cover: title+subtitle · point: title+body (15-35 words) · steps: title+3-5 items · checklist: title+4-6 items ·
   compare: title+left_label+right_label+3-4 rows · mythfact: myth+fact · quote: quote (exact words from a source)
   +attribution · summary: title+3-4 items.
   Every slide must earn its place: no filler or title-only slides. Short lines, phone-readable.
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
    return llm.generate_json(_prompt(REEL_TASK, idea, sources, recent_hooks, feedback), REEL_SCHEMA, temperature=0.85)


def write_carousel(idea, sources, recent_hooks="", feedback=""):
    return llm.generate_json(_prompt(CAROUSEL_TASK, idea, sources, recent_hooks, feedback), CAROUSEL_SCHEMA,
                             temperature=0.85)
