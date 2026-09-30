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
_GEMINI_COOLDOWN_UNTIL = 0.0  # epoch s; set on 429 so bursts fall back fast
_GEMINI_COOLDOWN_S = 120.0
_GEMINI_COOLDOWN_FILE = "/tmp/voicecare_gemini_cooldown"


def _cooldown_active() -> bool:
    """Process-local + file cooldown (take spawns many python processes)."""
    try:
        if time.time() < _GEMINI_COOLDOWN_UNTIL:
            return True
        with open(_GEMINI_COOLDOWN_FILE, encoding="utf-8") as f:
            if time.time() < float((f.read() or "0").strip() or 0):
                return True
    except Exception:
        pass
    return False


def _cooldown_set() -> None:
    global _GEMINI_COOLDOWN_UNTIL
    _GEMINI_COOLDOWN_UNTIL = time.time() + _GEMINI_COOLDOWN_S
    try:
        with open(_GEMINI_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            f.write(str(_GEMINI_COOLDOWN_UNTIL))
    except Exception:
        pass

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
    "yes: yes, yeah, yep, confirm, confirmed, correct, that's right, sure, book it, sounds good, "
    "ok, okay, that works, go ahead, lock it in, please do, perfect. "
    "no: no, cancel, don't book, stop, never mind (without a new time). "
    "unclear: everything else, questions, hesitation, single filler words. "
    "A message with a new time (digits, o'clock, am/pm, morning/afternoon, tomorrow, today) "
    "is NOT a plain no — classify by its confirmation words, default unclear if mixed."
)

# Warm receptionist voice for spoken wording (kept separate from NLU temp 0.0).
DIALOGUE_SYSTEM = (
    "You are Mai, a warm clinic receptionist speaking slow, clear English on the phone. "
    "Echo what you heard briefly, ask one thing at a time, vary your phrasing, "
    "use short backchannels like 'Got it', 'Perfect', 'Thanks'. "
    "Never invent specialty/doctor/slot. Keep it to 1-2 short sentences. "
    "Always end confirmations with an explicit YES prompt (uppercase YES)."
)


def _dialogue_call(prompt: str, timeout: float = 20.0) -> str:
    """Human phrasing via Gemini (temp 0.7). Returns '' on any failure."""
    try:
        if not load_gemini_key():
            return ""
        raw = _gemini_call(DIALOGUE_SYSTEM, prompt, timeout=timeout,
                           temperature=0.7, max_tokens=120)
        raw = (raw or "").strip().strip('"')
        if raw and len(raw) < 300:
            return raw
    except Exception:
        pass
    return ""


def _pick(variants: list, key: str = "") -> str:
    """Deterministic variety: same slot -> same phrasing (stable for tests/video)."""
    if not variants:
        return ""
    if not key:
        return variants[0]
    h = 0
    for ch in key:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return variants[h % len(variants)]


def _correction_prefix(history=None) -> str:
    try:
        hist = history or []
        tail = " ".join(str(m.get("text", "") if isinstance(m, dict) else m)
                        for m in hist[-3:]).lower()
        if any(w in tail for w in ("instead", "change", "no,", "correction", "rather")):
            return "Got the change — "
    except Exception:
        pass
    return ""


def _gemini_call(system: str, user: str, timeout: float = 20.0, temperature: float = 0.0,
                 max_tokens: int = 512) -> str:
    global _GEMINI_DEAD, _GEMINI_COOLDOWN_UNTIL
    if _GEMINI_DEAD:
        raise RuntimeError("gemini disabled (prior 404/invalid key)")
    if _cooldown_active():
        raise RuntimeError("gemini cooling down after 429 (quota), using fast fallback")
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
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
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
        if code == 429:
            # Free-tier quota burst: cool down so the take falls back
            # instantly (clean low latency on camera) instead of stalling
            # 1s per call. Quota refills; next take retries automatically.
            _cooldown_set()
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
    if re.search(r"\b(no|cancel|don't book|dont book|stop|never mind|not now)\b", low):
        # correction with a new time is not a plain cancel
        if re.search(r"\d|o'clock|oclock|\bam\b|\bpm\b|morning|afternoon|tomorrow|today", low):
            # has edit -> let caller merge; verdict by confirmation words
            if re.search(r"\b(yes|yeah|yep|confirm|sure|correct|book it|sounds good|that works|go ahead|lock it|please do|perfect|ok|okay)\b", low):
                return "yes"
            return "unclear"
        return "no"
    if re.search(r"\b(yes|yeah|yep|confirm|confirmed|correct|that's right|thats right|sure|book it|sounds good|that works|go ahead|lock it|please do|perfect|ok|okay)\b", low):
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


