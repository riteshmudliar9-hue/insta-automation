"""AI presenter "Arjun".

Daily flow
1. plan():   after production, the best approved Reels become Arjun Reels. Each script is rewritten into
             PRESENTER_TAKES short lines (one 8-second clip each). The bot sends the owner one Telegram message
             per clip with a ready-to-paste Gemini (Veo) prompt. These Reels move to the evening slots.
2. collect(): every publish run reads the owner's Telegram replies. A video sent as a reply to a prompt
             message (or captioned like "R1 2") is saved as that clip.
3. compose(): when all clips of a Reel are in, the bot transcribes them, builds the final edit
             (Arjun full screen → split screen with the Reel's diagrams → Arjun full screen), adds subtitles
             and an "AI presenter" label, runs the quality gate and swaps it in for publishing.
If clips are missing PRESENTER_GRACE_MIN minutes after the slot, the normal (non-Arjun) Reel is posted.
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
ACTING = [
    "He looks straight into the camera with a small knowing smile, then speaks with energy, leaning in slightly.",
    "He explains like a friendly expert, with small natural head movements and one light open-hand gesture.",
    "He speaks calmly and sincerely, nods slightly at the end and gives a small smile.",
    "He counts a point on his fingers once while talking, relaxed and natural.",
]

TAKES_SCHEMA = {"type": "OBJECT", "properties": {
    "takes": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "line": {"type": "STRING"}, "visual_scene": {"type": "INTEGER"}},
        "required": ["line", "visual_scene"]}}},
    "required": ["takes"]}

ADAPT = """You are the head writer for a top Instagram creator who explains practical AI to Indian small-business
owners. Turn this Reel script into exactly {n} lines spoken to camera by the presenter, Arjun, in natural
HINGLISH (Roman script), the way a smart young Indian creator talks.

RULES
- Each line is ONE 8-second clip: 12-19 words, one or two short sentences, easy to say in one breath.
- Line 1 is the hook: stop the scroll in the first 2 seconds (a specific problem, surprise or strong claim).
- Middle line(s): the single most useful, concrete point (a step, a setting, a number or a clear rule).
- Last line: the payoff plus the comment hook from the script ("Comment {keyword}, main aapko ___ DM kar dunga").
  No "follow for more", no "like and share".
- Sound like a sharp, friendly human creator: contractions, plain words, no hype, no AI clichés.
  Banned words/phrases: {banned}.
- Only facts that are in the script or the source material. Do not invent numbers.
- visual_scene: index (0-based) of the script scene whose diagram/checklist/comparison best supports the line,
  or -1 to show Arjun full screen. Line 1 and the last line must be -1. Middle lines should use a visual.

SCRIPT SCENES (index: visual_type | narration):
{scenes}

