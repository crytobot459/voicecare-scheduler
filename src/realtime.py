#!/usr/bin/env python3
"""VoiceCare realtime — custom WebSocket to AssemblyAI Streaming v3 (English-only).

Raw WS so we control speech_model / language / keyterms / diarization.
Model: u3-rt-pro + min_latency + language_codes=["en"] + EN keyterms.

Run (needs ASSEMBLYAI_API_KEY env):
  python3 src/realtime.py --src sample_en.wav
  echo "[]" > src/bookings.json  # reset before takes with --confirm to avoid double-booking

Flow: mic/file --WS--> PARTIAL/FINAL + speaker A/B + truly measured ms
  --FINAL text--> run_pipeline() (Gemini NLU -> availability -> consent -> book).
Billing: billed per open session — always send Terminate, never hang the WS.

English-only. No Vietnamese.
"""
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import aifc
import audioop
import json
import os
import sys
import threading
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent
sys.path.insert(0, str(HERE))

WS_URL = "wss://streaming.assemblyai.com/v3/ws"
SAMPLE_RATE = 16000
CHUNK_BYTES = 3200  # ~100ms audio 16k s16 mono


def load_api_key() -> str:
    key = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
    if key:
        return key
    for cand in (BUILD.parent / "work" / ".assemblyai_key",
                 BUILD / ".assemblyai_key",
                 Path.home() / ".assemblyai_key"):
        try:
            if cand.exists():
                k = cand.read_text(encoding="utf-8").strip()
                if len(k) >= 20:
                    return k
        except Exception:
            pass
    return ""


def _ws_keyterms() -> list:
    """English boost phrases for streaming (free, max 100, each <=50 chars)."""
    try:
        from agent.config import EN_KEYTERMS as _K
        return [k for k in _K if len(k) <= 50][:100]
    except Exception:
        try:
            from main import VI_KEYTERMS as _K2
            return [k for k in _K2 if len(k) <= 50][:100]
        except Exception:
            return ["cardiology", "appointment", "tomorrow morning", "yes", "no", "confirm"]


def build_ws_url(sample_rate: int = SAMPLE_RATE) -> str:
    # u3-rt-pro + mode=min_latency = lowest-latency path (server requires this pair;
    # universal-streaming-english + mode returns 3006 since Sep 2026).
    # language_codes=["en"]: monolingual English bias.
    # keyterms_prompt: single JSON array (server returns 3006 on repeated params).
    # max_speakers=2: patient + receptionist.
    from urllib.parse import urlencode as _ue
    params = {"sample_rate": sample_rate,
              "speech_model": "u3-rt-pro",
              "speaker_labels": "true",
              "max_speakers": "2",
              "format_turns": "true",
              "mode": "min_latency",
              "language_codes": json.dumps(["en"]),
              "keyterms_prompt": json.dumps(_ws_keyterms(), ensure_ascii=False)}
    return f"{WS_URL}?{_ue(params)}"


def parse_turn(msg: dict) -> dict:
    """Unpack a Turn event into a compact dict — pure, testable without network."""
    words = []
    for w in (msg.get("words") or [])[:40]:
        words.append({"text": w.get("text", ""),
                      "speaker": w.get("speaker", msg.get("speaker_label", "?")),
                      "start": w.get("start", 0), "end": w.get("end", 0)})
    return {"transcript": msg.get("transcript", ""),
            "end_of_turn": bool(msg.get("end_of_turn", False)),
            "turn_order": msg.get("turn_order", 0),
            "speaker": msg.get("speaker_label", "?"),
            "confidence": msg.get("end_of_turn_confidence", 0),
            "words": words}


def read_pcm16_mono_16k(path: str) -> bytes:
    """Read any wav/aiff -> PCM 16-bit mono 16kHz (no ffmpeg needed)."""
    p = Path(path)
    if not p.exists():
        alt = BUILD / path
        p = alt if alt.exists() else p
    raw, nch, width, fr = b"", 1, 2, SAMPLE_RATE
    suffix = p.suffix.lower()
    if suffix == ".wav":
        with wave.open(str(p), "rb") as w:
            nch, width, fr = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    elif suffix in (".aiff", ".aif", ".aifc"):
        with aifc.open(str(p), "rb") as a:
            nch, width, fr = a.getnchannels(), a.getsampwidth(), a.getframerate()
            raw = a.readframes(a.getnframes())
    else:
        raise SystemExit(f"Unsupported file for realtime (supports .wav/.aiff only): {suffix}")
    if width != 2:
        raw = audioop.lin2lin(raw, width, 2)
    if nch > 1:
        raw = audioop.tomono(raw, 2, 1, 1)
    if fr != SAMPLE_RATE:
        raw, _ = audioop.ratecv(raw, 2, 1, fr, SAMPLE_RATE, None)
    return raw


