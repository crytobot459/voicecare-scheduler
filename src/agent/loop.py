#!/usr/bin/env python3
"""VoiceCare agent loop — English-only state machine.

LISTENING -> UNDERSTANDING -> CHECKING -> CONFIRMATION -> BOOKED / ESCALATED

- STT: AssemblyAI when key + audio file, else typed fallback (labeled).
- NLU/confirmation/readback: Gemini when key, else minimal English fallback (labeled).
- Code decides booking, model never auto-books. Consent gate is strict.
"""
import time
from pathlib import Path

from . import llm_client
from . import stt_client
from . import tools
from . import store

HERE = Path(__file__).resolve().parent.parent
BOOKINGS = HERE / "bookings.json"
AUDIT_LOG = HERE / "audit.log"


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def _finalize_entities(raw: dict, transcript: str) -> dict:
    ent = {
        "intent": str(raw.get("intent", "unknown") or "unknown"),
        "specialty": tools.normalize_specialty(raw.get("specialty", "")),
        "doctor": "",
        "date_label": str(raw.get("date_label", "") or raw.get("date_raw", "") or ""),
        "hour": raw.get("hour"),
        "minute": int(raw.get("minute", 0) or 0),
        "phone": str(raw.get("phone", "") or ""),
        "confidence": float(raw.get("confidence", 0.5) or 0.5),
        "source": str(raw.get("source", "regex-fallback")),
    }
    try:
        ent["hour"] = int(ent["hour"]) if ent["hour"] is not None else None
    except Exception:
        ent["hour"] = None
    # normalize date paraphrases to canonical labels
    dl = (ent["date_label"] or "").lower()
    if "day after tomorrow" in dl or "in 2 days" in dl or "in two days" in dl:
        ent["date_label"] = "day after tomorrow"
    elif "tomorrow morning" in dl:
        ent["date_label"] = "tomorrow morning"
    elif "tomorrow" in dl:
        ent["date_label"] = "tomorrow"
    elif "today" in dl:
        ent["date_label"] = "today"
    ent["doctor"] = tools.doctor_for(ent["specialty"], raw.get("doctor", ""))
    # LLM-provided doctor may be a full name; keep as-is if present
    if raw.get("doctor") and not ent["doctor"]:
        ent["doctor"] = str(raw.get("doctor"))
    return ent


