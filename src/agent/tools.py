#!/usr/bin/env python3
"""Clinic scheduling tools — pure English. Read-only check + gated book + ICS."""
import uuid
from datetime import datetime, timedelta, timezone

from .config import DOCTORS_EN, SPECIALTIES_EN, CLINIC_OPEN_HOUR, CLINIC_CLOSE_HOUR


def normalize_specialty(s: str) -> str:
    low = (s or "").lower()
    if "cardio" in low or "heart" in low:
        return "cardiology"
    if "general" in low or "internal" in low:
        return "general internal medicine"
    if low.strip() == "ent" or "ear" in low or "throat" in low or "nose" in low:
        return "ent"
    if "dent" in low or "tooth" in low or "teeth" in low or "maxillofacial" in low:
        return "dental"
    if low.strip() in SPECIALTIES_EN:
        return low.strip()
    return ""


def doctor_for(specialty: str, spoken_doctor: str = "") -> str:
    if (spoken_doctor or "").strip():
        return spoken_doctor.strip().removeprefix("Dr. ").removeprefix("Dr ")
    return DOCTORS_EN.get(specialty, "")


def date_label_to_iso(label: str) -> str:
    low = (label or "").strip().lower()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if low in ("today",):
        off = 0
    elif low in ("tomorrow", "tomorrow morning"):
        off = 1
    elif low in ("day after tomorrow", "in 2 days", "in two days"):
        off = 2
    else:
        off = 1
    return (today + timedelta(days=off)).strftime("%Y-%m-%d")


def missing_fields(ent: dict) -> list:
    miss = []
    if not (ent or {}).get("specialty"):
        miss.append("specialty")
    if not (ent or {}).get("date_label"):
        miss.append("date")
    if (ent or {}).get("hour") is None:
        miss.append("time")
    return miss


def check_availability(ent: dict, bookings: list) -> tuple:
    """Return (ok, message, suggest_hour). Never auto-reschedules."""
    hour = ent.get("hour")
    date_label = ent.get("date_label", "")
    specialty = ent.get("specialty", "")
    if hour is None or not date_label:
        return False, "missing date/time", None
    if hour < CLINIC_OPEN_HOUR or hour > CLINIC_CLOSE_HOUR:
        return False, (f"outside clinic hours (07:00-17:00) — you said {hour}h, "
                       "please pick another time"), None
    date_iso = date_label_to_iso(date_label)
    for b in bookings:
        if (b.get("date_iso") == date_iso and b.get("hour") == hour
                and b.get("specialty", "") == specialty):
            nxt = None
            for cand in list(range(hour + 1, CLINIC_CLOSE_HOUR + 1)) + list(range(hour - 1, CLINIC_OPEN_HOUR - 1, -1)):
                clash = any(x.get("date_iso") == date_iso and x.get("hour") == cand
                            and x.get("specialty", "") == specialty for x in bookings)
                if not clash:
                    nxt = cand
                    break
            spec_t = specialty.title() if specialty else ""
            if nxt is not None:
                return False, (f"Sorry, {hour}:00 {date_label} {spec_t} is fully booked. "
                               f"Would you like {nxt}:00 instead?"), nxt
            return False, (f"Sorry, {hour}:00 {date_label} {spec_t} is fully booked. "
                           "Please pick another time."), None
    return True, "", None


def build_record(ent: dict) -> dict:
    from datetime import datetime as _dt
    spec = normalize_specialty(ent.get("specialty", "")) or ent.get("specialty", "")
    return {
        "id": f"VC-{uuid.uuid4().int % 90000 + 10000}",
        "specialty": spec,
        "doctor": doctor_for(spec, ent.get("doctor", "")),
        "date_label": ent.get("date_label", ""),
        "date_iso": date_label_to_iso(ent.get("date_label", "")),
        "hour": ent.get("hour"),
        "minute": int(ent.get("minute", 0) or 0),
        "phone": ent.get("phone", "") or "",
        "status": "CONFIRMED",
        "ts": _dt.now().strftime("%F %T"),
    }


def build_ics(rec: dict) -> str:
    if not rec:
        return ""
    try:
        base = datetime.strptime(rec["date_iso"], "%Y-%m-%d")
        start = base.replace(hour=int(rec.get("hour") or 9), minute=int(rec.get("minute") or 0))
        end = start + timedelta(minutes=30)
        fmt = lambda d: d.strftime("%Y%m%dT%H%M%S")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//VoiceCare//Clinic//EN\r\n"
            f"BEGIN:VEVENT\r\nUID:{rec.get('id','noid')}@voicecare\r\nDTSTAMP:{stamp}\r\n"
            f"DTSTART:{fmt(start)}\r\nDTEND:{fmt(end)}\r\n"
            f"SUMMARY:Clinic visit {rec.get('specialty','checkup').title()} "
            f"({rec.get('date_label','')} {int(rec.get('hour') or 9):02d}:{int(rec.get('minute') or 0):02d})\r\n"
            f"DESCRIPTION:VoiceCare booking {rec.get('specialty','')} Dr. {rec.get('doctor','')} — "
            "bring insurance\\, arrive 15 min early.\r\n"
            "END:VEVENT\r\nEND:VCALENDAR\r\n"
        )
    except Exception:
        return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//VoiceCare//Clinic//EN\r\n"
                "BEGIN:VEVENT\r\nUID:fallback@voicecare\r\nDTSTAMP:20260930T000000Z\r\n"
                "SUMMARY:Checkup (booking)\r\nDESCRIPTION:VoiceCare booking.\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")


TOOL_SCHEMAS = [
    {
        "type": "function", "name": "check_availability",
        "description": "Check whether an exam slot is free (07:00-17:00, per-specialty).",
        "parameters": {
            "type": "object",
            "properties": {
                "specialty": {"type": "string", "enum": SPECIALTIES_EN},
                "date_label": {"type": "string",
                               "enum": ["today", "tomorrow", "tomorrow morning", "day after tomorrow"]},
                "hour": {"type": "number", "minimum": 7, "maximum": 17},
            },
            "required": ["specialty", "date_label", "hour"],
        },
    },
    {
        "type": "function", "name": "book_appointment",
        "description": "Finalize booking ONLY after the patient says YES. Never call before confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "specialty": {"type": "string", "enum": SPECIALTIES_EN},
                "date_label": {"type": "string"},
                "hour": {"type": "number"},
                "phone": {"type": "string"},
            },
            "required": ["specialty", "date_label", "hour"],
        },
    },
]
