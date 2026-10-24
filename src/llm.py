"""Gemini helpers: JSON text generation (with model fallback), vision review, and TTS."""
import base64
import io
import json
import os
import time

import requests

import config

BASE = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
KEY = lambda: os.environ["GEMINI_API_KEY"].strip()  # noqa: E731
CALLS = {"text": 0, "tts": 0, "failed": 0}


_last_call = [0.0]
MIN_GAP = float(os.environ.get("LLM_MIN_GAP", "5"))  # seconds between calls (free-tier per-minute limits)


def _post(model, body, timeout=120):
    wait = MIN_GAP - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    return requests.post(BASE.format(model), json=body, timeout=timeout,
                         headers={"x-goog-api-key": KEY(), "Content-Type": "application/json"})


def generate_json(prompt, schema=None, images=None, temperature=0.8, rounds=3, audio=None):
    """Returns parsed JSON. images = list of JPEG/PNG bytes; audio = list of WAV bytes."""
    parts = [{"text": prompt}]
    for img in images or []:
        mime = "image/png" if img[:4] == b"\x89PNG" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(img).decode()}})
    for a in audio or []:
        parts.append({"inline_data": {"mime_type": "audio/wav", "data": base64.b64encode(a).decode()}})
    cfg = {"responseMimeType": "application/json", "temperature": temperature}
    if schema:
        cfg["responseSchema"] = schema
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": cfg}
    last = ""
    for rnd in range(rounds):
        for model in config.TEXT_MODELS:
            try:
                r = _post(model, body)
            except requests.exceptions.RequestException as ex:
                last = f"{model}: {type(ex).__name__}"
                print(f"[llm] {last}")
                continue
            if r.status_code in (404, 429, 500, 503):
                last = f"{model}: HTTP {r.status_code}"
                print(f"[llm] {last}")
                continue
            r.raise_for_status()
            try:
                cand = r.json()["candidates"][0]
                text = "".join(p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought"))
                CALLS["text"] += 1
                return json.loads(text)
            except (KeyError, IndexError, json.JSONDecodeError) as ex:
                last = f"{model}: bad response ({ex})"
                print(f"[llm] {last}")
                continue
        time.sleep(30 * (rnd + 1))
    CALLS["failed"] += 1
    raise RuntimeError(f"Gemini unavailable ({last})")


def _pcm_to_wav(pcm, rate=24000):
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


TTS_EXHAUSTED = [False]


def gemini_tts(text):
    """Returns WAV bytes or None (quota/unavailable)."""
    if TTS_EXHAUSTED[0]:
        return None
    body = {"contents": [{"parts": [{"text": config.VOICE_STYLE + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig":
                                                                  {"voiceName": config.GEMINI_VOICE}}}}}
    quota_hits = []
    for model in config.GEMINI_TTS_MODELS:
        for attempt in range(2):
            try:
                r = _post(model, body, timeout=90)
            except requests.exceptions.RequestException:
                continue
            if r.status_code == 429:
                print(f"[tts] {model} quota reached")
                quota_hits.append(model)
                break
            if r.status_code != 200:
                time.sleep(5)
                continue
            try:
                p = next(x for x in r.json()["candidates"][0]["content"]["parts"] if "inlineData" in x)
            except (KeyError, IndexError, StopIteration):
                continue
            data = base64.b64decode(p["inlineData"]["data"])
            CALLS["tts"] += 1
            if data[:4] == b"RIFF":
                return data
            rate = 24000
            mt = p["inlineData"].get("mimeType", "")
            if "rate=" in mt:
                rate = int(mt.split("rate=")[1].split(";")[0])
            return _pcm_to_wav(data, rate)
    if len(quota_hits) == len(config.GEMINI_TTS_MODELS):
        TTS_EXHAUSTED[0] = True
    return None
