"""AI presenter "Arjun".

Daily flow
1. plan():    after production, the best approved Reel becomes the Arjun Reel. A "director" prompt designs it
              start to end: 3 spoken Arjun shots (hook, point, payoff + comment hook) with varied camera framing
              and acting notes, plus 2 silent B-roll cutaways. Every shot gets a ready-to-paste Gemini (Veo) prompt.
2. process(): at 7 PM the bot sends the shot prompts on Telegram; the owner replies to each with the video.
3. compose(): when all shots are in, the bot transcribes Arjun's lines, trims dead air, cuts the B-roll in over
              his voice, adds subtitles, a hook title, a comment-hook card and an "AI presenter" label, runs the
              quality gate and swaps the result in for publishing.
If shots are missing PRESENTER_GRACE_MIN minutes after the slot, the normal (non-Arjun) Reel is posted.
"""
import datetime as dt
import json
import os
import re
import subprocess
import tempfile
import wave

from PIL import Image, ImageDraw

import config
import design as D
import llm
import qc
import reel
import telegram

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
RW, RH, FPS = reel.RW, reel.RH, reel.FPS

LOOK = ("Keep his face, hair, beard, navy overshirt, white t-shirt and the plain cream background exactly the same "
        "as the photo.")
VOICE = ("a warm, confident young Indian male voice speaking natural Hinglish (Hindi-English mix) with a natural "
         "Indian accent, at a lively but clear pace")
CAMERAS = ["close-up, camera steady at eye level",
           "medium close-up with a slow, smooth push-in towards his face",
           "medium shot from slightly to his left (about 20 degrees), camera steady",
           "medium shot from slightly to his right (about 20 degrees), camera steady"]

STORY_SCHEMA = {"type": "OBJECT", "properties": {
    "hook_title": {"type": "STRING"}, "cta_text": {"type": "STRING"},
    "talks": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "line": {"type": "STRING"}, "camera": {"type": "INTEGER"}, "action": {"type": "STRING"},
        "broll": {"type": "STRING"}},
        "required": ["line", "camera", "action", "broll"]}}},
    "required": ["hook_title", "cta_text", "talks"]}

DIRECT = """You are the director and head writer of a top Indian Instagram creator channel about practical AI for
small-business owners. Design ONE complete Reel, start to end, presented by Arjun (a friendly young Indian tech
advisor, always filmed in front of the same plain cream wall in a navy overshirt and white t-shirt).

The Reel is made of exactly {n} spoken shots. Each shot is ONE 8-second video clip of Arjun talking to camera.
Some shots also get a B-roll cutaway: a separate silent 8-second clip that plays for about 3 seconds in the
middle of that shot while Arjun's voice continues (a classic creator edit).

STORY
- Shot 1 = the hook: stops the scroll in 2 seconds (a specific problem, surprise or strong claim). No B-roll.
- Middle shot(s) = the single most useful, concrete point (a step, a setting, a clear rule).
- Last shot = the payoff + the comment hook: "Comment {keyword}, main aapko ___ DM kar dunga".
- The shots must flow as ONE continuous talk: each line follows naturally from the previous one.

FOR EACH SHOT
- line: HINGLISH in Roman script, 12-19 words (one breath, 8 seconds). Sounds like a sharp, friendly human creator.
  Contractions, plain words, no hype. Banned: {banned}. Only facts from the script/source; no invented numbers.
- camera: index of the framing that best suits the line, varied from shot to shot:
  {cameras}
- action: ONE short, natural acting note for Arjun (e.g. "raises one finger when he says the key word",
  "leans in slightly and lowers his voice", "smiles and shrugs lightly"). Different in every shot.
- broll: for shot 1 always "". For shots 2-{n}, a SPECIFIC, realistic cutaway that shows what he is talking about,
  in an Indian small-business setting, WITHOUT any person's face and WITHOUT readable text, logos or brand names
  (e.g. "close-up of a shopkeeper's hands typing on a laptop next to a stack of paper invoices on a wooden counter",
  "over-the-shoulder shot of a phone on a shop counter lighting up with new message notifications"). One sentence.
  Give a B-roll to at most {brolls} shots; use "" for the others.

Also: hook_title = 2-5 big words shown on screen during the first 2 seconds (Hinglish or English).
cta_text = 3-6 words shown on screen at the end, e.g. "Comment {keyword} for the list".

SCRIPT SCENES (narration of the approved Reel this is based on):
{scenes}

SOURCE MATERIAL:
{material}"""


