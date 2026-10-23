"""Pre-publishing quality gate: deterministic rule checks + model review of text AND rendered images."""
import io
import re

from PIL import Image

import config
import history
import llm

CATS = config.CRITICAL + config.OTHER
REVIEW_SCHEMA = {"type": "OBJECT", "properties": {
    "scores": {"type": "OBJECT", "properties": {c: {"type": "INTEGER"} for c in CATS}, "required": CATS},
    "claims": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "claim": {"type": "STRING"}, "supported": {"type": "BOOLEAN"}, "note": {"type": "STRING"}},
        "required": ["claim", "supported"]}},
    "spelling_errors": {"type": "ARRAY", "items": {"type": "STRING"}},
    "visual_issues": {"type": "ARRAY", "items": {"type": "STRING"}},
    "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
    "fix_instructions": {"type": "STRING"}},
    "required": ["scores", "claims", "spelling_errors", "visual_issues", "issues", "fix_instructions"]}

REVIEW = """You are a strict senior editor and fact-checker for an Instagram account about practical AI for Indian
small-business owners. Review this {kind} BEFORE it is published. Be demanding: 8/10 means genuinely good enough
to compete with the best human creators in this niche; most first drafts should score 5-7.

RUBRIC (score 1-10 each):
hook: does the first line/scene stop the scroll with a specific promise, problem or surprise?
originality: fresh angle, not generic AI content seen a hundred times?
practical_value: can the viewer DO something useful after this? specific steps, settings, decisions?
natural_language: sounds like a real knowledgeable person talking; no AI clichés, filler, hype, robotic lists?
accuracy: every factual statement supported by the SOURCE MATERIAL? (illustrative examples clearly framed are fine)
narrative: logical flow, each slide/scene adds something new, no redundancy, satisfying ending?
visual_integrity: in the attached rendered images: readable text, nothing cut off/overlapping, real interfaces
  (screenshots) not fake, no AI artifacts, clean hierarchy, fits a phone screen?
pacing: (reel) scene lengths sensible, no dragging; (carousel) right number of slides, not text-heavy.
brand_consistency: calm, practical, Indian-SMB-relevant voice and the restrained navy/cream/saffron look?
publish_readiness: overall, would you publish this today without edits?

Also: list each factual claim and whether the source supports it; list spelling/grammar errors in on-screen text;
list visual problems you can SEE in the images (be specific: slide/scene number); list other issues; then write
concise fix_instructions for the writer.

SOURCE MATERIAL:
{material}

{kind_upper} (JSON):
{piece}"""


