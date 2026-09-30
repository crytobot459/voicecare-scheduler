#!/usr/bin/env python3
"""Lightweight TTS for VoiceCare — English-only (accessibility).

Voice: en-US-AriaNeural. Missing lib/network -> returns None, UI falls back
to large text. Never crashes the demo because of TTS.
"""
from pathlib import Path
import tempfile


VOICE_EN = "en-US-AriaNeural"


def pick_voice(text: str, voice: str = "auto") -> str:
    """English-only voice selection."""
    return VOICE_EN


def speak(text: str, out_path: str = "", voice: str = "auto") -> str | None:
    """Synthesize `text` -> mp3 file. Returns the file path, or None if unavailable."""
    txt = (text or "").strip()
    if not txt:
        return None
    try:
        import edge_tts  # type: ignore
    except Exception:
        return None
    try:
        import asyncio

        dst = out_path or tempfile.mktemp(suffix=".mp3")
        voice_id = pick_voice(txt, voice)

        async def _run():
            tts = edge_tts.Communicate(txt[:500], voice_id)
            # Fail fast: a blackholed network must not hang the take forever.
            await asyncio.wait_for(tts.save(dst), timeout=25)

        asyncio.run(_run())
        p = Path(dst)
        if p.exists() and p.stat().st_size > 0:
            return str(p)
        return None
    except Exception:
        return None


def available() -> bool:
    try:
        import edge_tts  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False
