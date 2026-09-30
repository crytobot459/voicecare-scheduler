# SUBMIT DRAFT — copy-paste to lablab.ai

## Title (≤50 chars — form limit)
VoiceCare Scheduler — voice clinic booking

## Short desc (≤255 chars)
Voice agent for elderly patients: speak to book clinic appointments. AssemblyAI Voice Agent API (one-time token + live voice WS, vendor TTS) + STT fallback, consent-first booking, barge-in, per-stage latency.

## Long desc (≥100 words)
Elderly patients often depend on family to book clinic visits through apps with tiny text. One confusing screen and they give up — or travel to the clinic just to ask.

VoiceCare Scheduler lets them speak instead, on the AssemblyAI Voice Agent API (agents.assemblyai.com: short-lived token minted server-side, live browser voice WS, English inline session with keyterms + barge-in turn-taking, vendor TTS voice, 2 tools check_availability/book called as tool.call->tool.result): say the need, the agent transcribes, extracts day/time entities, asks for confirmation aloud, then books only after the patient says YES (strict, transcript-proof). STT batch/WS fallback (Universal-3-5-pro, en, diarization) keeps the demo runnable. If the user interrupts mid-flow, the agent stops, listens, and continues with the better-understood sentence. If confidence is low, it never guesses — it escalates to a human hotline.

Every run prints per-stage latency (reproducible locally). Measured live: WS handshake ~1.0s, PARTIAL ~1.2s, FINAL ~3.9s (Speaker A, `sample_en.wav`); batch ~8.5s with entities. Accessibility-first: slow clear TTS, large-text cards and autoplay replay serve elderly users, while barge-in turn-taking and never-guess escalation keep patients with unclear pronunciation safe instead of misbooked. Users: clinics serving elderly patients who don't use apps. Market: ~12M over-60 VN (UNFPA 2023) + ~5k private clinics (MOH est.); SAM 500 x $39/mo = $234k ARR yr1. Revenue: per-clinic SaaS $39/$99 per month, cheaper than a $250 phone receptionist. Track: Main Voice Agent (full operating loop: token + live WS + TTS + 2 tools + barge-in + YES-gated consent + escalation + measured latency; doubles as Accessibility entry for elderly/low-clarity speech). Live demo + video with EN overlays showing the full loop.

## Tags
technology: assemblyai, assemblyai-voice-agent-api, python, streamlit | category: voice, accessibility, healthcare

## Links (ENROLLED 28/9, demo live, repo public 29/9, filming silent + EN overlays)
- Repo PUBLIC: https://github.com/crytobot459/voicecare-scheduler (public, commits spread)
- Demo: https://voicecare-scheduler-lmzkozkdf4rssh4w6vz8p6.streamlit.app/ (Streamlit live; if asleep press Wake; anonymous test: press `RUN FULL DEMO` — or type `Book a cardiology checkup tomorrow morning at 9` → correct with `No, 10 o'clock instead` → `YES, BOOK IT`)
- Video: (silent 4:05 take per video/QUAY_CAM.md + OVERLAYS_EN.srt 8 cues, machine voice from the real pipeline via video/say.py --from-last — up on YouTube unlisted + Not for Kids)
- Slides PDF: deck_voicecare.pdf (10 slides: problem/solution/demo/how-it-works Voice Agent API/market $234k ARR [UNFPA 2023 + MOH est., SAM team estimate]/revenue $39-$99/why-AI-now/team/roadmap/ask Main Voice Agent)
