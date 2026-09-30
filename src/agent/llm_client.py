#!/usr/bin/env python3
"""LLM client — Gemini free tier primary, English-only.

All NLU goes through here:
  extract_appointment() — intent + entities + confidence
  confirm_verdict() — yes / no / unclear
  detect_correction() — barge-in merge vs cancel
  generate_readback() / missing_question() — agent wording

No hard-coded Vietnamese. Offline fallback is minimal English regex,
always labeled source=regex-fallback so judges see when LLM is off.
"""
import json
import os
import re
import time
import urllib.request

from .config import load_gemini_key, GEMINI_MODEL, GEMINI_ENDPOINT_TMPL

_GEMINI_DEAD = False

EXTRACT_SYSTEM = (
    "You are a clinic scheduling NLU extractor. Output JSON only, no markdown. "
    "Schema: {\"intent\": \"book_appointment|change_time|cancel|unknown\", "
    "\"specialty\": \"cardiology|general internal medicine|ent|dental|\", "
    "\"doctor\": \"\", \"date_raw\": \"\", \"date_label\": \"today|tomorrow|tomorrow morning|day after tomorrow|\", "
    "\"time_raw\": \"\", \"hour\": 0-23 or null, \"minute\": 0-59, "
    "\"phone\": \"\", \"confidence\": 0.0-1.0}. "
    "Rules: English input only. Map cardio/heart->cardiology, general/internal->general internal medicine, "
    "ear/nose/throat/tmh->ent, tooth/teeth/dentist->dental. "
    "Map today->today, tomorrow/tmrw->tomorrow, tomorrow morning->tomorrow morning, "
    "day after tomorrow/in 2 days->day after tomorrow. "
    "Parse 9, 9am, 9:30, nine o'clock, half past nine. Convert pm (2pm->14). "
    "intent=book_appointment if user wants to book/check availability. "
    "confidence: 1.0 full slot, 0.6 partial, 0.2 unclear."
)

CONFIRM_SYSTEM = (
    "You are a confirmation classifier. Output JSON only: {\"verdict\": \"yes|no|unclear\"}. "
    "yes: yes, yeah, yep, confirm, confirmed, correct, that's right, sure, book it, sounds good. "
    "no: no, cancel, don't book, stop, never mind (without a new time). "
    "unclear: everything else, questions, hesitation, single filler words. "
    "A message with a new time (digits, o'clock, am/pm, morning/afternoon, tomorrow, today) "
    "is NOT a plain no — classify by its confirmation words, default unclear if mixed."
)