def veo_talk_prompt(line, camera, action):
    cam = CAMERAS[camera] if 0 <= camera < len(CAMERAS) else CAMERAS[0]
    act = action.strip().rstrip(".") or "He speaks with natural head movements"
    act = act[0].upper() + act[1:]
    return (f"Animate this exact photo into a realistic vertical 9:16 video of about 8 seconds. {LOOK} "
            f"Camera: {cam}. {act}. Natural blinks, realistic skin and teeth, soft natural "
            f"lighting. He speaks in {VOICE}, saying exactly: \"{line}\" "
            f"No subtitles, no on-screen text, no music, no other people.")


def veo_broll_prompt(desc):
    return (f"Create a realistic vertical 9:16 video of about 8 seconds: {desc.strip().rstrip('.')}. "
            f"Indian small-business setting, warm natural light, handheld smartphone-camera look, slow subtle "
            f"camera movement, shallow depth of field. No faces, no readable text, no brand names or logos, "
            f"no subtitles, no speech, no music.")


def veo_prompt(line, n):                                   # kept for the one-off test command
    return veo_talk_prompt(line, (n - 1) % len(CAMERAS), "He speaks with natural head movements and one light gesture")


TRANSCRIBE_SCHEMA = {"type": "OBJECT", "properties": {
    "clips": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "transcript": {"type": "STRING"}, "matches": {"type": "BOOLEAN"}, "problem": {"type": "STRING"}},
        "required": ["transcript", "matches", "problem"]}}},
    "required": ["clips"]}


def photo_path():
    d = config.PRESENTER_PHOTO_DIR
    if not os.path.isdir(d):
        return None
    files = sorted(f for f in os.listdir(d) if f.lower().endswith((".png", ".jpg", ".jpeg")))
    return os.path.join(d, files[0]) if files else None


def _short(e):
    return e["id"].split("-")[0]


# ---------------------------------------------------------------- 1. plan
def plan(results, queue_entries):
    """Choose Arjun Reels among today's queued Reels, re-slot them to the evening, send prompts. Saves the queue."""
    import publisher
    if config.PRESENTER_REELS <= 0 or not photo_path():
        return []
    q = publisher.load()
    ids = {e["id"] for e in queue_entries if e["kind"] == "reel"}
    reels = [e for e in q if e["id"] in ids]
    if not reels:
        return []
    by_id = {r["id"]: r for r in results}
    reels.sort(key=lambda e: -sum(e["scores"].values()))
    chosen = reels[:config.PRESENTER_REELS]
    others = reels[config.PRESENTER_REELS:]
    date = reels[0]["date"]
    pres_slots = list(config.PRESENTER_SLOTS)[:len(chosen)]
    other_slots = [s for s in config.REEL_SLOTS if s not in pres_slots]
    for e, s in zip(others, other_slots):
        e["slot"] = f"{date}T{s}"
    planned = []
    for e, s in zip(chosen, pres_slots):
        e["slot"] = f"{date}T{s}"
        r = by_id.get(e["id"], {})
        try:
            takes, hook_title, cta = _adapt(r.get("piece", {}), r.get("material", ""))
        except Exception as ex:
            print("[presenter] could not design the Arjun Reel", e["id"], ex)
            continue
        e["presenter"] = {"status": "waiting", "takes": takes, "material": (r.get("material") or "")[:8000],
                          "scenes": r.get("piece", {}).get("scenes", []), "composed_from": None,
                          "hook_title": hook_title, "cta": cta}
        planned.append(e)
    publisher.save(q)                     # prompts are sent later, at PRESENTER_PROMPT_TIME (see process)
    return planned


