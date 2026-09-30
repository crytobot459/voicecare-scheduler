#!/usr/bin/env python3
"""Lightweight TTS for VoiceCare — English-only (accessibility).

Chain (first success wins, never crashes the demo):
  1. edge_tts (AriaNeural, needs lib + network) — best quality
  2. macOS `say` (offline, built-in) — local Streamlit on Mac
  3. espeak-ng (offline) — Linux fallback
Missing everything -> returns None, UI falls back to large text.
`last_error` explains WHY so the page says the real reason.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile


VOICE_EN = "en-US-AriaNeural"
SAY_VOICE = "Samantha"  # macOS en-US female, present on stock macOS

last_error = ""


def pick_voice(text: str, voice: str = "auto") -> str:
    """English-only voice selection."""
    return VOICE_EN


def _speak_edge(text: str, dst: str) -> bool:
    try:
        import edge_tts  # type: ignore
    except Exception as e:
        global last_error
        last_error = f"no edge-tts lib ({e.__class__.__name__})"
        return False
    try:
        import asyncio

        async def _run():
            tts = edge_tts.Communicate(text[:500], VOICE_EN)
            # Fail fast: a blackholed network must not hang the take forever.
            await asyncio.wait_for(tts.save(dst), timeout=25)

        asyncio.run(_run())
        p = Path(dst)
        if p.exists() and p.stat().st_size > 0:
            return True
        last_error = "edge-tts returned empty audio"
        return False
    except Exception as e:
        last_error = f"edge-tts network failed ({str(e)[:80] or e.__class__.__name__})"
        return False


def _speak_say(text: str, dst_aiff: str) -> bool:
    """macOS built-in voice, fully offline."""
    if not shutil.which("say"):
        return False
    try:
        cmd = ["say", "-r", "175", "-o", dst_aiff]
        # Prefer Samantha; fall back to system default if absent.
        try:
            voices = subprocess.run(["say", "-v", "?"], capture_output=True,
                                    text=True, timeout=10).stdout or ""
            if "Samantha" in voices:
                cmd[1:1] = ["-v", SAY_VOICE]
        except Exception:
            pass
        subprocess.run(cmd + [text[:1500]], check=True, timeout=60,
                       capture_output=True)
        p = Path(dst_aiff)
        if p.exists() and p.stat().st_size > 0:
            return True
        return False
    except Exception as e:
        global last_error
        last_error = f"macOS say failed ({str(e)[:80] or e.__class__.__name__})"
        return False


def _speak_espeak(text: str, dst_wav: str) -> bool:
    if not shutil.which("espeak-ng"):
        return False
    try:
        subprocess.run(["espeak-ng", "-v", "en", "-s", "170", "-w", dst_wav,
                        text[:1500]], check=True, timeout=60, capture_output=True)
        p = Path(dst_wav)
        if p.exists() and p.stat().st_size > 0:
            return True
        return False
    except Exception as e:
        global last_error
        last_error = f"espeak-ng failed ({str(e)[:80] or e.__class__.__name__})"
        return False


def speak(text: str, out_path: str = "", voice: str = "auto") -> str | None:
    """Synthesize `text` -> audio file. Returns the file path, or None if unavailable."""
    global last_error
    txt = (text or "").strip()
    if not txt:
        return None
    last_error = ""
    base = out_path or tempfile.mktemp(prefix="voicecare_")
    # 1. best quality: edge-tts mp3
    dst_mp3 = base if base.endswith(".mp3") else base + ".mp3"
    if _speak_edge(txt, dst_mp3):
        return dst_mp3
    edge_err = last_error
    # 2. offline macOS voice (aiff plays fine in browsers/st.audio)
    dst_aiff = base + ".aiff"
    if _speak_say(txt, dst_aiff):
        last_error = ""
        return dst_aiff
    # 3. offline linux voice
    dst_wav = base + ".wav"
    if _speak_espeak(txt, dst_wav):
        last_error = ""
        return dst_wav
    if not last_error:
        last_error = edge_err or "no TTS engine available (install edge-tts or use macOS)"
    return None


def available() -> bool:
    try:
        import edge_tts  # type: ignore  # noqa: F401
        return True
    except Exception:
        pass
    return bool(shutil.which("say") or shutil.which("espeak-ng"))