SOURCE MATERIAL:
{material}"""

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


def veo_prompt(line, n):
    return (f"Animate this exact photo into a realistic vertical 9:16 video of about 8 seconds. {LOOK} "
            f"{ACTING[(n - 1) % len(ACTING)]} Natural blinks, realistic skin and teeth, soft natural lighting, "
            f"steady camera. He speaks in {VOICE}, saying exactly: \"{line}\" "
            f"No subtitles, no on-screen text, no music, no other people.")


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
            takes = _adapt(r.get("piece", {}), r.get("material", ""))
        except Exception as ex:
            print("[presenter] could not adapt", e["id"], ex)
            continue
        e["presenter"] = {"status": "waiting", "takes": takes, "material": (r.get("material") or "")[:8000],
                          "scenes": r.get("piece", {}).get("scenes", []), "composed_from": None}
        planned.append(e)
    publisher.save(q)                     # prompts are sent later, at PRESENTER_PROMPT_TIME (see process)
    return planned


def _adapt(piece, material):
    scenes = piece.get("scenes", [])
    listing = "\n".join(f"{i}: {s.get('visual_type')} | {s.get('narration')}" for i, s in enumerate(scenes))
    res = llm.generate_json(ADAPT.format(n=config.PRESENTER_TAKES, banned=", ".join(config.BANNED[:20]),
                                         scenes=listing, material=material[:6000],
                                         keyword=piece.get("dm_keyword") or "KEYWORD"),
                            TAKES_SCHEMA, temperature=0.6)
    takes = res.get("takes", [])[:config.PRESENTER_TAKES]
    if len(takes) < 2:
        raise RuntimeError("too few takes")
    out = []
    for n, t in enumerate(takes, 1):
        line = re.sub(r"\s+", " ", t["line"]).strip().strip('"')
        vs = t.get("visual_scene", -1)
        if n in (1, len(takes)) or not (0 <= vs < len(scenes)):
            vs = -1
        out.append({"n": n, "line": line, "visual_scene": vs, "prompt": veo_prompt(line, n),
                    "msg_id": None, "file": None, "got_msg": None})
    return out


def _send_prompts(planned):
    total = sum(len(e["presenter"]["takes"]) for e in planned)
    times = ", ".join(f"{_short(e)} at {e['slot'][-5:]}" for e in planned)
    telegram.send_text(
        f"ARJUN CLIPS FOR TONIGHT: {len(planned)} Reels, {total} clips ({times} IST).\n\n"
        "For each prompt message below:\n"
        "1. Open Gemini, attach Arjun's photo (file below), choose Video, portrait 9:16.\n"
        "2. Copy the prompt (long-press the message > Copy) and generate.\n"
        "3. Download the video, then REPLY to that prompt message with the video.\n"
        "   (If you forget to reply, send the clips in order: R first, clip 1, 2, 3. The bot fills them in order.)\n\n"
        f"Clips needed by each Reel's time. If a Reel is missing clips {config.PRESENTER_GRACE_MIN} min after its "
        "time, the normal version is posted instead.")
    try:
        telegram.send_photo(photo_path(), "Arjun's photo: attach this in Gemini for every clip.")
    except Exception as ex:
        print("[presenter] photo send failed:", ex)
    for e in planned:
        for t in e["presenter"]["takes"]:
            head = f"{_short(e)} · clip {t['n']} of {len(e['presenter']['takes'])} · reply to this message with the video\n\n"
            t["msg_id"] = telegram.send_text(head + t["prompt"])


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
        telegram.send_text(f"Got {_short(e)} clip {t['n']} ({have}/{need})." +
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
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
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
    """Builds the Arjun edit. Returns (ok, reasons, meta)."""
    pres = e["presenter"]
    takes = pres["takes"]
    tmp = tempfile.mkdtemp(prefix="arjun_")
    clips, wavs, spans = [], [], []
    for t in takes:
        src = os.path.join(config.ROOT, t["file"])
        wav = os.path.join(tmp, f"a{t['n']}.wav")
        _ff(["-i", src, "-vn", "-ac", "1", "-ar", "44100", "-sample_fmt", "s16", wav])
        clips.append(src)
        wavs.append(wav)
        spans.append(_speech_span(wav))
    try:
        trans = _transcribe(e, wavs)
    except Exception as ex:
        trans = []
        print("[presenter] transcription unavailable:", ex)
    lines = []
    problems = []
    for i, t in enumerate(takes):
        tr = trans[i] if i < len(trans) else {}
        text = (tr.get("transcript") or "").strip() or t["line"]
        lines.append(text)
        if tr and not tr.get("matches", True):
            problems.append(f"clip {t['n']}: {tr.get('problem') or 'says something different from the prompt'}")

    out_dir = os.path.join(config.ROOT, os.path.dirname(e["dir"]), "arjun", "edit")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "reel.mp4")
    durs = [max(1.0, _duration(c)) for c in clips]
    audio = os.path.join(tmp, "voice.wav")
    reel.concat_audio(wavs, durs, audio)

    tag, badge = _ai_tag(), _handle_badge()
    enc = subprocess.Popen([reel.ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-", "-i", audio,
                            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest",
                            "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)
    previews = []
    scenes = pres.get("scenes", [])
    for i, (t, clip, d, (s0, s1), text) in enumerate(zip(takes, clips, durs, spans, lines)):
        subs = [(a + s0, b + s0, img) for a, b, img in reel.timed_subs(text, max(0.5, s1 - s0))]
        split = 0 <= t["visual_scene"] < len(scenes)
        panel = _split_panel(scenes[t["visual_scene"]], d) if split else None
        n_frames = int(round(d * FPS))
        k = 0
        for fr in _frames(clip, RW, RH):
            if k >= n_frames:
                break
            tt = k / FPS
            if split:
                canvas = Image.new("RGB", (RW, RH), D.CREAM)
                # Arjun in the lower half, framed on his face
                face = fr.crop((0, int(RH * 0.17), RW, int(RH * 0.17) + RH // 2))
                canvas.paste(face, (0, RH // 2))
                p = panel.panel(tt).resize((848, 760), Image.LANCZOS)
                D.rounded_paste(canvas, p, ((RW - 848) // 2, 150), 30)
                img = canvas
            else:
                img = fr.copy()
            img.paste(badge, (40, 60), badge)
            img.paste(tag, (RW - 340, 60), tag)
            sub_y = 880 if split else reel.SUB_Y - 80      # split screen: captions sit between graphic and face
            for a, b, sub in subs:
                if a <= tt < b:
                    img.paste(sub, (0, sub_y), sub)
                    break
            enc.stdin.write(img.tobytes())
            if k == int(n_frames * 0.55):
                pv = os.path.join(out_dir, f"scene_{i + 1:02d}.jpg")
                img.resize((540, 960)).save(pv, "JPEG", quality=85)
                previews.append(pv)
            k += 1
        if k == 0:
            raise RuntimeError(f"clip {t['n']} has no readable video frames")
        while k < n_frames:                       # pad if the clip was shorter than its audio
            enc.stdin.write(img.tobytes())
            k += 1
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError("ffmpeg failed while editing the Arjun Reel")

    piece = {"scenes": [{"narration": txt, "on_screen": "", "visual_type": "presenter" if takes[i]["visual_scene"] < 0
                         else scenes[takes[i]["visual_scene"]].get("visual_type")} for i, txt in enumerate(lines)],
             "caption": e["caption"]}
    rev = qc.review(piece, "reel", pres.get("material", ""), previews)
    ok, reasons = qc.verdict([], rev)
    reasons = problems + reasons
    ok = ok and not problems
    meta = {"dir": os.path.relpath(out_dir, config.ROOT), "duration": round(sum(durs), 1), "scores": rev["scores"],
            "previews": [os.path.relpath(p, config.ROOT) for p in previews], "transcripts": lines,
            "visual_issues": rev.get("visual_issues", [])}
    return ok, reasons, meta


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