def _adapt(piece, material):
    """Designs the whole Arjun Reel (storyboard) and returns the shot list with ready Gemini prompts."""
    scenes = piece.get("scenes", [])
    keyword = piece.get("dm_keyword") or "KEYWORD"
    listing = "\n".join(f"{i + 1}. {s.get('narration')}" for i, s in enumerate(scenes))
    res = llm.generate_json(DIRECT.format(n=config.PRESENTER_TALKS, brolls=config.PRESENTER_BROLLS, keyword=keyword,
                                          banned=", ".join(config.BANNED[:20]),
                                          cameras="\n  ".join(f"{i}: {c}" for i, c in enumerate(CAMERAS)),
                                          scenes=listing, material=material[:6000]),
                            STORY_SCHEMA, temperature=0.7)
    talks = res.get("talks", [])[:config.PRESENTER_TALKS]
    if len(talks) < 2:
        raise RuntimeError("storyboard has too few shots")
    shots, n_broll = [], 0
    for i, t in enumerate(talks, 1):
        line = re.sub(r"\s+", " ", t["line"]).strip().strip('"')
        shots.append({"n": len(shots) + 1, "kind": "talk", "talk": i, "line": line, "visual_scene": -1,
                      "prompt": veo_talk_prompt(line, t.get("camera", 0), t.get("action") or ""),
                      "msg_id": None, "file": None, "got_msg": None})
        desc = (t.get("broll") or "").strip()
        if i > 1 and desc and n_broll < config.PRESENTER_BROLLS:
            n_broll += 1
            shots.append({"n": len(shots) + 1, "kind": "broll", "cover": i, "desc": desc,
                          "prompt": veo_broll_prompt(desc), "msg_id": None, "file": None, "got_msg": None})
    return shots, (res.get("hook_title") or "").strip(), (res.get("cta_text") or f"Comment {keyword}").strip()


def _send_prompts(planned):
    total = sum(len(e["presenter"]["takes"]) for e in planned)
    times = ", ".join(f"{_short(e)} at {e['slot'][-5:]}" for e in planned)
    telegram.send_text(
        f"ARJUN SHOTS FOR TONIGHT: {len(planned)} Reel(s), {total} video clips ({times} IST).\n\n"
        "Each message below is ONE shot of the Reel, in story order. For each one:\n"
        "1. Open Gemini (Pro account) and choose Video. Portrait / 9:16.\n"
        "2. ARJUN shots: attach Arjun's photo (file below). B-ROLL shots: do NOT attach any photo.\n"
        "3. Copy the prompt (long-press > Copy), paste it in Gemini and generate.\n"
        "4. Download the video, then REPLY to that shot's message with the video.\n"
        "   (If you forget to reply, just send the videos in the same order as the shots.)\n\n"
        "The bot edits all shots into one Reel: Arjun's voice runs through, B-roll cuts in over it, "
        "subtitles, title and comment hook are added, then the quality check runs.\n"
        f"If shots are missing {config.PRESENTER_GRACE_MIN} min after the Reel's time, the normal version posts.")
    try:
        telegram.send_photo(photo_path(), "Arjun's photo: attach this ONLY for the ARJUN shots.")
    except Exception as ex:
        print("[presenter] photo send failed:", ex)
    for e in planned:
        n_all = len(e["presenter"]["takes"])
        for t in e["presenter"]["takes"]:
            if t.get("kind") == "broll":
                what = f"B-ROLL (no photo) · plays over shot {_talk_shot_no(e, t['cover'])}"
            else:
                what = "ARJUN TALKING (attach Arjun's photo)"
            head = f"{_short(e)} · SHOT {t['n']} of {n_all} · {what}\nReply to this message with the video.\n\n"
            t["msg_id"] = telegram.send_text(head + t["prompt"])


def _talk_shot_no(e, talk_index):
    for t in e["presenter"]["takes"]:
        if t.get("kind", "talk") == "talk" and t.get("talk", t["n"]) == talk_index:
            return t["n"]
    return talk_index


# ---------------------------------------------------------------- 2. collect
def _video_of(m):
    if m.get("video"):
        return m["video"]
    doc = m.get("document") or {}
    if (doc.get("mime_type") or "").startswith("video/"):
        return doc
    return None