def generate_readback(ent: dict, history=None) -> str:
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
    # Prefer LLM phrasing when a key exists, else warm deterministic variants.
    # NOTE: every variant keeps uppercase YES so the consent gate + tests stay green.
    try:
        if load_gemini_key():
            hist_txt = ""
            try:
                hist = history or []
                tail = [str(m.get("text", "") if isinstance(m, dict) else m)[-120:]
                        for m in hist[-4:]]
                hist_txt = " | ".join(t for t in tail if t)
            except Exception:
                hist_txt = ""
            raw = _dialogue_call(
                f"Confirm {spec_t}{doc_t} at {time_t} {day}. "
                f"Recent turns: {hist_txt[:400]}. "
                "Warm one-sentence confirmation ending with 'Say YES to confirm.'",
            )
            if raw and "YES" in raw:
                return raw.strip()
            raw2 = _gemini_call(
                "You write one short clinic confirmation sentence. No JSON, one sentence, English.",
                f"Confirm {spec_t}{doc_t} at {time_t} {day}. Ask: Should I book this? Say YES to confirm.",
            )
            if raw2 and len(raw2) < 300 and "YES" in raw2:
                return raw2.strip()
    except Exception:
        pass
    prefix = _correction_prefix(history) or _pick(
        ["Got it — ", "Perfect — ", "Thanks! "],
        key=f"{spec_t}|{day}|{hour}",
    )
    variants = [
        (f"{prefix}{spec_t}{doc_t} at {time_t} {day}. "
         "Shall I go ahead and book that for you? Just say YES to confirm."),
        (f"{prefix}I've got {spec_t}{doc_t}, {day} at {time_t}. "
         "Should I lock it in? Say YES and I'll book it."),
        (f"{prefix}so that's {spec_t}{doc_t}, {day} at {time_t} — does that sound right? "
         "Say YES to confirm and I'll book it."),
    ]
    return _pick(variants, key=f"{spec_t}|{day}|{hour}|{prefix}")


def full_slot_message(ent: dict, suggest_hour=None) -> str:
    """Warm 'slot just filled' message. Always keeps 'fully booked' for tests."""
    spec = ((ent or {}).get("specialty", "") or "checkup").title()
    day = (ent or {}).get("date_label", "") or (ent or {}).get("day", "") or "that day"
    hour = (ent or {}).get("hour", "")
    hour_s = f"{hour}:00" if isinstance(hour, int) else str(hour or "that time")
    try:
        if load_gemini_key():
            raw = _dialogue_call(
                f"Tell the patient {hour_s} {day} {spec} is fully booked, apologize briefly, "
                f"offer {suggest_hour}:00 instead or ask for another time. "
                "Must include the words 'fully booked'. One or two short sentences.",
            )
            if raw and "fully booked" in raw.lower():
                return raw.strip()
    except Exception:
        pass
    if suggest_hour is not None:
        return (f"Ah, {hour_s} {day} {spec} is fully booked — sorry, that slot just filled up. "
                f"I do have {suggest_hour}:00 open — would that work for you, or prefer another time?")
    return (f"Ah, {hour_s} {day} {spec} is fully booked — sorry about that. "
            "What other time works for you?")