def stream_session(pcm: bytes, key: str, realtime_factor: float = 1.0,
                   label: str = "realtime") -> dict:
    """Open one WS session, pump PCM in real time, return turns + truly measured ms."""
    import websocket  # websocket-client (already in requirements)
    t_start = time.perf_counter()
    t_open = None  # mark after WS handshake — ms measured from audio send
    partials, finals, speakers = [], [], set()
    revisions = []  # end-of-session SpeakerRevision (correction, +~400ms, excluded from realtime)
    applied = {}  # config the server actually applied (Begin echo — catches ignored param typos)
    t_first_partial = t_first_final = None
    done, terminated = threading.Event(), threading.Event()
    lock = threading.Lock()

    def ms() -> float:
        base = t_open or t_start
        return (time.perf_counter() - base) * 1000.0

    def on_message(ws, message):
        nonlocal t_first_partial, t_first_final
        try:
            data = json.loads(message)
        except Exception:
            return
        mtype = data.get("type", "")
        if mtype == "Begin":
            cfg = data.get("configuration") or {}
            applied.update({k: cfg.get(k) for k in ("model", "mode") if cfg.get(k)})
            if applied.get("model") and applied["model"] != "u3-rt-pro":
                print(f"\n[{label}] WARNING: server applied model {applied['model']} "
                      f"(asked u3-rt-pro — check params).")
            print(f"[{label}] Session started: {str(data.get('id', ''))[:8]}... "
                  f"(model={applied.get('model', '?')}, mode={applied.get('mode', '?')})")
        elif mtype == "Turn":
            t = parse_turn(data)
            if not t["transcript"]:
                return
            with lock:
                # Turns with <~1s audio get PENDING from the server (embedding not ready) —
                # keep them out of the speakers set to avoid phantom label splits.
                if t["speaker"] not in ("?", "PENDING"):
                    speakers.add(str(t["speaker"]))
                if t["end_of_turn"]:
                    if t_first_final is None:
                        t_first_final = ms()
                    finals.append(t)
                    print(f"[{label}][FINAL {ms():.0f}ms][Speaker {t['speaker']}] {t['transcript']}")
                else:
                    if t_first_partial is None:
                        t_first_partial = ms()
                    partials.append(t)
                    sys.stdout.write(f"\r[{label}][PARTIAL {ms():.0f}ms] {t['transcript'][:80]}")
                    sys.stdout.flush()
        elif mtype == "Termination":
            print(f"\n[{label}] Session terminated: "
                  f"{data.get('audio_duration_seconds', '?')}s audio processed")
            terminated.set()
            done.set()
        elif "revision" in mtype.lower() or mtype == "SpeakerRevision":
            # End-of-stream correction (before Termination, +~400ms): log only,
            # do not rewrite the demoed realtime labels — longer speech means better labels.
            with lock:
                revisions.append({"turn_order": data.get("turn_order"),
                                  "speaker": data.get("speaker_label", "?")})
            print(f"\n[{label}] Speaker labels revised (longer speech = better labels).")

    def on_error(ws, error):
        print(f"\n[{label}] WS error: {error}")

    def on_close(ws, *a):
        done.set()

    def on_open(ws):
        nonlocal t_open
        t_open = time.perf_counter()
        print(f"[{label}] WS connected: {(t_open - t_start) * 1000:.0f}ms (handshake, once per session).")

        def sender():
            try:
                # Trailing silence helps VAD emit end_of_turn FINAL before Terminate.
                padded = pcm + b"\x00" * int(SAMPLE_RATE * 2 * 0.8)
                for i in range(0, len(padded), CHUNK_BYTES):
                    if done.is_set():
                        break
                    ws.send(padded[i:i + CHUNK_BYTES], opcode=0x2)
                    time.sleep((CHUNK_BYTES / 2 / SAMPLE_RATE) / max(realtime_factor, 0.1))
                time.sleep(1.0)
            finally:
                try:
                    ws.send(json.dumps({"type": "Terminate"}))
                except Exception:
                    pass
                # Let the server deliver the last FINAL before closing (no billing hang).
                terminated.wait(timeout=15)
                try:
                    ws.close()
                except Exception:
                    pass
                done.set()
        threading.Thread(target=sender, daemon=True).start()

    ws = websocket.WebSocketApp(build_ws_url(), header={"Authorization": key},
                                on_open=on_open, on_message=on_message,
                                on_error=on_error, on_close=on_close)
    # Billing-hang guard: close the session after 60s even without server Termination.
    def _force_close():
        try:
            ws.close()
        except Exception:
            pass
        done.set()
    timer = threading.Timer(60.0, _force_close)
    timer.daemon = True
    timer.start()
    try:
        ws.run_forever(ping_interval=20, ping_timeout=10)
    finally:
        try:
            timer.cancel()
        except Exception:
            pass
    return {"partials": partials, "finals": finals,
            "speakers": sorted(speakers),
            "speaker_revisions": revisions,
            "applied": applied,
            "t_first_partial_ms": round(t_first_partial or -1, 0),
            "t_first_final_ms": round(t_first_final or -1, 0),
            "final_text": " ".join(t["transcript"] for t in finals).strip()}


