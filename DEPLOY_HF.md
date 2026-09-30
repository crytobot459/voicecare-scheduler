# Deploy HF Spaces — backup (main demo is Streamlit)

> Judge-facing demo: Streamlit `app_streamlit.py` (see DEPLOY_STREAMLIT.md).
> This file is only the HF Spaces Gradio `app.py` backup for when Streamlit sleeps.

1. Create a Space: https://huggingface.co/new-space -> SDK Gradio, Public.
2. Upload: `app.py`, `src/main.py`, `src/agent_api.py`, `src/realtime.py`, plus `requirements-gradio.txt` renamed to `requirements.txt` (the root `requirements.txt` is the slim Streamlit stack — do NOT use it for Gradio).
3. Wait for build -> verify incognito: type `Book a cardiology checkup tomorrow morning` -> asked for time -> `9 o'clock` -> CONFIRMATION -> `Booked`.
4. Shoot the video opening the real URL (never localhost).

Check: `python3 agent/submit.py assemblyai-voice-agent-hackathon --check --live-check <hf-url>`
