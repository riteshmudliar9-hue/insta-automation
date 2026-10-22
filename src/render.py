"""Render a branded 1080x1350 Instagram carousel with Pillow."""
import io
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "fonts")

# Brand
HANDLE = "@automatei_q"
NAVY = (11, 31, 58)          # #0B1F3A
NAVY_2 = (18, 45, 82)        # lighter navy for gradient / cards
SAFFRON = (255, 153, 51)     # #FF9933
WHITE = (255, 255, 255)
MUTED = (170, 186, 210)
TAGLINE = "AI & AUTOMATION FOR REAL BUSINESSES"
MARGIN = 90


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(os.path.join(FONT_DIR, f"Poppins-{weight}.ttf"), size)


def wrap(draw, text, fnt, max_w):
    words, lines, line = text.split(), [], ""
    for w in words:
        test = f"{line} {w}".strip()
        if draw.textlength(test, font=fnt) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def fit_text(draw, text, weight, max_w, max_h, start=96, min_size=40, spacing=1.18):
    """Largest font size where wrapped text fits in the box."""
    size = start
    while size >= min_size:
        fnt = font(weight, size)
        lines = wrap(draw, text, fnt, max_w)
        lh = int(size * spacing)
        if lh * len(lines) <= max_h:
            return fnt, lines, lh
        size -= 4
    fnt = font(weight, min_size)
    return fnt, wrap(draw, text, fnt, max_w), int(min_size * spacing)


def gradient_bg():
    img = Image.new("RGB", (W, H), NAVY)
    top, bot = NAVY_2, NAVY
    px = img.load()
    for y in range(H):
        t = y / H
        c = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    return img


_BG = None


def base():
    global _BG
    if _BG is None:
        _BG = gradient_bg()
        d = ImageDraw.Draw(_BG)
        # subtle saffron glow circle, top-right
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse((W - 420, -260, W + 260, 420), fill=45)
        glow = glow.filter(ImageFilter.GaussianBlur(140))
        _BG = Image.composite(Image.new("RGB", (W, H), SAFFRON), _BG, glow)
    return _BG.copy()


def logo(draw, x, y, size=64):
    """Text logo: saffron rounded square with 'A' + bolt-style underline."""
    draw.rounded_rectangle((x, y, x + size, y + size), radius=16, fill=SAFFRON)
    f = font("Bold", int(size * 0.62))
    tw = draw.textlength("A", font=f)
    draw.text((x + (size - tw) / 2, y + size * 0.08), "A", font=f, fill=NAVY)
    draw.rectangle((x + size * 0.28, y + size * 0.80, x + size * 0.72, y + size * 0.86), fill=NAVY)


def header(draw, idx, total):
    logo(draw, MARGIN, 70)
    draw.text((MARGIN + 82, 80), HANDLE, font=font("Bold", 34), fill=WHITE)
    f = font("Medium", 30)
    label = f"{idx}/{total}"
    tw = draw.textlength(label, font=f)
    draw.rounded_rectangle((W - MARGIN - tw - 36, 76, W - MARGIN, 128), radius=26, outline=MUTED, width=2)
    draw.text((W - MARGIN - tw - 18, 82), label, font=f, fill=MUTED)


def arrow(draw, x, y, color, length=44):
    draw.line((x, y, x + length, y), fill=color, width=5)
    draw.polygon([(x + length + 4, y), (x + length - 14, y - 12), (x + length - 14, y + 12)], fill=color)


def footer(draw, idx, total, text="Swipe for more"):
    # progress dots
    r, gap = 7, 26
    start = MARGIN
    for i in range(total):
        cx = start + i * gap
        fill = SAFFRON if i + 1 == idx else (60, 82, 115)
        draw.ellipse((cx - r, H - 95 - r, cx + r, H - 95 + r), fill=fill)
    f = font("Medium", 30)
    if text:
        tw = draw.textlength(text, font=f)
        draw.text((W - MARGIN - tw - 70, H - 115), text, font=f, fill=SAFFRON)
        arrow(draw, W - MARGIN - 52, H - 96, SAFFRON)


