"""Turn the day's carousel slides into a 1080x1920 Reel with an Indian-English voiceover."""
import asyncio
import os
import subprocess
import tempfile
import wave

from PIL import Image, ImageDraw

import render

RW, RH = 1080, 1920
VOICE = os.environ.get("REEL_VOICE", "en-IN-PrabhatNeural")  # Indian English, male
FADE = 0.4      # seconds of cross-fade between slides
PAD = 0.6       # silence after each spoken line
MIN_SLIDE = 2.5  # seconds, if there is no voice


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", *args], check=True)


# ---------- frames ----------
def vertical_frame(slide_path, out_path):
    """Place a 1080x1350 slide in the middle of a branded 1080x1920 frame."""
    canvas = render.base().resize((RW, RH))
    slide = Image.open(slide_path).convert("RGB")
    # hide the carousel-only "Swipe for more" footer (not relevant in a video)
    sd = ImageDraw.Draw(slide)
    bg = slide.getpixel((560, slide.height - 95))
    sd.rectangle((560, slide.height - 125, slide.width, slide.height - 65), fill=bg)
    top = (RH - slide.height) // 2 - 40
    canvas.paste(slide, (0, top))
    d = ImageDraw.Draw(canvas)
    f = render.font("Bold", 34)
    t = render.TAGLINE
    tw = d.textlength(t, font=f)
    d.text(((RW - tw) / 2, top - 90), t, font=f, fill=render.SAFFRON)
    f2 = render.font("Medium", 36)
    t2 = f"Follow {render.HANDLE} for daily AI tips"
    tw2 = d.textlength(t2, font=f2)
    d.text(((RW - tw2) / 2, top + slide.height + 40), t2, font=f2, fill=render.WHITE)
    canvas.save(out_path, "JPEG", quality=92)


# ---------- voice ----------
def speech_lines(post):
    lines = [post["hook"]]
    for s in post["slides"]:
        lines.append(f"{s['title']}. {s['text']}")
    lines.append("Found this useful? Follow us for daily A I tips for Indian businesses.")
    return lines


async def _edge(text, path):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="+5%").save(path)


def tts(text, mp3_path):
    """edge-tts (male en-IN) first, gTTS (en, India) as fallback. Returns True if audio made."""
    try:
        asyncio.run(_edge(text, mp3_path))
        if os.path.getsize(mp3_path) > 1000:
            return True
    except Exception as ex:
        print("[reel] edge-tts failed:", ex)
    try:
        from gtts import gTTS
        gTTS(text, lang="en", tld="co.in").save(mp3_path)
        return True
    except Exception as ex:
        print("[reel] gTTS failed:", ex)
    return False


def wav_seconds(path):
    with wave.open(path) as w:
        return w.getnframes() / float(w.getframerate())


# ---------- build ----------
def build_reel(post, slide_paths, out_path, voice=True):
    tmp = tempfile.mkdtemp(prefix="reel_")
    lines = speech_lines(post)
    assert len(lines) == len(slide_paths), "slides and speech lines must match"
    frames, durs, wavs = [], [], []
    have_voice = voice
    for i, (line, sp) in enumerate(zip(lines, slide_paths)):
        fp = os.path.join(tmp, f"f{i:02d}.jpg")
        vertical_frame(sp, fp)
        frames.append(fp)
        wav = os.path.join(tmp, f"a{i:02d}.wav")
        mp3 = os.path.join(tmp, f"a{i:02d}.mp3")
        if have_voice and tts(line, mp3):
            run(["-i", mp3, "-ar", "44100", "-ac", "2", wav])
            d = wav_seconds(wav) + PAD
        else:
            have_voice = False
            d = MIN_SLIDE + 0.08 * len(line.split())
        durs.append(round(max(d, MIN_SLIDE), 2))
        wavs.append(wav)

    # audio track: each line padded to exactly its slide's duration
    audio = os.path.join(tmp, "voice.wav")
    if have_voice:
        padded = []
        for i, (w, d) in enumerate(zip(wavs, durs)):
            p = os.path.join(tmp, f"p{i:02d}.wav")
            run(["-i", w, "-af", "apad", "-t", f"{d}", "-ar", "44100", "-ac", "2", p])
            padded.append(p)
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{p}'\n" for p in padded)
        run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", audio])
    else:  # silent track (Instagram is happier with an audio stream present)
        run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{sum(durs)}", audio])

    # video: each image held for its duration (+fade overlap), chained with cross-fades
    inputs, n = [], len(frames)
    for i, (fp, d) in enumerate(zip(frames, durs)):
        length = d + (FADE if i < n - 1 else 0)
        inputs += ["-loop", "1", "-t", f"{length:.2f}", "-framerate", "30", "-i", fp]
    chains, prev, offset = [], "[0:v]", 0.0
    for i in range(1, n):
        offset += durs[i - 1]
        out = f"[v{i}]"
        chains.append(f"{prev}[{i}:v]xfade=transition=fade:duration={FADE}:offset={offset:.2f}{out}")
        prev = out
    graph = ";".join(chains) + f";{prev}format=yuv420p,scale={RW}:{RH}[vout]" if chains else \
        f"[0:v]format=yuv420p,scale={RW}:{RH}[vout]"
    run([*inputs, "-i", audio, "-filter_complex", graph, "-map", "[vout]", "-map", f"{n}:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "26", "-r", "30", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out_path])
    total = sum(durs)
    print(f"[reel] {out_path} ({total:.1f}s, voice={'yes' if have_voice else 'no'})")
    return out_path