def collect(q, today):
    """Saves clips the owner sent. Returns True if anything changed."""
    waiting = [e for e in q if e.get("presenter") and e["date"] == today
               and e["presenter"]["status"] in ("waiting", "rejected") and e["status"] == "queued"]
    if not waiting:
        return False
    try:
        msgs = telegram.owner_updates()
    except Exception as ex:
        print("[presenter] telegram read failed:", ex)
        return False
    by_msg = {t["msg_id"]: (e, t) for e in waiting for t in e["presenter"]["takes"] if t.get("msg_id")}
    seen = {t.get("got_msg") for x in q if x.get("presenter") for t in x["presenter"]["takes"] if t.get("got_msg")}
    seen |= {i for x in q if x.get("presenter") for i in x["presenter"].get("seen", [])}
    changed = False
    for m in sorted(msgs, key=lambda x: x.get("message_id", 0)):
        v = _video_of(m)
        if not v or m.get("message_id") in seen:
            continue
        target = by_msg.get((m.get("reply_to_message") or {}).get("message_id"))
        if not target:                                   # fallback: caption like "R1 2" or "r1 clip 2"
            mm = re.search(r"\b(r\d)\D{0,8}(\d)\b", (m.get("caption") or "").lower())
            if mm:
                for e in waiting:
                    if _short(e).lower() == mm.group(1):
                        for t in e["presenter"]["takes"]:
                            if t["n"] == int(mm.group(2)):
                                target = (e, t)
        if not target:                                   # fallback: plain video (no reply/caption) → next missing clip
            sent_at = min((x["presenter"].get("prompts_sent_at") or 0) for x in waiting)
            if sent_at and m.get("date", 0) >= sent_at:
                for e in sorted(waiting, key=lambda x: x["slot"]):
                    for t in e["presenter"]["takes"]:
                        if not t.get("file") and not t.get("got_msg"):
                            target = (e, t)
                            break
                    if target:
                        break
        if not target:
            continue
        e, t = target
        if t.get("got_msg") and t["got_msg"] >= m["message_id"]:
            continue
        if (v.get("file_size") or 0) > 20_000_000:
            telegram.send_text(f"{_short(e)} clip {t['n']}: that file is over 20 MB, which Telegram bots can't "
                               "download. Please send it again as a normal video (not as a file).")
            seen.add(m["message_id"])
            e["presenter"].setdefault("seen", []).append(m["message_id"])
            changed = True
            continue
        dest = os.path.join(config.ROOT, os.path.dirname(e["dir"]), "arjun", f"clip{t['n']}_{m['message_id']}.mp4")
        try:
            telegram.download(v["file_id"], dest)
        except Exception as ex:
            print("[presenter] download failed:", ex)
            continue
        t["file"] = os.path.relpath(dest, config.ROOT)
        t["got_msg"] = m["message_id"]
        seen.add(m["message_id"])
        changed = True
        have = sum(1 for x in e["presenter"]["takes"] if x.get("file"))
        need = len(e["presenter"]["takes"])
        telegram.send_text(f"Got {_short(e)} shot {t['n']} ({have}/{need})." +
                           (" All clips in, editing the Reel now." if have == need else ""))
    return changed


# ---------------------------------------------------------------- 3. compose
def _ff(args, **kw):
    return subprocess.run([reel.ffmpeg(), "-y", "-loglevel", "error", *args], check=True, **kw)


def _duration(path):
    out = subprocess.run([reel.ffmpeg(), "-i", path], capture_output=True, text=True).stderr
    mm = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(mm.group(1)) * 3600 + int(mm.group(2)) * 60 + float(mm.group(3)) if mm else 0.0


