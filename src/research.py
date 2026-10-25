"""Idea generation, scoring and selection."""
import os

import config
import history
import llm

IDEA_SCHEMA = {"type": "OBJECT", "properties": {"ideas": {"type": "ARRAY", "items": {
    "type": "OBJECT",
    "properties": {
        "idea": {"type": "STRING"}, "angle": {"type": "STRING"}, "audience_problem": {"type": "STRING"},
        "format": {"type": "STRING"}, "medium": {"type": "STRING", "enum": ["reel", "carousel", "both"]},
        "source_ids": {"type": "ARRAY", "items": {"type": "INTEGER"}},
        "evergreen": {"type": "BOOLEAN"}, "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
        "scores": {"type": "OBJECT", "properties": {k: {"type": "INTEGER"} for k in
                   ["relevance", "novelty", "hook_potential", "retention", "save_share", "feasibility", "evidence",
                    "viral"]},
                   "required": ["relevance", "novelty", "hook_potential", "retention", "save_share",
                                "feasibility", "evidence", "viral"]},
    },
    "required": ["idea", "angle", "audience_problem", "format", "medium", "source_ids", "evergreen",
                 "keywords", "scores"]}}}, "required": ["ideas"]}

WEIGHTS = {"relevance": 1.6, "novelty": 1.2, "hook_potential": 1.8, "retention": 1.3, "save_share": 1.6,
           "feasibility": 0.7, "evidence": 1.3, "viral": 2.0}

PROMPT = """You are the head of research for @automatei_q, an Instagram account about practical AI and automation
for Indian small-business owners, contractors and traders.

SOURCES (id | kind | source | title | summary). kind=question means a real person asked this.
{sources}

ALREADY PUBLISHED OR PLANNED (avoid repeats and near-repeats of topic AND angle):
{history}

WHAT HAS WORKED SO FAR (from our own Instagram Insights; may be empty early on):
{learnings}

{formats}

TASK: Propose 14 distinct content ideas. Each must be grounded in one or more sources above (list their ids).
NICHE (hard rule): every idea must be about USING AI or automation tools/workflows in a business (a named tool,
a workflow, a setting, a cost, a risk of a tool). General self-help, productivity, mindset or management advice
with no AI/automation tool at its centre is OFF-NICHE: do not propose it.
Prefer: real audience questions, practical tools the audience can use this week, honest comparisons,
mistakes and limits, and evergreen how-tos. Avoid: pure funding/industry gossip, vague "AI will change everything",
self-promotional Reddit posts unless the tool is genuinely useful and free/cheap, anything needing facts not in sources.
Novelty matters: skip the take every AI account already posted ("ChatGPT can write emails"). Look for the
surprising detail, the honest limitation, the India-specific twist, or the question nobody answered well.
Give the idea a specific ANGLE (the fresh take) and the AUDIENCE PROBLEM it solves, in one sentence each.
Choose the best format from the library and the medium (reel, carousel or both).
Score 1-10 honestly: relevance (to Indian SMB owners), novelty (vs history and common content), hook_potential,
retention (can it hold 20-40 s), save_share (would someone save it or send it to a colleague), feasibility
(can we show it with screenshots/diagrams/text, no filming), evidence (how well sources support the facts needed).
viral (would thousands of Indian business owners stop, watch to the end and SEND this to a friend or WhatsApp
group? money/time/risk/free-tool angles score high; niche tech news scores low).
Do not inflate scores. Mark evergreen=true for ideas that stay useful for months.

{playbook}"""


def candidates(items, learnings=""):
    listing = "\n".join(f"{i} | {s['kind']} | {s['source']} | {s['title']} | {s['summary'][:260]}"
                        for i, s in enumerate(items[:90]))
    res = llm.generate_json(PROMPT.format(sources=listing, history=history.summary_for_prompt(),
                                          learnings=learnings or "(no data yet)",
                                          formats=config.prompt_file("formats.md"),
                                          playbook=config.prompt_file("viral_playbook.md")),
                            IDEA_SCHEMA, temperature=0.9)
    ideas = res.get("ideas", [])
    for idea in ideas:
        s = idea["scores"]
        idea["total"] = round(sum(WEIGHTS[k] * s.get(k, 0) for k in WEIGHTS) / sum(WEIGHTS.values()), 2)
        idea["source_ids"] = [i for i in idea["source_ids"] if 0 <= i < len(items)]
    return sorted(ideas, key=lambda x: -x["total"])


def select(ideas, n_reels, n_carousels):
    """Pick the best non-duplicate ideas with format variety. Returns (reels, carousels, rejected)."""
    reels, cars, rejected, planned = [], [], [], []
    for idea in ideas:
        text = " ".join([idea["idea"], idea["angle"], " ".join(idea["keywords"])])
        sim, match = history.most_similar(text, extra=planned)
        if sim >= config.DUP_THRESHOLD:
            rejected.append((idea["idea"], f"too similar ({sim:.2f}) to: {match.get('topic')}"))
            continue
        if idea["scores"]["evidence"] < 6 or not idea["source_ids"]:
            rejected.append((idea["idea"], "weak evidence"))
            continue
        if idea["scores"]["relevance"] < 7 or idea["scores"].get("novelty", 0) < 7:
            rejected.append((idea["idea"], "low relevance or novelty"))
            continue
        want_reel = idea["medium"] in ("reel", "both") and len(reels) < n_reels and \
            idea["format"] not in [r["format"] for r in reels]
        want_car = idea["medium"] in ("carousel", "both") and len(cars) < n_carousels and \
            idea["format"] not in [c["format"] for c in cars]
        if want_reel and (not want_car or len(reels) <= len(cars)):
            reels.append(idea)
        elif want_car:
            cars.append(idea)
        else:
            continue
        planned.append({"topic": idea["idea"], "hook": idea["angle"], "keywords": idea["keywords"]})
    return reels, cars, rejected


def learnings_text():
    path = os.path.join(config.DATA, "learnings.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()[:2500]
    return ""
