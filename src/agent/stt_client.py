#!/usr/bin/env python3
"""AssemblyAI STT client — English-only. Batch REST + streaming WS URL builder.

Key comes from ASSEMBLYAI_API_KEY env only. No key -> typed fallback,
always labeled so judges never see a faked transcript.
"""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode
from .config import WS_URL, SAMPLE_RATE, AAI_STREAMING_MODEL, EN_KEYTERMS


def load_key() -> str:
    return os.getenv("ASSEMBLYAI_API_KEY", "").strip()


def build_ws_url(sample_rate: int = SAMPLE_RATE) -> str:
    params = {
        "sample_rate": sample_rate,
        "speech_model": AAI_STREAMING_MODEL,
        "speaker_labels": "true",
        "max_speakers": "2",
        "format_turns": "true",
        "mode": "min_latency",
        "language_codes": json.dumps(["en"]),
        "keyterms_prompt": json.dumps([k for k in EN_KEYTERMS if len(k) <= 50][:100]),
    }
    return f"{WS_URL}?{urlencode(params)}"


def _rest_post(url: str, key: str, payload=None, raw: bytes | None = None,
               content: str = "application/json") -> dict:
    import urllib.request
    data = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Authorization": key, "Content-Type": content})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rest_get(url: str, key: str) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={"Authorization": key})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def batch_transcribe_en(path: Path, key: str) -> tuple:
    """English batch: upload + transcript + poll. Returns (text, ms, backend, err)."""
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        up = _rest_post("https://api.assemblyai.com/v2/upload", key,
                        raw=f.read(), content="application/octet-stream")
    job = _rest_post("https://api.assemblyai.com/v2/transcript", key, {
        "audio_url": up["upload_url"],
        "speech_models": ["universal-3-5-pro", "universal-2"],
        "language_code": "en",
        "speaker_labels": True,
        "entity_detection": True,
    })
    tid = job["id"]
    for _ in range(12):
        time.sleep(5)
        r = _rest_get(f"https://api.assemblyai.com/v2/transcript/{tid}", key)
        if r.get("status") == "completed":
            ms = (time.perf_counter() - t0) * 1000.0
            return r.get("text") or "", ms, "assemblyai", ""
        if r.get("status") == "error":
            ms = (time.perf_counter() - t0) * 1000.0
            return "", ms, "assemblyai", f"STT error: {r.get('error')}"
    ms = (time.perf_counter() - t0) * 1000.0
    return "", ms, "assemblyai", "STT error: transcript timeout (>60s)"


def transcribe(text_or_path: str, base_dir: Path) -> tuple:
    """Return (transcript, ms, backend, error). Audio file + key -> real STT."""
    t0 = time.perf_counter()
    key = load_key()
    p = base_dir.parent / text_or_path if not text_or_path.startswith("/") else Path(text_or_path)
    if not p.exists() and Path(text_or_path).exists():
        p = Path(text_or_path)
    if key and len(key) >= 20 and p.exists() and p.suffix.lower() in (
            ".wav", ".mp3", ".m4a", ".aiff", ".ogg", ".flac", ".webm"):
        try:
            return batch_transcribe_en(p, key)
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000.0
            return "", ms, "assemblyai", f"STT error: {e}"
    ms = (time.perf_counter() - t0) * 1000.0
    return text_or_path, ms, "local-sim", ""
