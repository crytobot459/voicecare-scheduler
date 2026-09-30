#!/usr/bin/env python3
"""VoiceCare — English-only voice clinic booking harness (thin wrapper).

Pipeline: AssemblyAI STT (EN) -> Gemini NLU (EN) -> scheduling tools -> consent gate -> book.
All Vietnamese tables removed. Keys from env only: ASSEMBLYAI_API_KEY, GEMINI_API_KEY.
Legacy names (VI_KEYTERMS, DAY_EN, run_pipeline, understand, ...) are kept as
English aliases so Streamlit/video/tests keep importing.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from agent.config import EN_KEYTERMS
from agent import llm_client, stt_client, tools, store
from agent.loop import run_agent_turn, BOOKINGS, AUDIT_LOG

# --- compat aliases (English values, old names kept for imports) ---
VI_KEYTERMS = EN_KEYTERMS
EN_KEYTERMS_ALIAS = EN_KEYTERMS
VI_DAYS = {"today": 0, "tomorrow": 1, "tomorrow morning": 1,
           "day after tomorrow": 2, "in 2 days": 2, "in two days": 2}
DAY_EN = {"today": "today", "tomorrow": "tomorrow",
          "tomorrow morning": "tomorrow morning",
          "day after tomorrow": "day after tomorrow",
          "in 2 days": "day after tomorrow", "in two days": "day after tomorrow"}
SPEC_EN = {"cardiology": "Cardiology",
           "general internal medicine": "General Internal Medicine",
           "ent": "ENT (Ear-Nose-Throat)", "dental": "Dental & Maxillofacial"}
SPECIALTIES = {
    "cardiology": ["cardiology", "cardio", "heart"],
    "general internal medicine": ["general", "general internal", "internal medicine", "internal"],
    "ent": ["ent", "ear nose throat", "ear-nose-throat"],
    "dental": ["dental", "dentist", "maxillofacial"],
}
DOCTORS = {"cardiology": "Nguyen", "general internal medicine": "Tran",
           "ent": "Le", "dental": "Pham"}
STATES = ("LISTENING", "UNDERSTANDING", "CHECKING", "CONFIRMATION", "BOOKED")


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def _empty_structured() -> dict:
    return {"utterances": [], "aai_entities": [], "sentiments": [],
            "summary": "", "chapters": [], "pii_text": "", "nlu_source": ""}


def transcribe(text_or_path: str) -> tuple:
    t, ms, backend, err = stt_client.transcribe(text_or_path, HERE)
    return t, ms, backend, err, [], _empty_structured()


def understand(transcript: str) -> tuple:
    t0 = now_ms()
    raw = llm_client.extract_appointment(transcript)
    ent = {
        "intent": "book" if raw.get("intent") in ("book_appointment", "change_time") else raw.get("intent", "unknown"),
        "specialty": tools.normalize_specialty(raw.get("specialty", "")),
        "doctor": tools.doctor_for(tools.normalize_specialty(raw.get("specialty", "")), raw.get("doctor", "")),
        "day": str(raw.get("date_label", "") or ""),
        "date_label": str(raw.get("date_label", "") or ""),
        "hour": raw.get("hour"),
        "minute": int(raw.get("minute", 0) or 0),
        "phone": str(raw.get("phone", "") or ""),
    }
    try:
        ent["hour"] = int(ent["hour"]) if ent["hour"] is not None else None
    except Exception:
        ent["hour"] = None
    conf = float(raw.get("confidence", 0.5) or 0.5)
    return ent, now_ms() - t0, conf


def missing_fields(ent: dict) -> list:
    e = dict(ent or {})
    if "day" in e and "date_label" not in e:
        e["date_label"] = e.get("day", "")
    return tools.missing_fields(e)


def ask_missing_text(miss: list, ent: dict) -> str:
    return llm_client.missing_question(miss, ent)


def load_bookings() -> list:
    return store.load_bookings(BOOKINGS)


def audit(event: str, payload: dict):
    return store.audit(AUDIT_LOG, event, payload)


def is_voice_confirm(text: str) -> str:
    return llm_client.confirm_verdict(text)


def check_availability(ent: dict) -> tuple:
    e = dict(ent or {})
    if "date_label" not in e and "day" in e:
        e["date_label"] = e.get("day", "")
    if "specialty" in e:
        e["specialty"] = tools.normalize_specialty(e.get("specialty", ""))
    return tools.check_availability(e, store.load_bookings(BOOKINGS))


def build_ics(rec: dict) -> str:
    return tools.build_ics(rec)


def build_readback(ent: dict) -> str:
    return llm_client.generate_readback(ent)


def entities_en(ent: dict) -> str:
    spec = (ent or {}).get("specialty", "") or "—"
    doc = (ent or {}).get("doctor", "") or "—"
    day = (ent or {}).get("date_label", "") or (ent or {}).get("day", "") or "—"
    hour = (ent or {}).get("hour", "")
    minute = (ent or {}).get("minute", 0) or 0
    hour_s = f"{hour:02d}:{minute:02d}" if isinstance(hour, int) else (str(hour) or "—")
    intent = (ent or {}).get("intent", "") or "—"
    return f"specialty={spec.title()} | doctor=Dr. {doc} | day={day} | time={hour_s} | intent={intent}"


def transcript_en_gloss(transcript: str, ent: dict | None = None) -> str:
    ent = ent or {}
    spec = (ent.get("specialty", "") or "checkup").title()
    day = ent.get("date_label", "") or ent.get("day", "") or "unspecified day"
    hour = ent.get("hour", "")
    hour_s = f"{hour} o'clock" if isinstance(hour, int) else "unspecified time"
    low = (transcript or "").lower()
    if any(w in low for w in ("book", "appointment", "schedule", "checkup", "visit", "clinic")):
        return f"Book {spec}, {day} at {hour_s}."
    if (transcript or "").strip().lower() in ("hello", "hello?", "hi"):
        return "Hello? (unclear audio — should escalate)."
    return f"{spec}, {day} at {hour_s}."


def structured_to_fields(transcript: str, ent: dict, struct: dict | None) -> list:
    struct = struct or {}
    src = (struct.get("nlu_source") or ent.get("source") or "regex-fallback")
    rows = [
        ("transcript", transcript or "", "assemblyai" if backend_is_real(struct) else "local-sim"),
        ("intent", ent.get("intent", ""), src),
        ("specialty", ent.get("specialty", "") or "", src),
        ("doctor", ent.get("doctor", "") or "", src),
        ("day", ent.get("date_label", "") or ent.get("day", ""), src),
        ("hour", "" if ent.get("hour") is None else str(ent.get("hour")), src),
        ("phone", ent.get("phone", "") or "", src),
    ]
    return rows


def backend_is_real(struct: dict) -> bool:
    return bool((struct or {}).get("utterances") or (struct or {}).get("aai_entities"))


def book(ent: dict, consent: bool) -> tuple:
    t0 = now_ms()
    if not consent:
        return None, now_ms() - t0, "no confirmation yet — books only on YES"
    e = dict(ent or {})
    if "date_label" not in e and "day" in e:
        e["date_label"] = e.get("day", "")
    e["specialty"] = tools.normalize_specialty(e.get("specialty", ""))
    e["doctor"] = tools.doctor_for(e.get("specialty", ""), e.get("doctor", ""))
    if not e.get("date_label") or e.get("hour") is None:
        return None, now_ms() - t0, "missing date/time — asking again"
    if not e.get("specialty"):
        return None, now_ms() - t0, "missing specialty — asking which specialty first"
    bookings = store.load_bookings(BOOKINGS)
    ok, amsg, _ = tools.check_availability(e, bookings)
    if not ok:
        return None, now_ms() - t0, amsg or "slot is full"
    rec = tools.build_record(e)
    try:
        bookings.append(rec)
        store.save_bookings(BOOKINGS, bookings)
    except Exception as ex:
        return None, now_ms() - t0, f"write error: {ex}"
    return rec, now_ms() - t0, ""


def run_pipeline(text: str, barge_in: str = "", auto_consent: bool = True,
                 confirm_text: str | None = None) -> dict:
    r = run_agent_turn(text, barge_in=barge_in, auto_consent=auto_consent,
                       confirm_text=confirm_text)
    # compat: expose day alias + keyterms + words for old callers
    ent = r.get("entities", {}) or {}
    ent = dict(ent)
    ent.setdefault("day", ent.get("date_label", ""))
    ent.setdefault("source", (r.get("structured") or {}).get("nlu_source", ""))
    r["entities"] = ent
    r["words"] = r.get("words", [])
    r["structured"] = r.get("structured") or {"nlu_source": ent.get("source", "")}
    r["keyterms"] = EN_KEYTERMS
    return r


def build(prompt: str) -> str:
    r = run_pipeline(prompt)
    return f"{r.get('reply','')} [total {r['total_ms']}ms, backend {r['backend']}]"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--barge-in") and not a.startswith("--confirm")]
    barge = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--barge-in=")), "")
    confirm = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--confirm=")), None)
    text = " ".join(args) or "Book a cardiology checkup tomorrow morning at 9"
    r = run_pipeline(text, barge_in=barge, confirm_text=confirm)
    print("== VoiceCare — speak to book your clinic visit ==")
    print(f"State: {r.get('state','')}")
    backend_label = {"local-sim": "typed try-out (text input, no audio file)", "assemblyai": "real AssemblyAI"}.get(r['backend'], r['backend'])
    print(f"Hearing backend: {backend_label}")
    print(f"Patient said: {r['transcript']}")
    print(f"Understood: {entities_en(r.get('entities',{}))} (confidence {r['confidence']})")
    for e in r["events"]:
        print(f"  [{e.split(':')[0]}] {e}")
    if r.get("readback"):
        print(f"Readback: {r['readback']}")
    if r.get("reply"):
        print(f"Assistant reply: {r['reply']}")
    if r.get("booking"):
        print(f"Booked: {r['booking']}")
    print("Stage latency (ms):", " | ".join(f"{k}={v}" for k, v in r["stages_ms"].items()), f"| TOTAL={r['total_ms']}")
    if r.get("escalated"):
        print("Transferred to the nurse hotline.")
    if r.get("needs_confirm"):
        print("Say YES to confirm, NO to change.")


if __name__ == "__main__":
    main()
