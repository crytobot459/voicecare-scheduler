#!/usr/bin/env python3
"""Agent config — English-only, env-based keys. Never log key values."""
import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load project-root .env into os.environ (no override, no logging).

    Lets double-click/Streamlit runs pick up local keys without exporting.
    Real env / Streamlit secrets / sidebar always win (setdefault only).
    """
    try:
        root = Path(__file__).resolve().parent.parent.parent
        for cand in (root / ".env", Path.cwd() / ".env"):
            if not cand.exists():
                continue
            for raw in cand.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("'").strip('"')
                if k and v and k not in os.environ:
                    os.environ[k] = v
            break
    except Exception:
        pass


_load_dotenv()

WS_URL = "wss://streaming.assemblyai.com/v3/ws"
AAI_STREAMING_MODEL = "u3-rt-pro"
SAMPLE_RATE = 16000

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
GEMINI_ENDPOINT_TMPL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# English boost phrases for AssemblyAI streaming (free, max 100).
EN_KEYTERMS = [
    "cardiology", "general internal medicine", "ent", "ear nose throat",
    "dental", "appointment", "checkup", "tomorrow morning", "tomorrow",
    "day after tomorrow", "today", "morning", "afternoon",
    "yes", "yeah", "confirm", "correct", "no", "cancel", "change time",
    "insurance", "doctor", "clinic", "nine", "ten", "eleven",
]

SPECIALTIES_EN = [
    "cardiology",
    "general internal medicine",
    "ent",
    "dental",
]

DOCTORS_EN = {
    "cardiology": "Nguyen",
    "general internal medicine": "Tran",
    "ent": "Le",
    "dental": "Pham",
}

CLINIC_OPEN_HOUR = 7
CLINIC_CLOSE_HOUR = 17


def load_assemblyai_key() -> str:
    return os.getenv("ASSEMBLYAI_API_KEY", "").strip()


def load_gemini_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip()


def has_assemblyai() -> bool:
    return len(load_assemblyai_key()) >= 20


def has_gemini() -> bool:
    return len(load_gemini_key()) >= 10


def key_status() -> dict:
    a = load_assemblyai_key()
    g = load_gemini_key()
    return {
        "assemblyai_set": len(a) >= 20,
        "assemblyai_len": len(a),
        "gemini_set": len(g) >= 10,
        "gemini_len": len(g),
        "gemini_model": GEMINI_MODEL,
        "streaming_model": AAI_STREAMING_MODEL,
    }