def cover(hook, total, photo_bytes=None):
    img = base()
    if photo_bytes:
        try:
            ph = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
            # cover-crop to top 60% area
            area_h = int(H * 0.62)
            scale = max(W / ph.width, area_h / ph.height)
            ph = ph.resize((int(ph.width * scale), int(ph.height * scale)))
            left = (ph.width - W) // 2
            top = (ph.height - area_h) // 2
            ph = ph.crop((left, top, left + W, top + area_h))
            # fade photo into navy
            mask = Image.new("L", (W, area_h), 0)
            md = ImageDraw.Draw(mask)
            for y in range(area_h):
                md.line((0, y, W, y), fill=int(170 * (1 - y / area_h) ** 0.8))
            img.paste(ph, (0, 0), mask)
        except Exception as e:  # photo is optional
            print("cover photo skipped:", e)
    d = ImageDraw.Draw(img)
    header(d, 1, total)
    # tagline pill
    f = font("Bold", 26)
    tw = d.textlength(TAGLINE, font=f)
    y0 = 560
    d.rounded_rectangle((MARGIN, y0, MARGIN + tw + 44, y0 + 54), radius=27, fill=SAFFRON)
    d.text((MARGIN + 22, y0 + 10), TAGLINE, font=f, fill=NAVY)
    # hook
    fnt, lines, lh = fit_text(d, hook, "Bold", W - 2 * MARGIN, 470, start=92, min_size=56)
    y = y0 + 90
    for ln in lines:
        d.text((MARGIN, y), ln, font=fnt, fill=WHITE)
        y += lh
    d.rectangle((MARGIN, y + 20, MARGIN + 140, y + 30), fill=SAFFRON)
    footer(d, 1, total)
    return img


def content(n, title, text, idx, total):
    img = base()
    d = ImageDraw.Draw(img)
    header(d, idx, total)
    inner_w = W - 2 * MARGIN
    tfnt, tlines, tlh = fit_text(d, title, "Bold", inner_w, 250, start=76, min_size=48, spacing=1.15)
    bfnt, blines, blh = fit_text(d, text, "Regular", inner_w - 80, 520, start=50, min_size=34, spacing=1.4)
    num_h, gap1, gap2 = 170, 30, 50
    title_h = tlh * len(tlines)
    card_h = blh * len(blines) + 80
    block = num_h + gap1 + title_h + gap2 + card_h
    top_lim, bot_lim = 180, H - 160
    y = top_lim + max(0, (bot_lim - top_lim - block) // 2)
    d.text((MARGIN, y - 20), f"{n:02d}", font=font("Bold", 160), fill=SAFFRON)
    y += num_h + gap1
    for ln in tlines:
        d.text((MARGIN, y), ln, font=tfnt, fill=WHITE)
        y += tlh
    y += gap2
    card_top = y
    d.rounded_rectangle((MARGIN, card_top, W - MARGIN, card_top + card_h), radius=28, fill=NAVY_2)
    d.rectangle((MARGIN, card_top + 24, MARGIN + 8, card_top + card_h - 24), fill=SAFFRON)
    y = card_top + 40
    for ln in blines:
        d.text((MARGIN + 50, y), ln, font=bfnt, fill=(225, 232, 244))
        y += blh
    footer(d, idx, total)
    return img


def cta(idx, total):
    img = base()
    d = ImageDraw.Draw(img)
    header(d, idx, total)
    logo(d, (W - 180) // 2, 330, size=180)
    lines = ["Found this useful?", "Follow for daily AI tips", "for Indian businesses."]
    y = 580
    for i, ln in enumerate(lines):
        f = font("Bold", 64 if i == 0 else 50)
        tw = d.textlength(ln, font=f)
        d.text(((W - tw) / 2, y), ln, font=f, fill=SAFFRON if i == 0 else WHITE)
        y += 90 if i == 0 else 70
    f = font("Bold", 46)
    tw = d.textlength(HANDLE, font=f)
    d.rounded_rectangle(((W - tw) / 2 - 40, y + 50, (W + tw) / 2 + 40, y + 140), radius=45, fill=SAFFRON)
    d.text(((W - tw) / 2, y + 66), HANDLE, font=f, fill=NAVY)
    f = font("Medium", 34)
    t = "Save  •  Share  •  Comment"
    tw = d.textlength(t, font=f)
    d.text(((W - tw) / 2, y + 200), t, font=f, fill=MUTED)
    footer(d, idx, total, text="")
    return img


def render_carousel(post, out_dir, photo_bytes=None):
    """post = {hook, slides:[{title,text}]}. Returns list of JPEG paths."""
    os.makedirs(out_dir, exist_ok=True)
    slides = post["slides"]
    total = len(slides) + 2
    imgs = [cover(post["hook"], total, photo_bytes)]
    for i, s in enumerate(slides, start=1):
        imgs.append(content(i, s["title"], s["text"], i + 1, total))
    imgs.append(cta(total, total))
    paths = []
    for i, im in enumerate(imgs, start=1):
        p = os.path.join(out_dir, f"slide_{i:02d}.jpg")
        im.save(p, "JPEG", quality=92)  # Instagram API accepts JPEG only
        paths.append(p)
    return paths
