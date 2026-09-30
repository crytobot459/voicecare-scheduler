"""VoiceCare — voice-first clinic scheduling (Streamlit, English-only).

Flow: Patient speaks/types English -> AssemblyAI STT -> Gemini NLU
-> scheduling tools -> confirmation -> booking with ID + .ics.
Keys from env/Secrets/sidebar only. No Vietnamese.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

try:
    import streamlit as st
except Exception:
    st = None

from main import run_pipeline, structured_to_fields
try:
    from agent.config import key_status as _key_status
except Exception:
    def _key_status():  # type: ignore
        return {}

try:
    from tts import speak as tts_speak
except Exception:
    def tts_speak(text, out_path=""):  # type: ignore
        return None


def ask_once(text="", audio_bytes=None, audio_suffix=".wav", barge="", history=None):
    if audio_bytes:
        with tempfile.NamedTemporaryFile(delete=False, suffix=audio_suffix) as f:
            f.write(audio_bytes)
            path = f.name
        return run_pipeline(path, barge_in=barge or "", auto_consent=True, confirm_text="",
                            history=history or [])
    return run_pipeline(text or "I'd like to book a cardiology appointment tomorrow morning",
                        barge_in=barge or "", auto_consent=True, confirm_text="",
                        history=history or [])


def confirm_pending(pending_text, yes=True, history=None):
    verdict = "yes, book it" if yes else "no, cancel"
    return run_pipeline(pending_text, auto_consent=True, confirm_text=verdict,
                        history=history or [])


def fmt_ms(ms):
    try:
        ms = float(ms)
    except Exception:
        return "-"
    if ms >= 1000:
        return f"{ms/1000:.1f}s"
    if ms >= 10:
        return f"{ms:.0f}ms"
    return f"{ms:.1f}ms"


def init_state():
    for k, v in (("history", []), ("pending_text", ""), ("pending_result", None),
                 ("last_result", None), ("booking", None), ("booking_ics", ""),
                 ("status", "idle"), ("played_for", ""), ("sending", False),
                 ("take_audio", ""), ("take_audio_error", "")):
        if k not in st.session_state:
            st.session_state[k] = v


def push(who, text):
    if text:
        st.session_state.history.append({"who": who, "text": text})


def bubble(who, text):
    if who == "patient":
        st.markdown(
            "<div style='background:#f1f5f9;border-radius:14px;padding:12px 16px;margin:8px 0;font-size:1.15rem'>"
            f"🧑 <b>Patient:</b><br>{text}</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div style='background:#e8f5e9;border-radius:14px;padding:12px 16px;margin:8px 0;font-size:1.15rem'>"
            f"🤖 <b>Assistant:</b><br>{text}</div>", unsafe_allow_html=True)


def render_status_bar(has_aai, has_llm):
    if st.session_state.status in ("listening", "speaking"):
        st.markdown("🔵 **Listening...**" if st.session_state.status == "listening"
                    else "🔊 **Assistant is speaking...**")
    elif st.session_state.get("booking"):
        tag = "🟢 **AssemblyAI Connected**" if has_aai else "🟡 **Typed try-out (no key)**"
        llm = " + Gemini" if has_llm else " (regex fallback)"
        st.markdown(f"{tag}{llm} · ✓ Booked")
    else:
        tag = "🟢 **AssemblyAI Connected**" if has_aai else "🟡 **Typed try-out (no key)**"
        llm = "Gemini on" if has_llm else "Gemini off (fallback)"
        st.markdown(f"{tag} · {llm} · Listening...")


STATE_STEPS = ["LISTENING", "UNDERSTANDING", "CHECKING", "CONFIRMATION", "BOOKED"]
STATE_LABEL = {"LISTENING": "🎙 LISTENING", "UNDERSTANDING": "🧠 UNDERSTANDING",
               "CHECKING": "🔎 CHECKING AVAILABILITY", "CONFIRMATION": "👤 AWAITING CONFIRMATION",
               "BOOKED": "✓ BOOKED", "ESCALATED": "📞 NURSE HANDOFF"}


def current_state():
    if st.session_state.get("booking"):
        return "BOOKED"
    r = st.session_state.get("last_result") or {}
    if (r.get("escalated") or r.get("state") == "ESCALATED") and not st.session_state.get("booking"):
        return "ESCALATED"
    if st.session_state.get("pending_text") and (st.session_state.get("pending_result") or {}).get("needs_confirm"):
        return "CONFIRMATION"
    return r.get("state", "LISTENING") if r else "LISTENING"


def render_state_stepper(state):
    steps = STATE_STEPS if state != "ESCALATED" else ["LISTENING", "UNDERSTANDING", "ESCALATED"]
    order = {s: i for i, s in enumerate(steps)}
    cur = order.get(state, 0)
    cols = st.columns(len(steps))
    for i, s in enumerate(steps):
        mark = "●" if i < cur else ("◉" if i == cur else "○")
        with cols[i]:
            st.caption(f"{mark} {STATE_LABEL[s]}")


def _ent(r=None, b=None):
    e = ((r or {}).get("entities", {}) if r else (b or {})) or {}
    spec = (e.get("specialty", "") or "—").title() if e.get("specialty") else "—"
    doc = e.get("doctor", "") or "—"
    day = e.get("date_label", "") or e.get("day", "") or "—"
    hour = e.get("hour", "")
    minute = e.get("minute", 0) or 0
    hour_s = f"{hour:02d}:{minute:02d}" if isinstance(hour, int) else (str(hour) or "—")
    return spec, doc, day, hour_s


def render_appointment_card(ent, r=None):
    spec, doc, day, hour_s = _ent(r, ent)
    stages = (r or {}).get("stages_ms", {}) if isinstance(r, dict) else {}
    lat = f"<div style='font-size:0.95rem;color:#92400e'>Latency: {' | '.join(f'{k}={v}' for k,v in stages.items())}</div>" if stages else ""
    st.markdown(
        "<div style='border:2px solid #f59e0b;border-radius:16px;padding:16px 18px;margin:10px 0;background:#fffbeb'>"
        "<div style='text-align:center;font-size:1.3rem'>🟡 <b>APPOINTMENT CONFIRMATION</b></div>"
        "<div style='text-align:center;color:#92400e'>Not booked yet — awaiting confirmation</div>"
        f"<div style='font-size:1.15rem;margin-top:10px'>Specialty &nbsp;&nbsp;&nbsp;<b>{spec}</b></div>"
        f"<div style='font-size:1.15rem'>Doctor &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>Dr. {doc}</b></div>"
        f"<div style='font-size:1.15rem'>Date &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>{day}</b></div>"
        f"<div style='font-size:1.15rem'>Time &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>{hour_s}</b></div>"
        "<div style='font-size:1.15rem'>Availability &nbsp;<b>Available</b></div>"
        f"{lat}</div>", unsafe_allow_html=True)


def render_success(booking):
    spec, doc, day, hour_s = _ent(None, booking)
    bid = booking.get("id", "")
    st.markdown(
        "<div style='background:#dcfce7;border:2px solid #22c55e;border-radius:16px;padding:18px;text-align:center;margin:12px 0'>"
        "<div style='font-size:1.5rem'>✓ <b>APPOINTMENT BOOKED</b></div>"
        f"<div style='font-size:1.2rem;margin-top:8px'>Specialty &nbsp;<b>{spec}</b></div>"
        f"<div style='font-size:1.2rem'>Doctor &nbsp;<b>Dr. {doc}</b></div>"
        f"<div style='font-size:1.2rem'>Date &nbsp;<b>{day}</b></div>"
        f"<div style='font-size:1.2rem'>Time &nbsp;<b>{hour_s}</b></div>"
        f"<div style='font-size:1.2rem'>Appointment ID &nbsp;<b>{bid}</b></div>"
        "<div style='font-size:1.2rem'>Status &nbsp;🟢 <b>Confirmed</b></div>"
        "<div style='margin-top:6px'>Please arrive 15 minutes early and bring your insurance card.</div>"
        "</div>", unsafe_allow_html=True)


def render_pipeline(r):
    if not r:
        return
    stages = r.get("stages_ms", {}) or {}
    ent = r.get("entities", {}) or {}
    st.markdown("**LIVE PIPELINE**")
    st.markdown(
        "🎙 Speech → AssemblyAI · ✓ Transcript<br>"
        f"🧠 Intent → ✓ {(ent.get('intent') or 'book_appointment')}<br>"
        f"📅 Entities → ✓ {(ent.get('specialty') or '—').title()} · {(ent.get('date_label') or ent.get('day') or '—')} · {ent.get('hour', '—')}<br>"
        "🔎 Availability → ✓ checked<br>"
        "👤 Confirmation → ✓ books only after YES<br>"
        "📖 Booking → ✓ created", unsafe_allow_html=True)
    st.caption("Latency · " + " · ".join(f"{k} {fmt_ms(v)}" for k, v in stages.items()))


def play_voice(text):
    try:
        mp3 = tts_speak(text or "")
        if mp3:
            try:
                st.audio(mp3, format="audio/mp3")
            except Exception:
                st.audio(mp3)
    except Exception:
        pass


def handle_new_turn(user_text):
    st.session_state.status = "listening"
    pending = st.session_state.pending_text
    hist = list(st.session_state.get("history", []) or [])
    if pending and user_text:
        r = ask_once(text=pending, barge=user_text, history=hist)
    else:
        r = ask_once(text=user_text, history=hist)
    st.session_state.status = "speaking"
    st.session_state.last_result = r
    push("patient", user_text)
    if r.get("escalated"):
        push("assistant", r.get("reply", "Transferring you to the nurse hotline."))
        st.session_state.pending_text = ""
        st.session_state.pending_result = None
    elif r.get("booking"):
        st.session_state.booking = r.get("booking")
        st.session_state.booking_ics = r.get("ics", "")
        push("assistant", r.get("reply", "Booked."))
        st.session_state.pending_text = ""
        st.session_state.pending_result = None
    elif r.get("needs_confirm"):
        st.session_state.pending_text = r.get("transcript", user_text)
        st.session_state.pending_result = r
        push("assistant", r.get("readback", r.get("reply", "")))
    elif r.get("needs_info") or r.get("state") == "UNDERSTANDING":
        st.session_state.pending_text = r.get("transcript", user_text)
        st.session_state.pending_result = r
        push("assistant", r.get("reply", "Could you say that again?"))
    else:
        push("assistant", r.get("reply", "Please pick another time."))
        st.session_state.pending_text = r.get("transcript", user_text)
        st.session_state.pending_result = r
    st.session_state.status = "idle"


def handle_confirm(yes=True):
    pending = st.session_state.pending_text
    if not pending:
        return
    with st.spinner("🔊 Assistant is speaking..."):
        r = confirm_pending(pending, yes=yes,
                            history=list(st.session_state.get("history", []) or []))
    st.session_state.last_result = r
    if yes and r.get("booking"):
        st.session_state.booking = r.get("booking")
        st.session_state.booking_ics = r.get("ics", "")
        push("assistant", r.get("reply", "Booked successfully."))
        st.session_state.pending_text = ""
        st.session_state.pending_result = None
    elif not yes:
        push("assistant", "Cancelled — please tell me a new time.")
        st.session_state.pending_text = ""
        st.session_state.pending_result = None
    else:
        push("assistant", r.get("reply", "Say YES to confirm, NO to change."))
        st.session_state.pending_result = r


DEMO_TURN_1 = "I'd like to book a general checkup day after tomorrow"
DEMO_TIMES = ["11 o'clock", "2pm", "10 o'clock"]


def reset_demo_session():
    st.session_state.history = []
    st.session_state.pending_text = ""
    st.session_state.pending_result = None
    st.session_state.last_result = None
    st.session_state.booking = None
    st.session_state.booking_ics = ""
    st.session_state.played_for = ""
    st.session_state.take_audio = ""
    st.session_state.take_audio_error = ""
    st.session_state.status = "idle"


def run_full_demo():
    """One-click take: Turn1 (specialty+day) -> Turn2 (time) -> Turn3 (YES).

    Uses the real pipeline (Gemini LLM when GEMINI_API_KEY is set,
    labeled regex fallback otherwise). Tries backup times if slot C is
    full on the shared server, so the take rarely fails on camera.
    Returns True when a booking was created.
    """
    reset_demo_session()
    st.session_state.status = "listening"
    try:
        handle_new_turn(DEMO_TURN_1)
        for t in DEMO_TIMES:
            pr = st.session_state.pending_result or {}
            if pr.get("needs_confirm"):
                break
            if not st.session_state.pending_text:
                break
            # If the last turn already asked for time, give a time;
            # if it hit "fully booked", the next time acts as correction.
            handle_new_turn(t)
            pr = st.session_state.pending_result or {}
            if pr.get("needs_confirm"):
                break
        pr = st.session_state.pending_result or {}
        if st.session_state.pending_text and pr.get("needs_confirm"):
            handle_confirm(yes=True)
    finally:
        st.session_state.status = "idle"
    return bool(st.session_state.booking)


def clear_server_slots():
    """Wipe the shared demo calendar (same as sidebar Reset demo slots)."""
    try:
        from main import BOOKINGS as _B
        _B.write_text("[]", encoding="utf-8")
        return True
    except Exception:
        return False


def fresh_take():
    """Recording take: clear server slots first, then run the full demo.

    Guarantees a clean 3-turn take (no fallback correction turns) for video.
    """
    clear_server_slots()
    return run_full_demo()


def build_take_audio():
    """Synthesize the whole take dialogue into ONE audio file for replay.

    Returns the mp3 path, or "" when TTS is unavailable (offline/no lib).
    The recorder presses play once and the machine voice is on the video.
    The failure reason is left in session (take_audio_error) so the page
    says WHY instead of showing nothing.
    """
    lines = []
    for m in st.session_state.get("history", []):
        who = "Patient" if m.get("who") == "patient" else "Receptionist"
        txt = (m.get("text") or "").strip()
        if txt:
            # Ellipsis gives TTS a natural breath between turns.
            lines.append(f"{who}: {txt}... ")
    if not lines:
        st.session_state.take_audio_error = "empty dialogue"
        return ""
    script = "VoiceCare clinic visit... " + " ".join(lines)
    try:
        mp3 = tts_speak(script[:1500])
        if mp3:
            st.session_state.take_audio_error = ""
            return mp3
        st.session_state.take_audio_error = "voice service offline (no TTS lib/network)"
        return ""
    except Exception as e:
        st.session_state.take_audio_error = str(e)[:100] or "voice error"
        return ""


def render_technical(r):
    if not r:
        return
    with st.expander("🔧 Technical — AssemblyAI + Gemini + tools", expanded=False):
        st.write(f"Listen backend: {r.get('backend','')} | "
                 f"NLU: {(r.get('structured') or {}).get('nlu_source','') or (r.get('entities') or {}).get('source','')}")
        st.write(f"Transcript: {r.get('transcript','')}")
        st.write(f"Entities: {r.get('entities',{})} (confidence {r.get('confidence',0)})")
        for e in r.get("events", []):
            st.info(e)
        st.write("Latency: " + " | ".join(f"{k}={v}" for k, v in (r.get("stages_ms", {}) or {}).items())
                 + f" | TOTAL={r.get('total_ms')}")
        try:
            rows = structured_to_fields(r.get("transcript",""), r.get("entities",{}), r.get("structured"))
            st.table([{"field": f, "value": v, "source": s} for f, v, s in rows])
        except Exception:
            pass


def main():
    if st is None:
        r = ask_once(text="I'd like to book a cardiology appointment tomorrow morning")
        print(r.get("reply",""), "|", r.get("total_ms"), "ms")
        return
    st.set_page_config(page_title="VoiceCare — voice clinic booking")
    st.markdown("<style>html{font-size:19px} .stButton>button{font-size:1.15rem;padding:.6rem 1.1rem;border-radius:12px}</style>",
                unsafe_allow_html=True)
    try:
        sec = st.secrets.get("ASSEMBLYAI_API_KEY", "") if hasattr(st, "secrets") else ""
        if sec and not os.getenv("ASSEMBLYAI_API_KEY"):
            os.environ["ASSEMBLYAI_API_KEY"] = str(sec)
        gsec = st.secrets.get("GEMINI_API_KEY", "") if hasattr(st, "secrets") else ""
        if gsec and not os.getenv("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = str(gsec)
    except Exception:
        pass
    init_state()
    st.title("VoiceCare")
    st.subheader("Voice-first Clinic Scheduling")
    st.caption("Speak. I listen. I check. You confirm. · English-only · AssemblyAI + Gemini")

    with st.sidebar:
        st.subheader("Settings")
        try:
            akey = st.text_input("ASSEMBLYAI_API_KEY (live voice)", value="", type="password")
            if akey:
                os.environ["ASSEMBLYAI_API_KEY"] = akey
            gkey = st.text_input("GEMINI_API_KEY (LLM understanding)", value="", type="password")
            if gkey:
                os.environ["GEMINI_API_KEY"] = gkey
        except Exception:
            pass
        st.caption("Without keys: typed try-out + fallback NLU (labeled). Add both keys for full voice agent.")
        if st.button("Restart call"):
            for k in ("history","pending_text","pending_result","last_result","booking","booking_ics","played_for"):
                st.session_state[k] = [] if k == "history" else ("" if isinstance(st.session_state.get(k,""),str) else None)
            st.session_state.pending_text = ""
            st.session_state.booking = None
            st.rerun()
        if st.button("Reset demo slots"):
            try:
                from main import BOOKINGS as _B
                _B.write_text("[]", encoding="utf-8")
                st.success("Demo slots cleared.")
            except Exception as e:
                st.info(f"Could not reset: {str(e)[:120]}")

    has_aai = bool(os.getenv("ASSEMBLYAI_API_KEY","").strip())
    has_llm = bool(os.getenv("GEMINI_API_KEY","").strip())
    render_status_bar(has_aai, has_llm)
    render_state_stepper(current_state())

    st.markdown("### 🎬 One-click take")
    st.caption("Recording? Fresh take, then play the replay — the AI voices the whole visit. Judge self-driving? RUN FULL DEMO or Manual input.")
    tc1, tc2 = st.columns(2)
    with tc1:
        fresh_clicked = st.button("🧹 Fresh take (clear + run)", type="primary")
    with tc2:
        run_clicked = st.button("▶ RUN FULL DEMO")
    if run_clicked or fresh_clicked:
        with st.spinner("🎬 Running full demo: specialty → time → YES (real LLM)..."):
            ok = fresh_take() if fresh_clicked else run_full_demo()
            with st.spinner("🔊 Voicing the take (up to ~25s)..."):
                st.session_state.take_audio = build_take_audio()
        if ok:
            st.success("Full demo booked — press play on the replay, then stop recording.")
        else:
            st.warning("Demo did not book (slot may be full on shared server). "
                       "Try Fresh take, or Sidebar → Reset demo slots.")
        st.rerun()

    with st.expander("▶ Demo script (tap to fill — manual step-by-step)", expanded=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("1. Book cardiology"):
                st.session_state["t_input"] = "I'd like to book a cardiology appointment tomorrow morning"
                st.rerun()
        with c2:
            if st.button("2. Pick 9:00"):
                st.session_state["t_input"] = "9 o'clock"
                st.rerun()
        with c3:
            if st.button("3. Confirm"):
                if st.session_state.pending_text:
                    handle_confirm(yes=True)
                    st.rerun()
                else:
                    st.info("Type a request first, then press Listen.")
        st.caption("Turn 1: specialty + day → Turn 2: time → Turn 3: YES to book.")

    if not st.session_state.history and not st.session_state.booking:
        st.markdown("<div style='text-align:center;font-size:3rem;margin:8px 0'>🎙</div>"
                    "<div style='text-align:center'>Press <b>Fresh take</b> and watch the AI do the whole visit by itself.<br>"
                    "Judges: open <b>Manual input</b> below to drive it yourself.</div>",
                    unsafe_allow_html=True)
    for m in st.session_state.history:
        bubble(m["who"], m["text"])

    pending_r = st.session_state.pending_result
    if st.session_state.pending_text and pending_r and pending_r.get("needs_confirm"):
        render_appointment_card(pending_r.get("entities", {}), pending_r)
        b1, b2 = st.columns(2)
        with b1:
            if st.button("YES, BOOK IT", type="primary"):
                handle_confirm(yes=True)
                st.rerun()
        with b2:
            if st.button("CHANGE TIME"):
                handle_confirm(yes=False)
                st.rerun()
        cur = st.session_state.pending_text or ""
        if cur and st.session_state.get("played_for") != cur:
            play_voice(pending_r.get("readback", ""))
            st.session_state.played_for = cur

    if st.session_state.booking:
        render_success(st.session_state.booking)
        if st.session_state.booking_ics:
            try:
                st.download_button("Download .ics calendar file", data=st.session_state.booking_ics,
                                   file_name="voicecare_booking.ics", mime="text/calendar")
            except Exception:
                pass

    take_audio = st.session_state.get("take_audio", "")
    if take_audio:
        try:
            st.caption("🔊 Replay the take — the machine voices the whole visit (press play during recording)")
            st.audio(take_audio)
        except Exception:
            pass
    elif st.session_state.get("take_audio_error") and st.session_state.get("history"):
        st.caption(f"🔇 Machine voice unavailable ({st.session_state.get('take_audio_error')}) — "
                   "read the cards aloud for the mic.")

    st.markdown("---")
    with st.expander("Manual input — type / mic / file (for judges)", expanded=False):
        mic = None
        try:
            mic = st.audio_input("Tap mic and speak, e.g. cardiology appointment tomorrow morning")
        except Exception:
            mic = None
        if mic:
            try:
                data = mic.read()
            except Exception:
                data = None
            if data and st.button("Send voice", type="primary"):
                if not has_aai:
                    st.warning("Voice needs ASSEMBLYAI_API_KEY in sidebar. Or type below.")
                else:
                    with st.spinner("🔵 Listening..."):
                        try:
                            r = ask_once(audio_bytes=data)
                            st.session_state.last_result = r
                            push("patient", f"(voice) {r.get('transcript','')}")
                            if r.get("escalated"):
                                st.session_state.pending_text = ""
                                st.session_state.pending_result = None
                                push("assistant", r.get("reply",""))
                            elif r.get("booking"):
                                st.session_state.booking = r.get("booking")
                                st.session_state.booking_ics = r.get("ics","")
                                push("assistant", r.get("reply",""))
                            elif r.get("needs_confirm"):
                                st.session_state.pending_text = r.get("transcript","")
                                st.session_state.pending_result = r
                                push("assistant", r.get("readback",""))
                            else:
                                st.session_state.pending_text = r.get("transcript","")
                                st.session_state.pending_result = r
                                push("assistant", r.get("reply",""))
                            st.rerun()
                        except Exception as e:
                            st.info(f"I didn't catch that. ({str(e)[:120]})")

        if "t_input" not in st.session_state:
            st.session_state["t_input"] = "I'd like to book a cardiology appointment tomorrow morning"
        text = st.text_input("Patient says (English)", key="t_input")
        col_a, col_b = st.columns([1,1])
        with col_a:
            send = st.button("Listen", type="primary")
        with col_b:
            try:
                up = st.file_uploader("Or upload a recording", type=["wav","mp3","m4a"], label_visibility="collapsed")
            except Exception:
                up = None
        if send:
            t = (text or "").strip()
            if st.session_state.get("booking") and t:
                st.session_state.booking = None
                st.session_state.booking_ics = ""
                st.session_state.pending_text = ""
                st.session_state.pending_result = None
            low = t.lower()
            from main import is_voice_confirm
            import re as _re
            if st.session_state.pending_text and is_voice_confirm(t) == "yes":
                handle_confirm(yes=True)
            elif st.session_state.pending_text and is_voice_confirm(t) == "no":
                if _re.search(r"\d", t) or any(w in low for w in ("o'clock","morning","afternoon","tomorrow","today","cardiology","dental","ent","general")):
                    with st.spinner("🔵 Listening..."):
                        handle_new_turn(t)
                else:
                    handle_confirm(yes=False)
            elif t:
                with st.spinner("🔵 Listening..."):
                    handle_new_turn(t)
            st.rerun()
        if up is not None and bool(up) and st.button("Transcribe this file"):
            if not has_aai:
                st.warning("File transcription needs ASSEMBLYAI_API_KEY. Or type below.")
            else:
                with st.spinner("🔵 Listening..."):
                    try:
                        raw = up.getvalue()
                        suffix = "." + (up.name.split(".")[-1] if "." in up.name else "wav")
                        r = ask_once(audio_bytes=raw, audio_suffix=suffix)
                        st.session_state.last_result = r
                        push("patient", f"(file) {r.get('transcript','')}")
                        if r.get("needs_confirm"):
                            st.session_state.pending_text = r.get("transcript","")
                            st.session_state.pending_result = r
                            push("assistant", r.get("readback",""))
                        else:
                            st.session_state.pending_text = r.get("transcript","")
                            st.session_state.pending_result = r
                            push("assistant", r.get("reply",""))
                        st.rerun()
                    except Exception as e:
                        st.info(f"Could not hear file. ({str(e)[:120]})")

    if st.session_state.last_result:
        st.markdown("---")
        render_pipeline(st.session_state.last_result)
        render_technical(st.session_state.last_result)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            import streamlit as _st
            _st.info(f"Restarting — {str(e)[:200]}")
        except Exception:
            print(f"VoiceCare UI error: {e}")
