#!/usr/bin/env python3
"""VoiceCare — AssemblyAI Voice Agent API (English-only direct voice path).

Secondary scene (5s --print-session). Primary demo is Streaming WS + app LLM loop.
Judge flow: browser --token--> agent WS --transcript.user--> LLM --> tool.call
(check_availability/book) --> tool.result --> reply.audio + consent + session.end.
No network needed to test pure funcs (pytest).
"""
import base64
import json
import os
import time
from pathlib import Path

AGENTS_BASE = "https://agents.assemblyai.com"
WS_URL = "wss://agents.assemblyai.com/v1/ws"

HERE = Path(__file__).resolve().parent
try:
    from agent.config import EN_KEYTERMS
except Exception:
    try:
        from main import VI_KEYTERMS as EN_KEYTERMS  # compat alias, now English values
    except Exception:
        EN_KEYTERMS = ["appointment", "cardiology", "tomorrow morning", "yes", "no", "confirm"]


SYSTEM_PROMPT_EN = (
    "You are the VoiceCare clinic receptionist. Speak English, slowly and clearly. "
    "Your only task: book appointments in 5 steps — ask specialty first "
    "(Cardiology, General Internal Medicine, ENT, Dental), then day, then time; "
    "check the slot; read back specialty/doctor/date/time; call the book tool "
    "only after the patient says YES. If full, ASK to change time, never auto-switch. "
    "Ask phone last for confirmation. If unclear twice, transfer to a nurse. "
    "If interrupted, stop, listen to the new turn, use the newer one. "
    "Each reply 1-2 short sentences."
)

GREETING_EN = "Hi, this is VoiceCare. Which specialty do you need?"

# Back-compat aliases (old tests import VI names — now English values)
SYSTEM_PROMPT_VI = SYSTEM_PROMPT_EN
GREETING_VI = GREETING_EN


def _keyterms_en() -> list:
    return [k for k in EN_KEYTERMS if len(k) <= 50][:100]


def _keyterms_vi() -> list:
    return _keyterms_en()


def build_tools_local() -> list:
    """Two function-tools: check_availability (read-only) + book_appointment (YES-gated)."""
    return [
        {
            "type": "function",
            "name": "check_availability",
            "description": "Check whether an exam slot is free (07:00-17:00, per-specialty duplicate guard).",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {"type": "string", "description": "cardiology/general internal medicine/ent/dental"},
                    "day": {"type": "string", "description": "today/tomorrow/tomorrow morning/day after tomorrow"},
                    "hour": {"type": "number", "description": "hour 7-17"},
                },
                "required": ["day", "hour"],
            },
        },
        {
            "type": "function",
            "name": "book_appointment",
            "description": "Finalize booking ONLY after the patient says YES. Never call before confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {"type": "string"},
                    "day": {"type": "string"},
                    "hour": {"type": "number"},
                    "phone": {"type": "string", "description": "may be empty"},
                },
                "required": ["specialty", "day", "hour"],
            },
        },
    ]


def build_inline_session(extra_keyterms: list | None = None) -> dict:
    """Inline session.update body — no stored agent needed, suits hackathon dynamics.

    Mirrors stored-agent fields 1-1 (system_prompt/greeting/tools/input/output).
    """
    kt = (extra_keyterms or []) + _keyterms_en()
    # dedup preserving order
    seen, uniq = set(), []
    for k in kt:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    return {
        "type": "session.update",
        "session": {
            "system_prompt": SYSTEM_PROMPT_EN,
            "greeting": GREETING_EN,
            "tools": build_tools_local(),
            "input": {
                "format": {"encoding": "audio/pcm"},
                "language_codes": ["en"],
                "keyterms": uniq[:100],
                "transcription_mode": "min_latency",
                "turn_detection": {
                    "interrupt_response": True,
                    "interruption_delay": 200,
                },
            },
            "output": {
                "type": "audio",
                "voice": "anna",
                "format": {"encoding": "audio/pcm"},
            },
        },
    }