def _gemini_call(system: str, user: str, timeout: float = 20.0) -> str:
    global _GEMINI_DEAD
    if _GEMINI_DEAD:
        raise RuntimeError("gemini disabled (prior 404/invalid key)")
    key = load_gemini_key()
    if not key:
        raise RuntimeError("missing GEMINI_API_KEY")
    # NOTE 30/9: keys are no longer always AIza... (OAuth-style tokens work
    # with ?key= too) — let the API decide; 400/401/403/404 latches dead below.
    # 503 overload stays retryable so the next turn tries again.
    url = GEMINI_ENDPOINT_TMPL.format(model=GEMINI_MODEL)
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user[:2000]}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 512},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url + "?key=" + key,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        code = getattr(e, "code", 0) or 0
        if code in (400, 401, 403, 404):
            _GEMINI_DEAD = True
        raise
    try:
        parts = out["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except Exception:
        return ""


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    # Strip code fences if model adds them despite instructions.
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    return {}


# ---------- offline English fallback (labeled, minimal) ----------

SPEC_PATTERNS = [
    ("cardiology", [r"cardio", r"heart"]),
    ("general internal medicine", [r"general internal", r"general", r"internal medicine", r"\binternal\b"]),
    ("ent", [r"\bent\b", r"ear", r"nose", r"throat"]),
    ("dental", [r"dental", r"dentist", r"tooth", r"teeth", r"maxillofacial"]),
]

DAY_PATTERNS = [
    ("tomorrow morning", [r"tomorrow morning"]),
    ("day after tomorrow", [r"day after tomorrow", r"in 2 days", r"in two days"]),
    ("tomorrow", [r"tomorrow", r"tmrw"]),
    ("today", [r"\btoday\b"]),
]

NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(o'?clock)?\s*(am|pm|a\.m\.|p\.m\.)?", re.I)
DAYWORD_RE = re.compile(r"morning|afternoon|evening", re.I)


def fallback_extract(transcript: str) -> dict:
    low = (transcript or "").lower()
    # Collect all matches with positions; last mention wins, longest wins at same spot.
    # This prevents "tomorrow" inside "tomorrow morning" or "day after tomorrow"
    # from overwriting the longer phrase.
    spec_hits: list = []
    for canon, pats in SPEC_PATTERNS:
        for p in pats:
            for m in re.finditer(p, low):
                spec_hits.append((m.start(), m.end() - m.start(), canon))
    specialty = ""
    if spec_hits:
        spec_hits.sort(key=lambda t: (t[0], t[1]))
        specialty = spec_hits[-1][2]
        # If a longer phrase ends at same region as a shorter one later in list,
        # prefer the longest among hits sharing the max start cluster.
        # (sort above already puts longest last for same start)
    day_hits: list = []
    for canon, pats in DAY_PATTERNS:
        for p in pats:
            for m in re.finditer(p, low):
                day_hits.append((m.start(), m.end() - m.start(), canon))
    date_label = ""
    if day_hits:
        # cluster overlapping hits; last cluster = last mention; longest inside wins
        day_hits.sort()
        clusters, cur, cur_end = [], [day_hits[0]], day_hits[0][0] + day_hits[0][1]
        for s, ln, c in day_hits[1:]:
            if s < cur_end:
                cur.append((s, ln, c))
                cur_end = max(cur_end, s + ln)
            else:
                clusters.append(cur)
                cur, cur_end = [(s, ln, c)], s + ln
        clusters.append(cur)
        last = clusters[-1]
        date_label = max(last, key=lambda t: (t[1], t[0]))[2]
    matches = list(TIME_RE.finditer(transcript or ""))
    # drop bare years/phone-ish numbers: keep 1-12 with time context or o'clock/am-pm
    hour = None
    minute = 0
    for m in reversed(matches):
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) and m.group(2).isdigit() else 0
        has_marker = bool(m.group(3) or m.group(4) or mi or (1 <= h <= 17))
        if 1 <= h <= 23 and has_marker:
            hour = h
            minute = mi
            ampm = (m.group(4) or "").lower()
            if ampm.startswith("p") and hour is not None and hour < 12:
                hour += 12
            break
    if hour is None:
        for w in sorted(NUM_WORDS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(w)}\b(\s*o'?clock)?", low):
                hour = NUM_WORDS[w]
                break
    if "half past" in low:
        for w, n in NUM_WORDS.items():
            if re.search(rf"half past {re.escape(w)}", low):
                hour, minute = n, 30
                break
    has_book = any(w in low for w in (
        "book", "appointment", "schedule", "checkup", "check-up",
        "visit", "clinic", "available", "open", "slot"))
    intent = "book_appointment" if (has_book or (specialty and date_label and hour is not None)) else "unknown"
    if re.search(r"\bcancel\b|\bdon't book\b|\bnever mind\b", low) and hour is None and not specialty:
        intent = "cancel"
    conf = sum([bool(date_label), hour is not None, intent == "book_appointment"]) / 3.0
    return {
        "intent": intent, "specialty": specialty, "doctor": "",
        "date_raw": date_label, "date_label": date_label,
        "time_raw": "", "hour": hour, "minute": minute, "phone": "",
        "confidence": round(conf, 2), "source": "regex-fallback",
    }


def fallback_confirm(text: str) -> str:
    low = f" {(text or '').lower()} "
    if re.search(r"\b(no|cancel|don't book|stop|never mind|not now)\b", low):
        # correction with a new time is not a plain cancel
        if re.search(r"\d|o'clock|oclock|\bam\b|\bpm\b|morning|afternoon|tomorrow|today", low):
            # has edit -> let caller merge; verdict by confirmation words
            if re.search(r"\b(yes|yeah|yep|confirm|sure|correct|book it)\b", low):
                return "yes"
            return "unclear"
        return "no"
    if re.search(r"\b(yes|yeah|yep|confirm|confirmed|correct|that's right|sure|book it|sounds good|ok|okay)\b", low):
        return "yes"
    return "unclear"


# ---------- public API ----------

def extract_appointment(transcript: str) -> dict:
    t0 = time.perf_counter()
    try:
        if load_gemini_key():
            raw = _gemini_call(EXTRACT_SYSTEM, f"Extract: {transcript}")
            d = _parse_json(raw)
            if d:
                ms = round((time.perf_counter() - t0) * 1000, 1)
                ent = {
                    "intent": str(d.get("intent", "unknown") or "unknown"),
                    "specialty": str(d.get("specialty", "") or ""),
                    "doctor": str(d.get("doctor", "") or ""),
                    "date_raw": str(d.get("date_raw", "") or d.get("date_label", "") or ""),
                    "date_label": str(d.get("date_label", "") or ""),
                    "time_raw": str(d.get("time_raw", "") or ""),
                    "hour": d.get("hour"),
                    "minute": int(d.get("minute", 0) or 0),
                    "phone": str(d.get("phone", "") or ""),
                    "confidence": float(d.get("confidence", 0.5) or 0.5),
                    "source": "gemini",
                    "nlu_ms": ms,
                }
                # normalize hour
                try:
                    ent["hour"] = int(ent["hour"]) if ent["hour"] is not None else None
                except Exception:
                    ent["hour"] = None
                # normalize specialty aliases the model may paraphrase
                sp = (ent["specialty"] or "").lower()
                if "cardio" in sp or "heart" in sp:
                    ent["specialty"] = "cardiology"
                elif "general" in sp or "internal" in sp:
                    ent["specialty"] = "general internal medicine"
                elif "ent" in sp or "ear" in sp or "throat" in sp:
                    ent["specialty"] = "ent"
                elif "dent" in sp or "tooth" in sp or "teeth" in sp:
                    ent["specialty"] = "dental"
                return ent
    except Exception:
        pass
    ent = fallback_extract(transcript)
    ent["nlu_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return ent


def confirm_verdict(text: str) -> str:
    try:
        if load_gemini_key() and (text or "").strip():
            raw = _gemini_call(CONFIRM_SYSTEM, f"Classify: {text}")
            d = _parse_json(raw)
            v = str(d.get("verdict", "") or "").lower().strip()
            if v in ("yes", "no", "unclear"):
                return v
    except Exception:
        pass
    return fallback_confirm(text)


def detect_correction(original: str, barge_in: str) -> str:
    """Return 'cancel' | 'merge' | 'ignore' for a barge-in turn."""
    b = (barge_in or "").lower()
    if not b.strip():
        return "ignore"
    # plain cancel with no new slot info
    if re.search(r"\b(cancel|don't book|stop|never mind|not now|no)\b", b):
        has_edit = bool(re.search(
            r"\d|o'clock|oclock|\bam\b|\bpm\b|morning|afternoon|evening|tomorrow|today|"
            r"cardiology|general|internal|ent|dental|ear|throat|tooth|monday|tuesday|"
            r"wednesday|thursday|friday", b))
        if not has_edit:
            return "cancel"
        return "merge"
    # any new slot content -> merge
    if re.search(r"\d|o'clock|morning|afternoon|tomorrow|today|cardiology|general|ent|dental", b):
        return "merge"
    return "merge"


def generate_readback(ent: dict) -> str:
    spec = (ent or {}).get("specialty", "") or "checkup"
    spec_t = spec.title() if spec else "Checkup"
    doc = (ent or {}).get("doctor", "")
    doc_t = f" with Dr. {doc}" if doc else ""
    day = (ent or {}).get("date_label", "") or (ent or {}).get("date_raw", "") or "unspecified day"
    hour = (ent or {}).get("hour")
    minute = (ent or {}).get("minute", 0) or 0
    if isinstance(hour, int):
        time_t = f"{hour:02d}:{minute:02d}" if minute else f"{hour:02d}:00"
    else:
        time_t = "unspecified time"
    # Prefer LLM phrasing when a key exists, else deterministic template.
    try:
        if load_gemini_key():
            raw = _gemini_call(
                "You write one short clinic confirmation sentence. No JSON, one sentence, English.",
                f"Confirm {spec_t}{doc_t} at {time_t} {day}. Ask: Should I book this? Say YES to confirm.",
            )
            if raw and len(raw) < 300:
                return raw.strip()
    except Exception:
        pass
    return (f"I found {spec_t}{doc_t} at {time_t} {day}. "
            "Should I book this? Say YES to confirm.")


def missing_question(missing: list, ent: dict | None = None) -> str:
    ent = ent or {}
    if "specialty" in missing:
        return ("Sure. Which specialty would you like? "
                "(Cardiology, General Internal Medicine, ENT, Dental)")
    if "date" in missing or "day" in missing:
        spec = ent.get("specialty", "")
        prefix = f"For {spec.title()} " if spec else ""
        return (f"{prefix}which day works? "
                "(e.g. today / tomorrow / tomorrow morning / day after tomorrow)")
    if "time" in missing:
        return "What time works? The clinic runs 07:00-17:00 (e.g. 9 o'clock)."
    return "Could you say that again?"
