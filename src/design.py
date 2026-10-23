"""Brand identity v2: restrained editorial look. Shared drawing helpers for carousels and reels."""
import os

from PIL import Image, ImageDraw, ImageFont, ImageFilter

import config

FONT_DIR = os.path.join(config.ROOT, "fonts")

# Palette
CREAM = (246, 243, 236)
CARD = (255, 255, 255)
INK = (19, 33, 60)
INK_DARK = (13, 22, 40)
ACCENT = (232, 134, 42)      # saffron, used sparingly
MUTED = (107, 114, 128)
LINE = (226, 222, 212)
GREEN = (34, 139, 94)
RED = (196, 69, 54)
WHITE = (255, 255, 255)

_fonts = {}


def font(weight, size):
    key = (weight, size)
    if key not in _fonts:
        name = {"Regular": "Inter-Regular.otf", "Medium": "Inter-Medium.otf", "SemiBold": "Inter-SemiBold.otf",
                "Bold": "Inter-Bold.otf", "Display": "Poppins-Bold.ttf"}[weight]
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):  # Inter comes from the 'fonts-inter' system package on the runner
            alt = os.path.join("/usr/share/fonts/opentype/inter", name)
            path = alt if os.path.exists(alt) else os.path.join(FONT_DIR, "Poppins-Bold.ttf" if "Bold" in name
                                                                  else "Poppins-Regular.ttf")
        _fonts[key] = ImageFont.truetype(path, size)
    return _fonts[key]


def wrap(draw, text, fnt, max_w):
    lines, line = [], ""
    for w in (text or "").split():
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


def fit(draw, text, weight, max_w, max_h, start, min_size, spacing=1.2):
    size = start
    while size >= min_size:
        f = font(weight, size)
        lines = wrap(draw, text, f, max_w)
        if int(size * spacing) * len(lines) <= max_h:
            return f, lines, int(size * spacing)
        size -= 2
    f = font(weight, min_size)
    return f, wrap(draw, text, f, max_w), int(min_size * spacing)


def text_block(draw, xy, text, weight, max_w, max_h, start, min_size, fill, spacing=1.2, align="left"):
    f, lines, lh = fit(draw, text, weight, max_w, max_h, start, min_size, spacing)
    x, y = xy
    for ln in lines:
        lx = x + (max_w - draw.textlength(ln, font=f)) / 2 if align == "center" else x
        draw.text((lx, y), ln, font=f, fill=fill)
        y += lh
    return y


def mark(draw, x, y, size=44, bg=ACCENT, fg=WHITE):
    """Brand mark: rounded square with 'A' and a short underline."""
    draw.rounded_rectangle((x, y, x + size, y + size), radius=size // 4, fill=bg)
    f = font("Bold", int(size * 0.6))
    tw = draw.textlength("A", font=f)
    draw.text((x + (size - tw) / 2, y + size * 0.1), "A", font=f, fill=fg)
    draw.rectangle((x + size * 0.3, y + size * 0.8, x + size * 0.7, y + size * 0.86), fill=fg)


def check_icon(draw, x, y, s, color=GREEN):
    draw.rounded_rectangle((x, y, x + s, y + s), radius=s // 4, fill=color)
    draw.line((x + s * 0.24, y + s * 0.52, x + s * 0.43, y + s * 0.7, x + s * 0.78, y + s * 0.3), fill=WHITE,
              width=max(3, s // 9))


def cross_icon(draw, x, y, s, color=RED):
    draw.rounded_rectangle((x, y, x + s, y + s), radius=s // 4, fill=color)
    w = max(3, s // 9)
    draw.line((x + s * 0.3, y + s * 0.3, x + s * 0.7, y + s * 0.7), fill=WHITE, width=w)
    draw.line((x + s * 0.7, y + s * 0.3, x + s * 0.3, y + s * 0.7), fill=WHITE, width=w)


def rounded_paste(base, img, xy, radius=28):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.size[0], img.size[1]), radius=radius, fill=255)
    base.paste(img, xy, mask)


def shadow(base, box, radius=28, blur=24, opacity=60):
    x0, y0, x1, y1 = box
    sh = Image.new("L", base.size, 0)
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 10, x1, y1 + 10), radius=radius, fill=opacity)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.paste(Image.new("RGB", base.size, (0, 0, 0)), (0, 0), sh)


def cover_crop(img, w, h, focus_top=False):
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale + 0.5), int(img.height * scale + 0.5)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = 0 if focus_top else (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))
