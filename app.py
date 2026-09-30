#!/usr/bin/env python3
"""app.py — Secondary HuggingFace demo (Gradio), English-only.
MAIN demo: app_streamlit.py. Same run_pipeline core. Books only on YES.
Keys from Secrets/env only.
"""
try:
    import gradio as gr
except Exception:
    gr = None

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

try:
    from main import run_pipeline, structured_to_fields
except Exception:
    run_pipeline = None

    def structured_to_fields(t, e, s):  # type: ignore
        return []


def en_summary(r):
    ent = (r or {}).get("entities", {}) or {}
    spec = (ent.get("specialty", "") or "—").title()
    doc = ent.get("doctor", "") or "—"
    day = ent.get("date_label", "") or ent.get("day", "") or "—"
    hour = ent.get("hour", "")
    hour_s = f"{hour:02d}:00" if isinstance(hour, int) else (str(hour) or "—")
    return (f"Summary: {spec} with Dr. {doc}, {day} at {hour_s} "
            f"| state={r.get('state', '')} | books only on YES.")


def run(text, barge="", consent=True, confirm_voice=""):
    if run_pipeline is None:
        return "Pipeline failed to load"
    confirm = confirm_voice.strip() if confirm_voice.strip() else ""
    r = run_pipeline(text or "Book a cardiology checkup tomorrow morning at 9",
                     barge_in=barge or "", auto_consent=consent, confirm_text=confirm)
     backend = {"local-sim": "typed try-out (text input, no audio file)",
               "assemblyai": "real AssemblyAI"}.get(r['backend'], r['backend'])
    L = [f"State: {r.get('state', '')}",
         f"Listen backend: {backend}",
         f"Patient said: {r['transcript']}",
         f"Understood: {r['entities']} (confidence {r['confidence']})"]
    st_ = r.get("structured") or {}
    try:
        for f, v, s in structured_to_fields(r.get("transcript", ""), r.get("entities", {}), st_):
            L.append(f"Entity[{f}@{s}]: {v}")
    except Exception:
        pass
    if r.get("readback"):
        L.append(f"Assistant readback: {r['readback']}")
    L.append(en_summary(r))
    L += [f"[{e.split(':')[0]}] {e}" for e in r["events"]]
    if r.get("reply"):
        L.append(f"Assistant reply: {r['reply']}")
    L.append("Stage latency (ms): " + " | ".join(f"{k}={v}" for k, v in r["stages_ms"].items())
             + f" | TOTAL={r['total_ms']}")
    if r.get("booking"):
        L.append(f"Booked: {r['booking']}")
    if r.get("needs_confirm"):
        L.append("Say YES to book, NO to change.")
    if r.get("escalated"):
        L.append("Handed off to the nurse hotline.")
    return "\n".join(L)


if __name__ == "__main__":
    if gr is None:
        print("gradio not installed — pip install -r requirements.txt")
        print(run("Book a cardiology checkup tomorrow morning at 9"))
    else:
        demo = gr.Interface(
            fn=run,
            inputs=[gr.Textbox(value="Book a cardiology checkup tomorrow morning at 9", label="Patient says (English)"),
                    gr.Textbox(value="", label="Barge-in (interrupt mid-turn)"),
                    gr.Checkbox(value=True, label="Patient consents to book (unticked = never books)"),
                    gr.Textbox(value="", label="Voice confirm (YES to book, NO to cancel, empty = ask first)")],
            outputs=gr.Textbox(label="assistant reply + measured latency"),
            title="VoiceCare — voice clinic booking (AssemblyAI + Gemini) [secondary demo]",
            description="MAIN demo: Streamlit app_streamlit.py. Same core. Books ONLY on YES. Add ASSEMBLYAI_API_KEY + GEMINI_API_KEY via Secrets for full voice.",
        )
        demo.launch(server_name="0.0.0.0", server_port=7860)
