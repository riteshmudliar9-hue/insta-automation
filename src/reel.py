"""Reel renderer v2: scene-based 1080x1920 video with real visuals, staged animations,
synced subtitles and a natural voice (Gemini TTS, edge-tts fallback)."""
import asyncio
import os
import subprocess
import tempfile
import wave

from PIL import Image, ImageDraw

import config
import design as D
import llm
import visuals

RW, RH, FPS = 1080, 1920, 30
PX, PY, PW, PH = 60, 430, 960, 860           # visual panel (inside Instagram safe area)
SUB_Y = 1440                                 # subtitle centre line (above IG bottom UI)
TAIL = 0.35                                  # pause after each scene's narration


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *args], check=True)


# ---------------- audio ----------------
async def _edge(text, path):
    import edge_tts
    await edge_tts.Communicate(text, config.EDGE_VOICE, rate="+4%").save(path)


def _to_wav(src, dst):
    run(["-i", src, "-ar", "44100", "-ac", "1", "-sample_fmt", "s16", dst])


def _seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / w.getframerate()


def voice_lines(lines, tmp):
    """Returns (wav paths, durations, engine). One engine for the whole reel so the voice is consistent."""
    engine = "gemini"
    wavs = []
    for i, line in enumerate(lines):
        raw = os.path.join(tmp, f"g{i}.wav")
        data = llm.gemini_tts(line) if engine == "gemini" else None
        if data is None and engine == "gemini":
            engine = "edge"          # switch the whole reel to edge-tts for consistency
            return _edge_all(lines, tmp)
        with open(raw, "wb") as f:
            f.write(data)
        out = os.path.join(tmp, f"v{i}.wav")
        _to_wav(raw, out)
        wavs.append(out)
    return wavs, [_seconds(w) for w in wavs], engine


def _edge_all(lines, tmp):
    wavs = []
    for i, line in enumerate(lines):
        mp3 = os.path.join(tmp, f"e{i}.mp3")
        asyncio.run(_edge(line, mp3))
        out = os.path.join(tmp, f"v{i}.wav")
        _to_wav(mp3, out)
        wavs.append(out)
    return wavs, [_seconds(w) for w in wavs], "edge"


