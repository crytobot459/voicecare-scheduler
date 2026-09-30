# Deploy Streamlit Cloud — VoiceCare (free, no card needed)

Streamlit Community Cloud free: public app, deployed from a GitHub repo.

## You do (10 minutes)

1. Create a new public GitHub repo, e.g. `voicecare-scheduler`: https://github.com/new
2. Push the code (run inside the export folder — NEVER push `work/.assemblyai_key`):
   ```bash
   git remote add origin https://github.com/<user>/voicecare-scheduler.git
   git branch -M main && git push -u origin main
   ```
   Required: `app_streamlit.py`, `src/`, `requirements-streamlit.txt` (renamed to `requirements.txt` in the deploy repo).
3. Open https://share.streamlit.io → **New app** → pick repo/branch/`app_streamlit.py` → **Deploy**.
4. (Optional, for real STT) App → Settings → Secrets, add:
   ```toml
   ASSEMBLYAI_API_KEY = "paste-your-key"
   ```
   Without a key it still runs local-sim (backend labeled) — judges can still score the loop.
5. Verify in an incognito window: type a sentence → entities + booking + latency appear.

## After you have the URL
Tell the agent: fill in the config + verify `submit --check --live-check <url>` → shoot the video opening the real URL.