def _small(path, w=540):
    img = Image.open(path).convert("RGB")
    img = img.resize((w, int(img.height * w / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _texts(piece, kind):
    if kind == "reel":
        return [piece.get("caption", "")] + [s.get("narration", "") + " " + s.get("on_screen", "")
                                             for s in piece.get("scenes", [])]
    out = [piece.get("caption", "")]
    for s in piece.get("slides", []):
        out += [str(v) for k, v in s.items() if isinstance(v, str)]
        out += [str(x) for x in s.get("items", [])]
        out += [r.get("left", "") + " " + r.get("right", "") for r in s.get("rows", [])]
    return out


def rule_checks(piece, kind, source_urls, n_sources):
    probs = []
    alltext = " ".join(_texts(piece, kind)).lower()
    for b in config.BANNED:
        if b in alltext:
            probs.append(f"banned phrase used: '{b}'")
    if alltext.count("!") > 1:
        probs.append("more than one exclamation mark")
    tags = piece.get("hashtags", [])
    if not 3 <= len(tags) <= 5:
        probs.append(f"need 3-5 hashtags, got {len(tags)}")
    cw = len(piece.get("caption", "").split())
    if not 40 <= cw <= 170:
        probs.append(f"caption has {cw} words (want 50-140)")
    for c in piece.get("claims", []):
        if not 0 <= c.get("source_id", -1) < n_sources:
            probs.append(f"claim cites unknown source: {c.get('claim')}")
    hooks = piece.get("hooks", [])
    hook = hooks[piece.get("chosen_hook", 0)] if hooks and 0 <= piece.get("chosen_hook", 0) < len(hooks) else ""
    sim, match = history.most_similar(hook + " " + " ".join(piece.get("keywords", [])))
    if sim >= config.DUP_THRESHOLD:
        probs.append(f"hook/keywords too similar to past item: {match.get('topic')}")
    if kind == "reel":
        sc = piece.get("scenes", [])
        if not 4 <= len(sc) <= 9:
            probs.append(f"{len(sc)} scenes (want 4-8)")
        if sc and len(sc[0].get("narration", "").split()) > 18:
            probs.append("opening line too long for a 3-second hook")
        for i, s in enumerate(sc, 1):
            n = len(s.get("narration", "").split())
            if n < 4 or n > 34:
                probs.append(f"scene {i} narration {n} words")
            if len(s.get("on_screen", "").split()) > 7:
                probs.append(f"scene {i} on-screen text too long")
            if s.get("visual_type") == "screenshot" and s.get("url") not in source_urls:
                probs.append(f"scene {i} screenshot URL is not one of the sources")
    else:
        sl = piece.get("slides", [])
        if not 4 <= len(sl) <= 9:
            probs.append(f"{len(sl)} slides (want 5-8)")
        if sl and sl[0].get("kind") != "cover":
            probs.append("first slide must be the cover")
        if sl and sl[-1].get("kind") not in ("summary", "checklist"):
            probs.append("last slide must be a useful summary/checklist")
        for i, s in enumerate(sl, 1):
            if len(s.get("body", "").split()) > 40:
                probs.append(f"slide {i} body too long for a phone")
    return probs


def review(piece, kind, material, image_paths):
    imgs = [_small(p) for p in image_paths[:10]]
    import json
    return llm.generate_json(REVIEW.format(kind=kind, kind_upper=kind.upper(), material=material,
                                           piece=json.dumps(piece, ensure_ascii=False, indent=1)),
                             REVIEW_SCHEMA, images=imgs, temperature=0.2)


def verdict(rules, rev, render_meta=None):
    reasons = list(rules)
    s = rev["scores"]
    for c in config.CRITICAL:
        if s.get(c, 0) < config.MIN_CRITICAL:
            reasons.append(f"{c} {s.get(c)}/10 (<{config.MIN_CRITICAL})")
    for c in config.OTHER:
        if s.get(c, 0) < config.MIN_OTHER:
            reasons.append(f"{c} {s.get(c)}/10 (<{config.MIN_OTHER})")
    bad = [c["claim"] for c in rev.get("claims", []) if not c.get("supported")]
    if bad:
        reasons.append("unsupported claims: " + "; ".join(bad[:3]))
    if rev.get("spelling_errors"):
        reasons.append("spelling: " + "; ".join(rev["spelling_errors"][:3]))
    if render_meta and render_meta.get("fallback_visuals", 0) > 1:
        reasons.append(f"{render_meta['fallback_visuals']} scenes lost their real visual (screenshot/photo failed)")
    return (len(reasons) == 0), reasons


def feedback_text(rules, rev):
    parts = []
    if rules:
        parts.append("Rule violations: " + "; ".join(rules))
    if rev:
        parts.append("Editor issues: " + "; ".join(rev.get("issues", [])[:8]))
        if rev.get("visual_issues"):
            parts.append("Visual issues: " + "; ".join(rev["visual_issues"][:5]))
        parts.append("Fix: " + rev.get("fix_instructions", ""))
    return "\n".join(parts)


def clean_tags(tags):
    return ["#" + re.sub(r"[^A-Za-z0-9_]", "", t.lstrip("#")) for t in tags if t.strip("# ")][:5]