def concat_audio(wavs, durs, path):
    with wave.open(path, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        for w, d in zip(wavs, durs):
            with wave.open(w) as src:
                frames = src.readframes(src.getnframes())
            need = int(d * 44100) * 2
            out.writeframes(frames[:need] + b"\x00" * max(0, need - len(frames)))


# ---------------- subtitles ----------------
WEAK_END = {"a", "an", "the", "to", "of", "and", "or", "but", "in", "on", "at", "for", "with", "your", "my",
            "our", "their", "is", "are", "was", "that", "this", "it", "you", "we", "they", "by", "from", "as",
            "if", "so", "than", "into", "about", "can", "will", "do", "does", "not", "no", "be", "just", "every"}


def chunks(text, max_words=8, max_chars=40, min_words=3):
    """Phrase-aware subtitle chunks (1-2 lines). Breaks at punctuation; never ends a chunk on a weak word."""
    words, out, cur = text.split(), [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        line = " ".join(cur)
        if nxt is None:
            break
        if w.endswith((".", "?", "!", ":")) or (w.endswith((",", ";")) and len(cur) >= min_words):
            out.append(line); cur = []
            continue
        too_long = len(cur) >= max_words or len(line + " " + nxt) > max_chars
        if too_long:
            # move weak trailing words to the next chunk
            keep = list(cur)
            carry = []
            while len(keep) > 2 and keep[-1].lower().strip(",.") in WEAK_END:
                carry.insert(0, keep.pop())
            out.append(" ".join(keep)); cur = carry
    if cur:
        if out and len(cur) < 2 and len(out[-1]) + len(cur[0]) < max_chars + 8:
            out[-1] += " " + " ".join(cur)
        else:
            out.append(" ".join(cur))
    return out


def _sub_lines(text, f, d, width=880):
    if d.textlength(text, font=f) <= width:
        return [text]
    words = text.split()
    best = None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        w = max(d.textlength(a, font=f), d.textlength(b, font=f))
        if words[k - 1].lower() in WEAK_END:
            w += 60   # prefer not to break a line after a weak word
        if best is None or w < best[0]:
            best = (w, [a, b])
    return best[1]


def subtitle_img(text):
    img = Image.new("RGBA", (RW, 240), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = D.font("Bold", 52)
    lines = _sub_lines(text, f, d)
    lh = 66
    tw = max(d.textlength(l, font=f) for l in lines)
    top = 30
    x0 = (RW - tw) / 2
    d.rounded_rectangle((x0 - 26, top, x0 + tw + 26, top + 24 + lh * len(lines)), radius=20,
                        fill=(13, 22, 40, 225))
    for j, l in enumerate(lines):
        lw = d.textlength(l, font=f)
        d.text(((RW - lw) / 2, top + 10 + j * lh), l, font=f, fill=D.WHITE)
    return img


def timed_subs(narration, audio_dur):
    cs = chunks(narration)
    total = sum(len(c) for c in cs) or 1
    t, out = 0.0, []
    for c in cs:
        dur = audio_dur * len(c) / total
        out.append((t, t + dur, subtitle_img(c)))
        t += dur
    return out


# ---------------- scene visuals ----------------
def base_canvas(on_screen):
    img = Image.new("RGB", (RW, RH), D.CREAM)
    d = ImageDraw.Draw(img)
    D.mark(d, PX, 120, 44)
    d.text((PX + 60, 126), config.HANDLE, font=D.font("SemiBold", 30), fill=D.MUTED)
    y = D.text_block(d, (PX, 205), on_screen or "", "Bold", RW - 2 * PX, 180, 70, 48, D.INK, spacing=1.12)
    if on_screen:
        d.rectangle((PX, y + 14, PX + 90, y + 22), fill=D.ACCENT)
    return img


def card_panel():
    img = Image.new("RGB", (PW, PH), D.CARD)
    ImageDraw.Draw(img).rounded_rectangle((0, 0, PW - 1, PH - 1), radius=34, outline=D.LINE, width=3)
    return img


def panel_text(headline):
    img = card_panel()
    d = ImageDraw.Draw(img)
    d.rectangle((60, 300, 150, 310), fill=D.ACCENT)
    D.text_block(d, (60, 340), headline, "Bold", PW - 120, 420, 84, 50, D.INK, spacing=1.1)
    return img


def panel_list_states(title, items, numbered):
    """One image per reveal state (0..n items shown)."""
    states = []
    for k in range(len(items) + 1):
        img = card_panel()
        d = ImageDraw.Draw(img)
        tf, tl, tlh = D.fit(d, title or "", "Bold", PW - 100, 140, 48, 34, 1.2)
        th = tlh * len(tl) if title else 0
        per = min(150, (PH - 100 - th) // max(1, len(items)))
        y0 = max(40, (PH - (th + 30 + per * len(items))) // 2)
        y = D.text_block(d, (50, y0), title or "", "Bold", PW - 100, 140, 48, 34, D.INK) + 30 if title else y0
        for i, it in enumerate(items[:k], 1):
            d.rounded_rectangle((40, y, PW - 40, y + per - 16), radius=18, fill=D.CREAM, outline=D.LINE, width=2)
            cy = y + (per - 16) / 2
            if numbered:
                d.ellipse((62, cy - 28, 118, cy + 28), fill=D.ACCENT)
                f = D.font("Bold", 30)
                d.text((90 - d.textlength(str(i), font=f) / 2, cy - 20), str(i), font=f, fill=D.WHITE)
            else:
                D.check_icon(d, 62, int(cy - 26), 52)
            f, lines, lh = D.fit(d, it, "Medium", PW - 220, per - 40, 38, 26, 1.2)
            ty = cy - lh * len(lines) / 2
            for ln in lines:
                d.text((140, ty), ln, font=f, fill=D.INK)
                ty += lh
            y += per
        states.append(img)
    return states


def panel_compare_states(left, right, rows):
    states = []
    colw = (PW - 100) // 2
    for k in range(len(rows) + 1):
        img = card_panel()
        d = ImageDraw.Draw(img)
        f = D.font("Bold", 30)
        per = min(170, (PH - 160) // max(1, len(rows)))
        top = max(40, (PH - (80 + per * len(rows))) // 2)
        for x, lab, bg, fg in ((40, left or "Before", (226, 222, 212), D.INK), (60 + colw, right or "After", D.INK, D.WHITE)):
            d.rounded_rectangle((x, top - 4, x + colw, top + 52), radius=26, fill=bg)
            t = lab.upper()
            d.text((x + (colw - d.textlength(t, font=f)) / 2, top + 6), t, font=f, fill=fg)
        y = top + 80
        for r in rows[:k]:
            for x, txt, fill, bg in ((40, r.get("left", ""), D.INK, D.CREAM),
                                     (60 + colw, r.get("right", ""), D.INK, D.CREAM)):
                d.rounded_rectangle((x, y, x + colw, y + per - 16), radius=18, fill=bg, outline=D.LINE, width=2)
                D.text_block(d, (x + 22, y + 20), txt, "Medium", colw - 44, per - 56, 36, 24, fill, spacing=1.2)
            y += per
        states.append(img)
    return states


def panel_diagram_states(steps):
    steps = steps[:4]
    states = []
    n = len(steps)
    bh = min(170, (PH - 80 - (n - 1) * 60) // max(1, n))
    for k in range(n + 1):
        img = card_panel()
        d = ImageDraw.Draw(img)
        total_h = n * bh + (n - 1) * 60
        y = (PH - total_h) // 2
        for i, s in enumerate(steps[:k]):
            fill = D.INK if i == n - 1 else D.CARD
            col = D.WHITE if i == n - 1 else D.INK
            d.rounded_rectangle((90, y, PW - 90, y + bh), radius=24, fill=fill if i == n - 1 else D.CREAM, outline=D.INK,
                                width=3)
            D.text_block(d, (120, y + (bh - 50) // 2 - 6), s, "Bold", PW - 240, bh - 30, 44, 28, col,
                         spacing=1.15, align="center")
            if i < n - 1 and i < k - 1:
                cx = PW // 2
                d.line((cx, y + bh + 8, cx, y + bh + 50), fill=D.ACCENT, width=6)
                d.polygon([(cx - 16, y + bh + 40), (cx + 16, y + bh + 40), (cx, y + bh + 58)], fill=D.ACCENT)
            y += bh + 60
        states.append(img)
    return states


def screenshot_card(shot, url):
    """Browser-style card: domain bar + real screenshot (scaled to panel width, tall for scrolling)."""
    bar = 70
    s = shot.resize((PW, int(shot.height * PW / shot.width)), Image.LANCZOS)
    card = Image.new("RGB", (PW, bar + s.height), D.CARD)
    d = ImageDraw.Draw(card)
    d.rectangle((0, 0, PW, bar), fill=(236, 236, 240))
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        d.ellipse((24 + i * 30, 26, 42 + i * 30, 44), fill=c)
    d.rounded_rectangle((130, 14, PW - 30, bar - 14), radius=20, fill=D.WHITE)
    d.text((152, 22), visuals.domain(url), font=D.font("Medium", 26), fill=D.MUTED)
    card.paste(s, (0, bar))
    return card


class Scene:
    def __init__(self, sc, duration, subs):
        self.sc, self.dur, self.subs = sc, duration, subs
        head = (sc.get("headline") or "").strip().lower()
        same = sc.get("visual_type") == "text" and head and head == (sc.get("on_screen") or "").strip().lower()
        self.base = base_canvas("" if same else sc.get("on_screen", ""))
        self.kind, self.states, self.tall, self.photo = "text", None, None, None
        self.ai_visual = False
        vt = sc.get("visual_type", "text")
        if vt == "screenshot" and not config.is_news(sc.get("url", "")):
            shot = visuals.screenshot(sc.get("url", ""))
            if shot is not None:
                self.kind, self.tall = "scroll", screenshot_card(shot, sc.get("url", ""))
        elif vt == "photo":
            img, ai = visuals.library(sc.get("query", ""))   # approved library only; no random stock photos
            if img is not None:
                self.kind, self.photo, self.ai_visual = "kenburns", D.cover_crop(img, int(PW * 1.1), int(PH * 1.1)), ai
        elif vt in ("checklist", "diagram", "compare") or sc.get("steps") or sc.get("items") or sc.get("rows"):
            if vt == "compare" and sc.get("rows"):
                self.kind = "staged"
                self.states = panel_compare_states(sc.get("left_label"), sc.get("right_label"), sc["rows"][:4])
            elif vt == "diagram" and sc.get("steps"):
                self.kind, self.states = "staged", panel_diagram_states(sc["steps"])
            elif sc.get("items"):
                self.kind = "staged"
                self.states = panel_list_states(sc.get("headline") or "", sc["items"][:5], numbered=False)
        if self.kind == "text":
            self.states = [panel_text(sc.get("headline") or sc.get("on_screen") or "")]
        self.fallback = vt in ("screenshot", "photo") and self.kind == "text"

    def panel(self, t):
        p = t / max(self.dur, 0.01)
        if self.kind == "scroll":
            max_scroll = max(0, min(self.tall.height - PH, 380))
            y = int(max_scroll * min(1.0, max(0.0, (p - 0.25) / 0.7)))
            return self.tall.crop((0, y, PW, y + PH))
        if self.kind == "kenburns":
            z = 1.0 + 0.08 * p
            w, h = int(self.photo.width / z / 1.1 * 1.0), int(self.photo.height / z / 1.1 * 1.0)
            x0, y0 = (self.photo.width - w) // 2, (self.photo.height - h) // 2
            return self.photo.crop((x0, y0, x0 + w, y0 + h)).resize((PW, PH), Image.BILINEAR)
        if self.kind == "staged":
            n = len(self.states) - 1
            k = min(n, 1 + int(p * n / 0.75)) if n else 0
            return self.states[k]
        z = 1.0 + 0.03 * p
        st = self.states[0]
        w, h = int(PW / z), int(PH / z)
        return st.crop(((PW - w) // 2, (PH - h) // 2, (PW - w) // 2 + w, (PH - h) // 2 + h)).resize((PW, PH))

    def frame(self, t):
        img = self.base.copy()
        D.rounded_paste(img, self.panel(t), (PX, PY), 34)
        for a, b, sub in self.subs:
            if a <= t < b:
                img.paste(sub, (0, SUB_Y - 80), sub)
                break
        return img


def build(script, out_path, preview_dir=None):
    """Render the reel. Returns metadata for QC and the report."""
    tmp = tempfile.mkdtemp(prefix="reel2_")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    scenes = script["scenes"]
    lines = [s["narration"].strip() for s in scenes]
    wavs, adurs, engine = voice_lines(lines, tmp)
    durs = [round(a + TAIL, 2) for a in adurs]
    audio = os.path.join(tmp, "voice.wav")
    concat_audio(wavs, durs, audio)

    objs = [Scene(sc, d, timed_subs(sc["narration"], a)) for sc, d, a in zip(scenes, durs, adurs)]
    proc = subprocess.Popen([ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-", "-i", audio,
                             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                             "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest",
                             "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)
    previews = []
    for i, sc in enumerate(objs):
        n = int(round(sc.dur * FPS))
        for f in range(n):
            t = f / FPS
            fr = sc.frame(t)
            proc.stdin.write(fr.tobytes())
            if preview_dir and f == int(n * 0.7):
                os.makedirs(preview_dir, exist_ok=True)
                p = os.path.join(preview_dir, f"scene_{i + 1:02d}.jpg")
                fr.resize((540, 960)).save(p, "JPEG", quality=85)
                previews.append(p)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return {"duration": round(sum(durs), 1), "voice": engine, "scene_previews": previews,
            "fallback_visuals": sum(o.fallback for o in objs), "ai_visuals": any(o.ai_visual for o in objs),
            "scene_durations": durs}