def build_stored_agent_body(name: str = "VoiceCare Scheduler") -> dict:
    """POST /v1/agents body — create once, deploy browser + phone on the same agent_id."""
    inline = build_inline_session()["session"]
    return {
        "name": name,
        "system_prompt": inline["system_prompt"],
        "greeting": inline["greeting"],
        "voice": {"voice_id": "anna"},
        "tools": [
            {
                "type": "function",
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
                "timeout_seconds": 20,
                "execution_mode": "interactive",
            }
            for t in inline["tools"]
        ],
        "input": inline["input"],
        "output": {"type": "audio", "voice": "anna",
                   "format": {"encoding": "audio/pcm"}},
    }


def mint_token(api_key: str, expires_in: int = 300,
               max_session: int = 600) -> dict:
    """GET /v1/token — server mints, browser uses once, key never leaks."""
    import urllib.request
    url = (f"{AGENTS_BASE}/v1/token?expires_in_seconds={expires_in}"
           f"&max_session_duration_seconds={max_session}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def create_agent(api_key: str, body: dict | None = None) -> dict:
    import urllib.request
    data = json.dumps(body or build_stored_agent_body()).encode("utf-8")
    req = urllib.request.Request(
        f"{AGENTS_BASE}/v1/agents", data=data,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode("utf-8"))
        return out


def handle_tool_call(name: str, args: dict) -> dict:
    """Client executes the tool the agent calls — pure logic, shared with main.py.

    Returns a dict to send back as tool.result. Consent gate: book only writes when
    args has confirmed=true AND transcript evidence contains strict YES.
    Client-controlled confirmed alone is NOT enough (anti prompt-injection).
    """
    try:
        from main import check_availability, book, is_voice_confirm
    except Exception:
        return {"ok": False, "error": "tool backend not loaded"}
    if name == "check_availability":
        res = check_availability({"specialty": args.get("specialty", ""),
                                  "day": args.get("day", ""),
                                  "hour": args.get("hour")})
        ok, msg = res[0], res[1]
        out = {"ok": ok, "message": msg or "available"}
        if len(res) > 2 and res[2] is not None:
            out["suggest_hour"] = res[2]
        return out
    if name == "book_appointment":
        if not args.get("confirmed"):
            return {"ok": False,
                    "error": "missing YES confirmation — ask the patient again before booking"}
        transcript = str(args.get("transcript", "") or args.get("confirm_text", "") or "")
        if transcript and is_voice_confirm(transcript) != "yes":
            return {"ok": False,
                    "error": "transcript has no clear YES — ask the patient again (strict consent)"}
        if not transcript:
            # No transcript evidence: require explicit voice proof, don't trust flag alone.
            return {"ok": False,
                    "error": "missing YES voice proof (transcript) — not booking"}
        rec, _, err = book({"specialty": args.get("specialty", ""),
                            "day": args.get("day", ""),
                            "hour": args.get("hour"),
                            "minute": args.get("minute", 0),
                            "phone": args.get("phone", "")}, consent=True)
        if err or not rec:
            return {"ok": False, "error": err or "missing day/time"}
        return {"ok": True, "booking": rec}
    return {"ok": False, "error": f"unknown tool: {name}"}


def parse_agent_event(msg: dict) -> dict:
    """Unpack a WS event into a compact dict — pure, testable without network."""
    t = msg.get("type", "")
    if t == "transcript.user":
        return {"kind": "user_final", "text": msg.get("text", msg.get("transcript", ""))}
    if t == "transcript.user.delta":
        return {"kind": "user_partial", "text": msg.get("text", msg.get("transcript", ""))}
    if t == "transcript.agent":
        return {"kind": "agent_text", "text": msg.get("text", msg.get("transcript", ""))}
    if t == "transcript.agent.delta":
        return {"kind": "agent_partial", "text": msg.get("text", msg.get("transcript", ""))}
    if t == "tool.call":
        return {"kind": "tool_call",
                "tool": msg.get("name", msg.get("tool", "")),
                "args": msg.get("arguments", msg.get("args", {})),
                "call_id": msg.get("call_id", msg.get("id", ""))}
    if t in ("reply.started", "reply.audio", "reply.done",
             "input.speech.started", "input.speech.stopped"):
        return {"kind": "signal", "event": t}
    if t in ("session.ready", "session.updated"):
        return {"kind": "ready", "session_id": msg.get("session_id", "")}
    if t == "session.ended":
        return {"kind": "ended"}
    if t == "session.error":
        return {"kind": "error", "error": msg.get("error", msg)}
    return {"kind": "other", "event": t}


def pcm16_24k_to_b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def load_api_key() -> str:
    k = os.getenv("ASSEMBLYAI_API_KEY", "").strip()
    if k:
        return k
    for cand in (HERE.parent.parent / "work" / ".assemblyai_key",
                 HERE.parent / ".assemblyai_key",
                 Path.home() / ".assemblyai_key"):
        try:
            if cand.exists():
                v = cand.read_text(encoding="utf-8").strip()
                if len(v) >= 20:
                    return v
        except Exception:
            pass
    return ""


def run_agent_session(pcm24k: bytes, token: str,
                      on_event=None, max_s: float = 90.0) -> dict:
    """Run one live voice session via the Voice Agent API (needs a real token).

    pcm24k: PCM16 mono 24kHz. Send ~50ms/chunk, receive partial/final + TTS.
    Always send session.end so billing never hangs for 30s.
    """
    import websocket  # websocket-client
    import threading

    partials, finals, agent_texts, agent_partials, tool_calls = [], [], [], [], []
    ready = threading.Event()
    greeting_done = threading.Event()
    done = threading.Event()
    interrupted = {"hit": False}
    ws_holder: dict = {}
    t0 = time.perf_counter()

    def emit(e):
        if on_event:
            try:
                on_event(e)
            except Exception:
                pass

    def on_message(ws, message):
        try:
            data = json.loads(message)
        except Exception:
            return
        e = parse_agent_event(data)
        emit(e)
        if e["kind"] == "ready":
            ready.set()
        elif e["kind"] == "user_partial":
            partials.append(e["text"])
        elif e["kind"] == "user_final":
            finals.append(e["text"])
        elif e["kind"] == "agent_text":
            agent_texts.append(e["text"])
        elif e["kind"] == "agent_partial":
            agent_partials.append(e["text"])
            # NOTE: agent_partial means the AGENT is speaking — not a user barge-in.
            # interrupted is set only on input.speech.* below (user cuts in mid-reply).
        elif e["kind"] == "signal" and e.get("event") == "reply.done":
            # Only send caller audio after greeting — overlapping the greeting drops audio server-side.
            greeting_done.set()
        elif e["kind"] == "signal" and e.get("event") in ("input.speech.started", "input.speech.start"):
            interrupted["hit"] = True
        elif e["kind"] == "tool_call":
            tool_calls.append(e)
            # Execute tool locally, then return tool.result (JSON string per docs).
            res = handle_tool_call(e.get("tool", ""), e.get("args", {}) or {})
            try:
                ws.send(json.dumps({"type": "tool.result",
                                    "call_id": e.get("call_id", ""),
                                    "result": json.dumps(res, ensure_ascii=False)}))
            except Exception:
                pass
        elif e["kind"] in ("ended", "error"):
            done.set()

    def on_open(ws):
        ws_holder["ws"] = ws
        try:
            ws.send(json.dumps(build_inline_session()))
        except Exception:
            pass

        def sender():
            if not ready.wait(timeout=15):
                # Handshake timeout: close cleanly to avoid hanging billing/run_forever.
                try:
                    ws.send(json.dumps({"type": "session.end"}))
                except Exception:
                    pass
                try:
                    ws.close()
                except Exception:
                    pass
                done.set()
                return
            # Wait for greeting to finish (reply.done) before pumping caller audio — free keys still hear it.
            if not greeting_done.wait(timeout=15):
                emit({"kind": "signal", "event": "greeting-timeout"})
            step = int(24000 * 2 * 0.05)  # ~50ms chunk 24k s16 mono
            for i in range(0, len(pcm24k), step):
                if done.is_set():
                    break
                chunk = pcm24k[i:i + step]
                try:
                    ws.send(json.dumps({"type": "input.audio",
                                        "audio": pcm16_24k_to_b64(chunk)}))
                except Exception:
                    break
                time.sleep(0.05)
            # Wait proportional to audio + tool/TTS, not a fixed 6s (billing-safe).
            audio_s = len(pcm24k) / (24000 * 2) if pcm24k else 0
            wait_s = min(20.0, max(4.0, audio_s + 8.0))
            deadline = time.perf_counter() + wait_s
            while time.perf_counter() < deadline and not done.is_set():
                if agent_texts and time.perf_counter() - t0 > audio_s + 12:
                    break
                time.sleep(0.2)
            try:
                ws.send(json.dumps({"type": "session.end"}))
            except Exception:
                pass
            done.wait(timeout=20)
            try:
                ws.close()
            except Exception:
                pass
        threading.Thread(target=sender, daemon=True).start()

    url = f"{WS_URL}?token={token}"
    ws = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                on_error=lambda w, e: emit({"kind": "error",
                                                            "error": str(e)}),
                                on_close=lambda w, *a: done.set())
    timer = threading.Timer(max_s, lambda: (done.set(), _force_close()))
    timer.daemon = True

    def _force_close():
        try:
            w = ws_holder.get("ws")
            if w:
                try:
                    w.send(json.dumps({"type": "session.end"}))
                except Exception:
                    pass
                try:
                    w.close()
                except Exception:
                    pass
        except Exception:
            pass
    try:
        timer.start()
        ws.run_forever(ping_interval=20, ping_timeout=10)
    finally:
        try:
            timer.cancel()
        except Exception:
            pass
    return {"partials": partials, "finals": finals,
            "agent_texts": agent_texts or agent_partials[-1:],
            "agent_partials": agent_partials, "tool_calls": tool_calls,
            "final_text": " ".join(finals).strip(),
            "interrupted": interrupted["hit"],
            "elapsed_s": round(time.perf_counter() - t0, 1)}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="VoiceCare Voice Agent API live")
    ap.add_argument("--print-session", action="store_true",
                    help="print inline session.update body (no network needed)")
    ap.add_argument("--make-agent", action="store_true",
                    help="POST /v1/agents to create a stored agent (needs key)")
    ap.add_argument("--src", default="",
                    help="wav file for a direct voice call (needs token/key)")
    args = ap.parse_args()
    if args.print_session:
        print("# VoiceCare inline session (English-only):")
        print("# - system_prompt/greeting: English receptionist.")
        print("# - input.language_codes=['en'] + keyterms: EN clinic words.")
        print("# - turn_detection.interrupt_response=true: barge-in handling.")
        print("# - tools: check_availability (read-only) + book_appointment (YES-gated).")
        print(json.dumps(build_inline_session(), ensure_ascii=False, indent=2)[:3000])
        return 0
    if args.make_agent:
        key = load_api_key()
        if not key:
            print("Missing key: export ASSEMBLYAI_API_KEY")
            return 2
        print(json.dumps(create_agent(key), ensure_ascii=False, indent=2)[:2000])
        return 0
    if args.src:
        key = load_api_key()
        if not key:
            print("Missing key: export ASSEMBLYAI_API_KEY")
            return 2
        from realtime import read_pcm16_mono_16k
        import audioop
        raw16 = read_pcm16_mono_16k(args.src)
        # realtime reader outputs 16k -> upsample to 24k for the agent API
        raw24, _ = audioop.ratecv(raw16, 2, 1, 16000, 24000, None)
        tok_resp = mint_token(key)
        tok = tok_resp.get("token", "")
        if not tok:
            print(f"No token received: {str(tok_resp)[:200]}")
            return 3
        r = run_agent_session(raw24, tok,
                              on_event=lambda e: print(f"[{e.get('kind')}] "
                                                       f"{str(e)[:160]}"))
        print(f"FINAL: {r['final_text']} | agent: {r['agent_texts'][:2]} "
              f"| tools: {len(r['tool_calls'])} | {r['elapsed_s']}s")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