def booked_message(rec: dict) -> str:
    """Warm booking confirmation. Keeps specialty + day strings for tests/demo."""
    spec = (rec.get("specialty", "") or "checkup").title()
    doc = rec.get("doctor", "")
    doc_t = f" with Dr. {doc}" if doc else ""
    day = rec.get("date_label", "")
    hour = rec.get("hour", 9)
    minute = rec.get("minute", 0) or 0
    try:
        hh = f"{int(hour):02d}:{int(minute):02d}"
    except Exception:
        hh = str(hour)
    bid = rec.get("id", "")
    try:
        if load_gemini_key():
            raw = _dialogue_call(
                f"Confirm booking: {spec}{doc_t}, {day} at {hh}, ID {bid}. "
                "Warm, brief, remind to arrive 15 min early with insurance card.",
            )
            if raw and spec in raw and day in raw:
                return raw.strip()
    except Exception:
        pass
    opener = _pick(
        ["All set — you're booked! ", "Wonderful, it's confirmed! ", "Great news — all booked! "],
        key=str(bid),
    )
    return (f"{opener}You're seeing {spec}{doc_t}, {day} at {hh} "
            f"(booking {bid}). Please arrive 15 minutes early and bring your insurance card. "
            "Anything else I can help with?")


def escalation_message() -> str:
    try:
        if load_gemini_key():
            raw = _dialogue_call(
                "The line is unclear. Apologize warmly and say you're transferring "
                "to the nurse hotline. One short sentence.",
            )
            if raw and len(raw) < 200:
                return raw.strip()
    except Exception:
        pass
    return ("Sorry, I'm having trouble hearing you — let me transfer you "
            "to our nurse hotline so we can take good care of you.")


def cancel_message() -> str:
    return "No problem at all — I've cancelled that. Just tell me a new time whenever you're ready."


def ask_again_message() -> str:
    return "Sorry, I didn't quite catch the day and time — could you say it again? For example, tomorrow morning at 9 o'clock."


def missing_question(missing: list, ent: dict | None = None, history=None) -> str:
    ent = ent or {}
    # Try one warm LLM line first so phrasing varies visit to visit.
    try:
        if load_gemini_key():
            need = ",".join(missing or [])
            have = f"{ent.get('specialty','')}|{ent.get('date_label','')}|{ent.get('hour','')}"
            raw = _dialogue_call(
                f"Patient is missing: {need}. Already have: {have}. "
                "Ask for the FIRST missing item only (specialty, then day, then time), "
                "warm and brief, one question.",
            )
            if raw and len(raw) < 250:
                low = raw.lower()
                if ("specialty" in missing and "specialt" in low) or \
                   ("specialty" not in missing and "?" in raw):
                    return raw.strip()
                if "specialty" not in missing:
                    return raw.strip()
    except Exception:
        pass
    if "specialty" in missing:
        return _pick([
            ("Sure, happy to help — which specialty do you need? "
             "(Cardiology, General Internal Medicine, ENT, Dental)"),
            ("Got it — and which specialty would you like? "
             "We have Cardiology, General Internal Medicine, ENT, and Dental."),
            ("Thanks! Which specialty should I book — Cardiology, General Internal Medicine, ENT, or Dental?"),
        ], key=str(ent.get("date_label", "")) + str(ent.get("hour", "")))
    if "date" in missing or "day" in missing:
        spec = ent.get("specialty", "")
        prefix = f"For {spec.title()} " if spec else ""
        return _pick([
            (f"{prefix}which day works best for you? "
             "(e.g. today / tomorrow / tomorrow morning / day after tomorrow)"),
            (f"{prefix}what day suits you — today, tomorrow, or day after tomorrow?"),
        ], key=str(spec))
    if "time" in missing:
        spec = (ent.get("specialty", "") or "").title()
        day = ent.get("date_label", "") or ent.get("day", "")
        parts = f"{spec} {day}".strip()
        ctx = f" for {parts}" if parts else ""
        return _pick([
            (f"Got it{ctx} — what time suits you best? We're open 07:00 to 17:00, "
             "e.g. 9 o'clock works great."),
            (f"Thanks{ctx}! Morning or afternoon better for you? We're open 7 to 5."),
            (f"Perfect{ctx}. Which time should I check — e.g. 9 o'clock?"),
        ], key=str(ent.get("specialty", "")) + str(ent.get("date_label", "")))
    return "Could you say that again?"
