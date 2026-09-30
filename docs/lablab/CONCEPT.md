# CONCEPT (locked) — Voice Clinic Scheduler (AssemblyAI track)

**Name:** Speak to book a checkup — a voice agent that books clinic appointments for elderly patients.
**Elevator (10s):** Patient says "book a checkup for tomorrow morning" — the agent listens, reads back for confirmation, books only on YES, and prints per-stage ms.

## Why it wins (real rubric: Technology / Usability / Accessibility / Creativity)
- [x] Core loop in 24h: `python3 src/main.py` runs end-to-end (transcribe→entities→consent→book).
- [x] Niche: elderly patients booking checkups by phone — no app, no tiny text.
- [x] 1 page: Streamlit with one RUN FULL DEMO button → booked slot + latency table.
- [x] Sponsor load-bearing: remove the AssemblyAI STT and the agent is deaf — the demo dies. Free key at assemblyai.com, runs via `ASSEMBLYAI_API_KEY`.

## Numbers to report (printed by the pipeline, measured for real, never made up)
- Per-stage latency (ms): transcribe / understand / act / respond + total.
- Interruption: interrupt mid-turn → agent stops, listens, continues (live demo).
- Recovery: empty STT / tool error → ask again or hand off to a human (escalation).

## Out of scope
- No generic chatbot (fails Use-of-technology).
- No made-up numbers: the local simulator labels itself `backend: local-sim`; real AssemblyAI numbers are filled in after the key arrives.
