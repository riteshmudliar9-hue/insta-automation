"""Carousel renderer: 1080x1350 editorial layouts, one per slide kind."""
import os

from PIL import Image, ImageDraw

import config
import design as D

W, H = 1080, 1350
M = 84  # side margin
KICKER = {"demo": "DEMO", "problem_fix": "PROBLEM → FIX", "tutorial": "HOW TO", "experiment": "EXPERIMENT",
          "tool_test": "TOOL TEST", "myth_fact": "MYTH vs FACT", "case_study": "CASE STUDY",
          "manual_vs_auto": "MANUAL vs AUTOMATED", "checklist": "CHECKLIST", "audience_q": "YOU ASKED"}


def _chrome(img, idx, total):
    d = ImageDraw.Draw(img)
    D.mark(d, M, 62, 40)
    d.text((M + 56, 68), config.HANDLE, font=D.font("SemiBold", 26), fill=D.MUTED)
    lab = f"{idx} / {total}"
    f = D.font("Medium", 26)
    d.text((W - M - d.textlength(lab, font=f), 68), lab, font=f, fill=D.MUTED)
    y = H - 64
    d.rounded_rectangle((M, y, W - M, y + 6), radius=3, fill=D.LINE)
    d.rounded_rectangle((M, y, M + (W - 2 * M) * idx / total, y + 6), radius=3, fill=D.ACCENT)
    return d


def _title(d, text, y=170, size=66, max_h=260):
    return D.text_block(d, (M, y), text, "Bold", W - 2 * M, max_h, size, 44, D.INK, spacing=1.15)


def _title_h(d, text, size=66, max_h=260):
    f, lines, lh = D.fit(d, text, "Bold", W - 2 * M, max_h, size, 44, 1.15)
    return lh * len(lines)


TOP, BOTTOM = 150, H - 110   # usable content band


def _start(block_h):
    return int(max(TOP + 20, TOP + (BOTTOM - TOP - block_h) / 2))


def _cover(img, s, fmt, shot):
    d = ImageDraw.Draw(img)
    k = KICKER.get(fmt, "")
    y = 190
    if shot is None:
        tf, tl, tlh = D.fit(d, s.get("title", ""), "Bold", W - 2 * M, 470, 104, 58, 1.08)
        sf, sl, slh = D.fit(d, s.get("subtitle", ""), "Regular", W - 2 * M, 190, 44, 32, 1.3)
        y = _start(86 + tlh * len(tl) + 66 + slh * len(sl))
    if k:
        f = D.font("Bold", 26)
        tw = d.textlength(k, font=f)
        d.rounded_rectangle((M, y, M + tw + 36, y + 50), radius=25, fill=D.INK)
        d.text((M + 18, y + 10), k, font=f, fill=D.WHITE)
        y += 86
    title_h = 470 if shot is None else 380
    y = D.text_block(d, (M, y), s.get("title", ""), "Bold", W - 2 * M, title_h, 104 if shot is None else 98, 58,
                     D.INK, spacing=1.08)
    y += 26
    d.rectangle((M, y, M + 90, y + 8), fill=D.ACCENT)
    y += 40
    y = D.text_block(d, (M, y), s.get("subtitle", ""), "Regular", W - 2 * M, 190, 44, 32, D.MUTED, spacing=1.3)
    if shot is not None:
        top = max(y + 40, 880)
        box_h = H - 120 - top
        if box_h > 200:
            card = D.cover_crop(shot, W - 2 * M, box_h, focus_top=True)
            D.shadow(img, (M, top, W - M, top + box_h))
            D.rounded_paste(img, card, (M, top), 26)
            d = ImageDraw.Draw(img)


def _point(img, s):
    d = ImageDraw.Draw(img)
    f, lines, lh = D.fit(d, s.get("body", ""), "Regular", W - 2 * M, 700, 52, 34, 1.38)
    y = _start(_title_h(d, s.get("title", ""), 72) + 50 + lh * len(lines))
    y = _title(d, s.get("title", ""), y, 72)
    D.text_block(d, (M, y + 50), s.get("body", ""), "Regular", W - 2 * M, 700, 52, 34, D.INK, spacing=1.38)