def run_agent_turn(text: str, barge_in: str = "", auto_consent: bool = True,
                   confirm_text: str | None = None, history=None) -> dict:
    stages, events = {}, []
    state = "LISTENING"
    hist = list(history or [])

    transcript, listen_ms, backend, err = stt_client.transcribe(text, HERE)
    stages["listen_ms"] = round(listen_ms, 1)
    if err:
        events.append(f"AssemblyAI STT failed ({err}) — labeled typed fallback")
        backend = "local-sim"
    if not (transcript or "").strip():
        events.append("recovery: unclear audio — asking again")
        transcript = transcript or text
        events.append("fallback: typed mode, backend local-sim (labeled)")

    state = "UNDERSTANDING"
    raw = llm_client.extract_appointment(transcript)
    ent = _finalize_entities(raw, transcript)
    conf = ent["confidence"]
    stages["understand_ms"] = round(float(raw.get("nlu_ms", 0) or 0), 1)
    events.append(f"nlu: source={ent['source']} intent={ent['intent']} conf={conf:.2f}")

    # barge-in: interruption handling
    if barge_in:
        events.append(f"barge-in: interruption '{barge_in}' — agent stops, keeps listening")
        action = llm_client.detect_correction(transcript, barge_in)
        if action == "cancel":
            events.append("barge-in: cancel heard — stopping, nothing written")
            store.audit(AUDIT_LOG, "barge_cancel", {"transcript": transcript, "barge_in": barge_in})
            stages["act_ms"] = 0.0
            stages["speak_ms"] = 0.0
            return _out(transcript + " " + barge_in, ent, conf, None, llm_client.cancel_message(),
                        stages, events, backend, "", "", False, False, "UNDERSTANDING", [], None)
        raw2 = llm_client.extract_appointment(transcript + " " + barge_in)
        ent2 = _finalize_entities(raw2, transcript + " " + barge_in)
        conf2 = ent2["confidence"]
        stages["understand_ms"] = round(stages["understand_ms"] + float(raw2.get("nlu_ms", 0) or 0), 1)
        if conf2 > conf or (action == "merge" and conf2 >= conf and conf2 > 0):
            ent, conf = ent2, conf2
            transcript = f"{transcript} {barge_in}".strip()
            events.append("barge-in: using the newer utterance")

    # escalation on low confidence / unknown intent
    if conf < 0.34 or ent["intent"] not in ("book_appointment", "change_time"):
        if ent["intent"] == "cancel":
            events.append("consent: cancel intent — nothing written")
            stages["act_ms"] = 0.0
            stages["speak_ms"] = 0.0
            return _out(transcript, ent, conf, None, llm_client.cancel_message(),
                        stages, events, backend, "", "", False, False, "UNDERSTANDING", [], None)
        events.append("escalating to a human: low confidence — calling the clinic hotline")
        store.audit(AUDIT_LOG, "escalate", {"transcript": transcript, "conf": round(conf, 2)})
        stages["act_ms"] = 0.0
        stages["speak_ms"] = 0.0
        return _out(transcript, ent, conf, None,
                    llm_client.escalation_message(),
                    stages, events, backend, "", "", False, False, "ESCALATED", [], None,
                    escalated=True)

    # missing slots -> ask one question
    miss = tools.missing_fields(ent)
    if miss and confirm_text is not None:
        q = llm_client.missing_question(miss, ent, hist)
        events.append(f"asking missing info: {','.join(miss)} — one question at a time")
        stages["act_ms"] = 0.0
        stages["speak_ms"] = 0.0
        return _out(transcript, ent, conf, None, q, stages, events, backend,
                    "", "", False, True, "UNDERSTANDING", miss, None)

    # availability check (read-only tool)
    state = "CHECKING"
    bookings = store.load_bookings(BOOKINGS)
    ok, amsg, suggest = tools.check_availability(ent, bookings)
    if not ok:
        events.append(f"recovery/availability: {amsg}")
        store.audit(AUDIT_LOG, "availability_block", {"entities": ent, "reason": amsg})
        stages["act_ms"] = 0.0
        stages["speak_ms"] = 0.0
        if amsg == "missing date/time":
            reply = llm_client.ask_again_message()
        else:
            try:
                reply = llm_client.full_slot_message(ent, suggest) or amsg
            except Exception:
                reply = amsg
        return _out(transcript, ent, conf, None, reply, stages, events, backend,
                    "", "", False, False, "CHECKING", [], suggest)

    # confirmation gate
    state = "CONFIRMATION"
    readback = llm_client.generate_readback(ent, hist)
    if confirm_text is not None:
        verdict = llm_client.confirm_verdict(confirm_text)
        store.audit(AUDIT_LOG, "voice_consent",
                    {"verdict": verdict, "confirm_text": confirm_text,
                     "entities": ent, "conf": round(conf, 2)})
        if verdict == "no":
            events.append("consent: NO heard — cancelled, nothing written")
            stages["act_ms"] = 0.0
            stages["speak_ms"] = 0.0
            return _out(transcript, ent, conf, None, llm_client.cancel_message(),
                        stages, events, backend, readback, "", False, False,
                        "CONFIRMATION", [], None)
        if verdict == "unclear":
            events.append("consent: waiting for YES/NO — asking again, nothing written")
            stages["act_ms"] = 0.0
            stages["speak_ms"] = 0.0
            return _out(transcript, ent, conf, None, readback, stages, events, backend,
                        readback, "", True, False, "CONFIRMATION", [], None)

        events.append("consent: YES heard — booking now")

    # book (re-check inside for TOCTOU)
    t0 = now_ms()
    bookings = store.load_bookings(BOOKINGS)
    ok2, amsg2, _ = tools.check_availability(ent, bookings)
    if not ok2:
        stages["act_ms"] = round(now_ms() - t0, 1)
        stages["speak_ms"] = 0.0
        events.append(f"recovery/write blocked: {amsg2}")
        try:
            blocked_reply = llm_client.full_slot_message(ent, None) or amsg2
        except Exception:
            blocked_reply = amsg2 or "Slot just filled — pick another time."
        return _out(transcript, ent, conf, None, blocked_reply,
                    stages, events, backend, readback, "", False, False, "CHECKING", [], None)
    if not ent.get("specialty"):
        stages["act_ms"] = round(now_ms() - t0, 1)
        stages["speak_ms"] = 0.0
        return _out(transcript, ent, conf, None, llm_client.missing_question(["specialty"], ent, hist),
                    stages, events, backend, readback, "", False, True, "UNDERSTANDING",
                    ["specialty"], None)
    if not auto_consent and confirm_text is None:
        stages["act_ms"] = round(now_ms() - t0, 1)
        stages["speak_ms"] = 0.0
        return _out(transcript, ent, conf, None, readback, stages, events, backend,
                    readback, "", True, False, "CONFIRMATION", [], None)
    rec = tools.build_record(ent)
    bookings.append(rec)
    try:
        store.save_bookings(BOOKINGS, bookings)
    except Exception as e:
        stages["act_ms"] = round(now_ms() - t0, 1)
        stages["speak_ms"] = 0.0
        return _out(transcript, ent, conf, None, f"write error: {e}",
                    stages, events, backend, readback, "", False, False, "CHECKING", [], None)
    stages["act_ms"] = round(now_ms() - t0, 1)
    store.audit(AUDIT_LOG, "book", {"booking": rec, "conf": round(conf, 2), "backend": backend})
    if confirm_text is None and auto_consent:
        events.append("consent: typed auto-confirm mode (labeled) — live use needs spoken YES")
    t1 = now_ms()
    try:
        reply = llm_client.booked_message(rec)
    except Exception:
        reply = (f"Booked successfully: {rec['specialty'].title()} with Dr. {rec['doctor']}, "
                 f"{rec['date_label']} at {rec['hour']:02d}:{rec['minute']:02d}. "
                 "Please arrive 15 minutes early and bring your insurance card.")
    stages["speak_ms"] = round(now_ms() - t1, 1)
    ics = tools.build_ics(rec)
    total = round(sum(stages.values()), 1)
    return {
        "transcript": transcript, "entities": ent, "confidence": round(conf, 2),
        "booking": rec, "reply": reply, "stages_ms": stages, "total_ms": total,
        "backend": backend, "words": [], "structured": {"nlu_source": ent["source"]},
        "keyterms": [], "events": events, "escalated": False, "readback": readback,
        "ics": ics, "needs_confirm": False, "needs_info": False,
        "state": "BOOKED", "missing": [], "suggest_hour": None,
    }


def _out(transcript, ent, conf, booking, reply, stages, events, backend,
         readback, ics, needs_confirm, needs_info, state, missing, suggest,
         escalated=False):
    total = round(sum(stages.values()), 1)
    return {
        "transcript": transcript, "entities": ent, "confidence": round(conf, 2),
        "booking": booking, "reply": reply, "stages_ms": stages, "total_ms": total,
        "backend": backend, "words": [], "structured": {"nlu_source": ent.get("source", "")},
        "keyterms": [], "events": events, "escalated": escalated, "readback": readback,
        "ics": ics, "needs_confirm": needs_confirm, "needs_info": needs_info,
        "state": state, "missing": missing, "suggest_hour": suggest,
    }