def _opt(args: list, *names: str, default: str = "") -> str:
    """Parse --src=X or --src X style options (either paste style works)."""
    for i, a in enumerate(args):
        for n in names:
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
            if a == n and i + 1 < len(args) and not args[i + 1].startswith("--"):
                return args[i + 1]
    return default


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args or _opt(args, "--src") == "":
        print(__doc__)
        return 0
    src = _opt(args, "--src")
    src2 = _opt(args, "--src2")
    barge_demo = "--barge-in-demo" in args
    factor = float(_opt(args, "--factor", default="1.0"))
    # Distinguish a missing flag (None = legacy terminal auto path) from
    # --confirm="" (live path: wait for the user to say YES).
    # The old `_opt(...) or None` swallowed "" into None, making realtime auto-BOOK
    # right after STT + booking an empty slot that blocked the later confirm scene in the video.
    confirm_present = any(a == "--confirm" or a.startswith("--confirm=") for a in args)
    confirm = _opt(args, "--confirm", default="") if confirm_present else None

    key = load_api_key()
    if not key:
        print("Missing key: export ASSEMBLYAI_API_KEY.")
        print("Fallback: run typed try-out (no key needed):")
        print('  python3 src/main.py "Book a cardiology checkup tomorrow morning at 9"')
        return 2
    print("== VoiceCare realtime (WS custom -> u3-rt-pro + min_latency + diarization) ==")
    pcm = read_pcm16_mono_16k(src)
    print(f"Source: {src} ({len(pcm) / 2 / SAMPLE_RATE:.1f}s audio 16k mono)")

    if barge_demo and src2:
        # Live barge-in demo over WS: turn 1 (caller) -> agent starts replying
        # -> turn 2 (caller interrupts) arrives mid-reply -> agent stops, uses the newer utterance.
        r1 = stream_session(pcm, key, factor, label="turn-1")
        if not r1["final_text"]:
            print("Turn 1 unclear (check file/network), retrying.")
            return 3
        print("Agent is replying (2s simulation, interrupting mid-reply)...")
        pcm2 = read_pcm16_mono_16k(src2)
        t0 = time.perf_counter()
        r2 = stream_session(pcm2, key, factor, label="turn-2-barge")
        dt = (time.perf_counter() - t0) * 1000
        print(f"[BARGE-IN] agent stopped after {dt:.0f}ms, hearing the new turn: '{r2['final_text']}'")
        print("[BARGE-IN] using the newer utterance (clearer) — interruption handling.")
        final_text = (r1["final_text"] + " " + r2["final_text"]).strip()
        sess = r2
    else:
        sess = stream_session(pcm, key, factor)
        final_text = sess["final_text"]

    if not final_text:
        print("WS returned no FINAL (weak network/empty file?) — typed fallback:")
        print('  python3 src/main.py "Book a cardiology checkup tomorrow morning at 9"')
        return 3
    print(f"First PARTIAL after audio send: {sess['t_first_partial_ms']}ms | "
          f"First FINAL: {sess['t_first_final_ms']}ms (measured from audio send).")
    print(f"Speakers in session: {sess['speakers']}")

    from main import run_pipeline
    r = run_pipeline(final_text, confirm_text=confirm)
    print(f"Patient said (realtime FINAL): {r['transcript']}")
    try:
        from main import transcript_en_gloss, entities_en
        print(f"EN: {transcript_en_gloss(r['transcript'], r.get('entities', {}))}")
    except Exception:
        pass
    print(f"Understood: {r['entities']} (confidence {r['confidence']})")
    try:
        from main import entities_en as _ee
        print(f"Understood (EN): {_ee(r.get('entities', {}))}")
    except Exception:
        pass
    for e in r["events"]:
        print(f"  [{e.split(':')[0]}] {e}")
    if r.get("readback"):
        print(f"Readback: {r['readback']}")
    print(f"Agent reply: {r['reply']}")
    if r.get("booking"):
        print(f"Booked: {r['booking']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