def _list(img, s, numbered):
    d = ImageDraw.Draw(img)
    items = s.get("items", [])[:6]
    th = _title_h(d, s.get("title", ""), 70)
    per = min(190, (BOTTOM - TOP - th - 50) // max(1, len(items)))
    y = _title(d, s.get("title", ""), _start(th + 50 + per * len(items)), 70) + 50
    for i, it in enumerate(items, 1):
        box = (M, y, W - M, y + per - 22)
        d.rounded_rectangle(box, radius=22, fill=D.CARD, outline=D.LINE, width=2)
        cy = y + (per - 22) / 2
        if numbered:
            d.ellipse((M + 26, cy - 30, M + 86, cy + 30), fill=D.ACCENT)
            n = str(i)
            f = D.font("Bold", 32)
            d.text((M + 56 - d.textlength(n, font=f) / 2, cy - 21), n, font=f, fill=D.WHITE)
        else:
            D.check_icon(d, M + 28, int(cy - 28), 56)
        f, lines, lh = D.fit(d, it, "Medium", W - 2 * M - 150, per - 50, 44, 28, 1.22)
        ty = cy - lh * len(lines) / 2
        for ln in lines:
            d.text((M + 116, ty), ln, font=f, fill=D.INK)
            ty += lh
        y += per


def _compare(img, s):
    d = ImageDraw.Draw(img)
    rows = s.get("rows", [])[:5]
    th = _title_h(d, s.get("title", ""), 70)
    per = min(210, (BOTTOM - TOP - th - 120) // max(1, len(rows)))
    y = _title(d, s.get("title", ""), _start(th + 108 + per * len(rows)), 70) + 36
    colw = (W - 2 * M - 24) // 2
    lx, rx = M, M + colw + 24
    f = D.font("Bold", 30)
    D.cross_icon(d, lx, y, 40)
    d.text((lx + 54, y + 2), (s.get("left_label") or "Manual").upper(), font=f, fill=D.MUTED)
    D.check_icon(d, rx, y, 40)
    d.text((rx + 54, y + 2), (s.get("right_label") or "Automated").upper(), font=f, fill=D.INK)
    y += 72
    for r in rows:
        for x, txt, fill, bg in ((lx, r.get("left", ""), D.MUTED, (238, 235, 228)),
                                 (rx, r.get("right", ""), D.INK, D.CARD)):
            d.rounded_rectangle((x, y, x + colw, y + per - 18), radius=20, fill=bg, outline=D.LINE, width=2)
            D.text_block(d, (x + 26, y + 24), txt, "Medium", colw - 52, per - 60, 40, 26, fill, spacing=1.2)
        y += per


def _mythfact(img, s):
    d = ImageDraw.Draw(img)
    mf, ml, mlh = D.fit(d, s.get("myth", ""), "Medium", W - 2 * M, 300, 56, 36, 1.2)
    ff, fl, flh = D.fit(d, s.get("fact", ""), "Bold", W - 2 * M, 420, 60, 34, 1.22)
    y = _start(80 + mlh * len(ml) + 100 + 80 + flh * len(fl))
    f = D.font("Bold", 28)
    d.rounded_rectangle((M, y, M + 120, y + 48), radius=24, fill=D.RED)
    d.text((M + 24, y + 9), "MYTH", font=f, fill=D.WHITE)
    y = D.text_block(d, (M, y + 80), s.get("myth", ""), "Medium", W - 2 * M, 300, 56, 36, D.MUTED, spacing=1.2)
    y += 50
    d.line((M, y, W - M, y), fill=D.LINE, width=3)
    y += 50
    d.rounded_rectangle((M, y, M + 110, y + 48), radius=24, fill=D.GREEN)
    d.text((M + 24, y + 9), "FACT", font=f, fill=D.WHITE)
    D.text_block(d, (M, y + 80), s.get("fact", ""), "Bold", W - 2 * M, 420, 60, 34, D.INK, spacing=1.22)


def _quote(img, s):
    d = ImageDraw.Draw(img)
    d.text((M - 6, 150), "“", font=D.font("Display", 220), fill=D.ACCENT)
    y = D.text_block(d, (M, 380), s.get("quote", ""), "Medium", W - 2 * M, 600, 56, 36, D.INK, spacing=1.3)
    d.text((M, y + 40), "— " + (s.get("attribution") or ""), font=D.font("SemiBold", 32), fill=D.MUTED)


def render(car, out_dir, fmt="", cover_shot=None):
    os.makedirs(out_dir, exist_ok=True)
    slides = car["slides"]
    total = len(slides)
    paths = []
    for i, s in enumerate(slides, 1):
        img = Image.new("RGB", (W, H), D.CREAM)
        k = s.get("kind", "point")
        if k == "cover":
            _cover(img, s, fmt, cover_shot)
        elif k in ("steps",):
            _list(img, s, numbered=True)
        elif k in ("checklist", "summary"):
            _list(img, s, numbered=False)
        elif k == "compare":
            _compare(img, s)
        elif k == "mythfact":
            _mythfact(img, s)
        elif k == "quote":
            _quote(img, s)
        else:
            _point(img, s)
        _chrome(img, i, total)
        p = os.path.join(out_dir, f"slide_{i:02d}.jpg")
        img.save(p, "JPEG", quality=92)
        paths.append(p)
    return paths