def _speech_span(wav_path):
    """(start, end) seconds of speech by simple energy detection."""
    with wave.open(wav_path) as w:
        rate, n = w.getframerate(), w.getnframes()
        data = w.readframes(n)
    import array
    a = array.array("h", data)
    win = int(rate * 0.05)
    levels = [max(1, sum(abs(x) for x in a[i:i + win]) // win) for i in range(0, len(a), win)]
    if not levels:
        return 0.0, n / rate
    thr = max(levels) * 0.12
    idx = [i for i, v in enumerate(levels) if v >= thr]
    if not idx:
        return 0.0, n / rate
    return idx[0] * 0.05, min(n / rate, (idx[-1] + 1) * 0.05 + 0.1)


def _frames(path, w, h):
    """Yields RGB frames of a clip scaled to cover w x h at FPS."""
    p = subprocess.Popen([reel.ffmpeg(), "-loglevel", "error", "-i", path, "-vf",
                          f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    size = w * h * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield Image.frombytes("RGB", (w, h), buf)
    p.wait()


def _ai_tag():
    img = Image.new("RGBA", (300, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = D.font("SemiBold", 28)
    t = "AI presenter"
    tw = d.textlength(t, font=f)
    d.rounded_rectangle((300 - tw - 44, 6, 300, 58), radius=26, fill=(13, 22, 40, 170))
    d.text((300 - tw - 22, 15), t, font=f, fill=D.WHITE)
    return img


def _handle_badge():
    img = Image.new("RGBA", (420, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = D.font("SemiBold", 28)
    tw = d.textlength(config.HANDLE, font=f)
    d.rounded_rectangle((0, 6, tw + 96, 58), radius=26, fill=(13, 22, 40, 170))
    D.mark(d, 12, 13, 38)
    d.text((62, 15), config.HANDLE, font=f, fill=D.WHITE)
    return img


def _title_card(text):
    """Big white hook title shown at the top during the first seconds of the Reel."""
    text = (text or "").strip()
    if not text:
        return None
    img = Image.new("RGBA", (RW, 330), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f, lines, lh = D.fit(d, text, "Bold", RW - 200, 230, 76, 48, 1.15)
    tw = max(d.textlength(l, font=f) for l in lines)
    h = lh * len(lines)
    x0 = (RW - tw) / 2
    d.rounded_rectangle((x0 - 36, 30, x0 + tw + 36, 30 + h + 40), radius=28, fill=(255, 255, 255, 240))
    y = 48
    for l in lines:
        d.text(((RW - d.textlength(l, font=f)) / 2, y), l, font=f, fill=D.INK)
        y += lh
    d.rectangle(((RW - 90) / 2, 30 + h + 40 - 12, (RW + 90) / 2, 30 + h + 40 - 4), fill=D.ACCENT)
    return img


def _split_panel(scene, dur):
    """A Scene object for the top half (diagram/checklist/compare from the original script)."""
    return reel.Scene(scene, dur, [])


def _transcribe(e, wavs):
    takes = e["presenter"]["takes"]
    prompt = ("These audio clips are, in order, takes of an Instagram presenter speaking Hinglish. For each clip give "
              "the exact transcript (Hindi words in Roman script, as Indians type on WhatsApp), whether it matches the intended line closely (same meaning, nearly same words), and a "
              "short problem note if not (empty string if fine).\n\n" +
              "\n".join(f"Clip {t['n']} intended line: {t['line']}" for t in takes))
    blobs = []
    for w in wavs:
        with open(w, "rb") as f:
            blobs.append(f.read())
    return llm.generate_json(prompt, TRANSCRIBE_SCHEMA, audio=blobs, temperature=0.0).get("clips", [])


def compose(e):
    """Edits all shots into one Reel. Returns (ok, reasons, meta)."""
    pres = e["presenter"]
    takes = pres["takes"]
    talks = [t for t in takes if t.get("kind", "talk") == "talk"]
    brolls = {t["cover"]: t for t in takes if t.get("kind") == "broll" and t.get("file")}
    tmp = tempfile.mkdtemp(prefix="arjun_")
    clips, wavs, spans = [], [], []
    for t in talks:
        src = os.path.join(config.ROOT, t["file"])
        wav = os.path.join(tmp, f"a{t['n']}.wav")
        _ff(["-i", src, "-vn", "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", wav])
        clips.append(src)
        wavs.append(wav)
        spans.append(_speech_span(wav))
    try:
        trans = _transcribe({"presenter": {"takes": talks}}, wavs)
    except Exception as ex:
        trans = []
        print("[presenter] transcription unavailable:", ex)
    lines, problems = [], []
    for i, t in enumerate(talks):
        tr = trans[i] if i < len(trans) else {}
        lines.append((tr.get("transcript") or "").strip() or t["line"])
        if tr and not tr.get("matches", True):
            problems.append(f"shot {t['n']}: {tr.get('problem') or 'says something different from the prompt'}")

    out_dir = os.path.join(config.ROOT, os.path.dirname(e["dir"]), "arjun", "edit")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "reel.mp4")
    # trim each talk clip to its speech (+ small breath) so the Reel flows without dead air
    cuts = [(max(0.0, s0 - 0.15), min(_duration(c), s1 + 0.25)) for c, (s0, s1) in zip(clips, spans)]
    trimmed = []
    for i, (w, (a, b)) in enumerate(zip(wavs, cuts)):
        tw = os.path.join(tmp, f"t{i}.wav")
        _ff(["-i", w, "-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", tw])
        trimmed.append(tw)
    durs = [max(0.8, b - a) for a, b in cuts]
    audio = os.path.join(tmp, "voice.wav")
    reel.concat_audio(trimmed, durs, audio)

    tag, badge = _ai_tag(), _handle_badge()
    title = _title_card(pres.get("hook_title") or "")
    cta = _title_card(pres.get("cta") or "")
    enc = subprocess.Popen([reel.ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-", "-i", audio,
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest",
                            "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)
    previews = []
    img = None
    for i, (t, clip, d, (a, b), text) in enumerate(zip(talks, clips, durs, cuts, lines)):
        speech0 = spans[i][0] - a
        subs = [(x + speech0, y + speech0, im) for x, y, im in reel.timed_subs(text, max(0.5, spans[i][1] - spans[i][0]))]
        zoom = 1.12 if i % 2 else 1.0                     # alternate punch-in between Arjun shots
        br = brolls.get(t.get("talk", i + 1))
        b0 = b1 = -1
        bframes = None
        if br:                                            # cutaway in the middle of the line, max 3.2 s
            b0 = max(0.6, d * 0.30)
            b1 = min(d - 0.8, b0 + 3.2)
            bframes = _frames(os.path.join(config.ROOT, br["file"]), RW, RH)
        n_frames = int(round(d * FPS))
        k = 0
        for fr in _frames_from(clip, a, RW, RH):
            if k >= n_frames:
                break
            tt = k / FPS
            if bframes is not None and b0 <= tt < b1:
                bf = next(bframes, None)
                img = bf.copy() if bf is not None else fr.copy()
            elif zoom != 1.0:
                w, h = int(RW / zoom), int(RH / zoom)
                x0, y0 = (RW - w) // 2, int((RH - h) * 0.35)
                img = fr.crop((x0, y0, x0 + w, y0 + h)).resize((RW, RH), Image.LANCZOS)
            else:
                img = fr.copy()
            if i == 0 and title is not None and tt < 2.4:
                img.paste(title, (0, 150), title)
            if i == len(talks) - 1 and cta is not None and tt > d - 2.4:
                img.paste(cta, (0, 150), cta)
            img.paste(badge, (40, 60), badge)
            img.paste(tag, (RW - 340, 60), tag)
            for x, y, sub in subs:
                if x <= tt < y:
                    img.paste(sub, (0, reel.SUB_Y - 80), sub)
                    break
            enc.stdin.write(img.tobytes())
            if k == int(n_frames * 0.5) or (bframes is not None and k == int((b0 + 0.8) * FPS)):
                pv = os.path.join(out_dir, f"shot_{t['n']:02d}_{k}.jpg")
                img.resize((540, 960)).save(pv, "JPEG", quality=85)
                previews.append(pv)
            k += 1
        if k == 0:
            raise RuntimeError(f"shot {t['n']} has no readable video frames")
        while k < n_frames:
            enc.stdin.write(img.tobytes())
            k += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg failed while editing the Arjun Reel")

    piece = {"scenes": [{"narration": txt, "on_screen": "", "visual_type": "presenter"} for txt in lines],
             "caption": e["caption"]}
    rev = qc.review(piece, "reel", pres.get("material", ""), previews)
    ok, reasons = qc.verdict([], rev)
    reasons = problems + reasons
    ok = ok and not problems
    meta = {"dir": os.path.relpath(out_dir, config.ROOT), "duration": round(sum(durs), 1), "scores": rev["scores"],
            "previews": [os.path.relpath(p, config.ROOT) for p in previews], "transcripts": lines,
            "visual_issues": rev.get("visual_issues", [])}
    return ok, reasons, meta


def _frames_from(path, start, w, h):
    """Like _frames, but starting at the start seconds."""
    p = subprocess.Popen([reel.ffmpeg(), "-loglevel", "error", "-ss", f"{start:.2f}", "-i", path, "-vf",
                          f"fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    size = w * h * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield Image.frombytes("RGB", (w, h), buf)
    p.wait()


def _with_ai_note(caption):
    note = "(Presenter is an AI-generated character.)"
    if note in caption:
        return caption
    parts = caption.rsplit("\n\n", 1)
    if len(parts) == 2 and parts[1].strip().startswith("#"):
        return f"{parts[0]}\n\n{note}\n\n{parts[1]}"
    return f"{caption}\n\n{note}"


def process(q, today):
    """send the evening prompts, then collect + compose. Returns True if the queue changed."""
    changed = False
    now = dt.datetime.now(IST).strftime("%H:%M")
    due = [e for e in q if e.get("presenter") and e["date"] == today and e["status"] == "queued"
           and e["presenter"]["status"] == "waiting" and not e["presenter"].get("prompts_sent")]
    if due and now >= config.PRESENTER_PROMPT_TIME:
        try:
            _send_prompts(due)
            for e in due:
                e["presenter"]["prompts_sent"] = True
                e["presenter"]["prompts_sent_at"] = int(dt.datetime.now(IST).timestamp())
        except Exception as ex:
            print("[presenter] could not send prompts:", ex)
        changed = True
    changed = collect(q, today) or changed
    for e in q:
        pres = e.get("presenter")
        if not pres or e["date"] != today or e["status"] != "queued" or pres["status"] not in ("waiting", "rejected"):
            continue
        files = [t.get("file") for t in pres["takes"]]
        if not all(files) or pres.get("composed_from") == files:
            continue
        pres["composed_from"] = files
        changed = True
        try:
            ok, reasons, meta = compose(e)
        except Exception as ex:
            pres["status"] = "rejected"
            pres["last_error"] = str(ex)[:300]
            telegram.send_text(f"{_short(e)}: I couldn't edit the Arjun clips ({str(ex)[:200]}). The normal version "
                               "will post unless you send a new clip.")
            continue
        pres["meta"] = meta
        short = _short(e)
        if ok:
            pres["status"] = "ready"
            e["normal_dir"] = e["dir"]
            e["dir"] = meta["dir"]
            e["files"] = ["reel.mp4"]
            e["caption"] = _with_ai_note(e["caption"])
            e["scores"] = meta["scores"]
            try:
                telegram.send_video(os.path.join(config.ROOT, meta["dir"], "reel.mp4"),
                                    f"{short} Arjun version is ready and passed the quality check. "
                                    f"Posting at {e['slot'][-5:]} IST. Reply 'stop {short}' to cancel.")
            except Exception as ex:
                print("[presenter] preview failed:", ex)
        else:
            pres["status"] = "rejected"
            msg = (f"{short} Arjun version did NOT pass the quality check:\n- " + "\n- ".join(reasons[:5]) +
                   "\n\nSend a new clip as a reply to the matching prompt message to try again. "
                   "Otherwise the normal version posts.")
            try:
                telegram.send_video(os.path.join(config.ROOT, meta["dir"], "reel.mp4"), msg[:1000])
            except Exception:
                telegram.send_text(msg)
    return changed


def effective_slot(e):
    """Arjun Reels still waiting for clips get a grace period after their slot."""
    pres = e.get("presenter")
    if not pres or pres["status"] == "ready":
        return e["slot"]
    t = dt.datetime.strptime(e["slot"], "%Y-%m-%dT%H:%M") + dt.timedelta(minutes=config.PRESENTER_GRACE_MIN)
    return t.strftime("%Y-%m-%dT%H:%M")
