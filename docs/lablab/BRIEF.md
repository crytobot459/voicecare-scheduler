# BRIEF — AssemblyAI - Voice Agent Hackathon
- Link: https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon
- Prizes: $5000 (total $10000)
- EV: $60.0/day | Score A85
- Dates: 2026-09-01 → 2026-09-30 (DEADLINE: 22:00 VN 30/9 (15:00 UTC) — month-long 1-30/9, enroll stays open, joining mid-way still works)
- Format: online only | Stack: voice | Status: watch/LIVE
- Real repo: https://github.com/crytobot459/voicecare-scheduler (public, spread-out commits 29/9)
- Demo URL: https://voicecare-scheduler-lmzkozkdf4rssh4w6vz8p6.streamlit.app/ (live, verified ?embed=true 200; if root 303 login then open embed or set Public)

## 🎯 Target track (snipe low-competition): Accessibility/bonus track — voice agent latency numbers + realtime entity extractor (fewer rivals than generic voice — verify the Tracks section)

## Tracks / themes
- Main [inferred from slug]: Voice agent on AssemblyAI STT (open the event page and read Tracks + Accessibility/bonus prizes)
- [ ] Open https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon and read Tracks/Prizes (static HTML lacks them, needs a 5-minute manual read)

## Judging criteria
- Default lablab 4 dimensions (static page has no detailed criteria — read the Judging/Evaluation section by hand):
- Presentation / Business Value / Technology / Originality (see the 4-dimension frame below)
- Rubric verbatim (event override): "AssemblyAI load-bearing + latency ms + interruption handling + real tool-use + consent/recovery + generic 4 dimensions Presentation/Business/Technology/Originality"

## 5-minute manual read checklist (static HTML lacks full tracks)
- [ ] Open https://lablab.ai/ai-hackathons/assemblyai-voice-agent-hackathon Tracks/Prizes section -> fill `track_target` in config/events.yaml
- [ ] Copy the Judging/Evaluation rubric -> fill `judging_rubric_quote` in config
- [ ] Confirm the deadline in standard time (DB stores date only) -> `deadline_vn`

## 3 idea directions (pick 1 — then load the locking skill)
1. Latency proof: an agent with >300ms delay loses — measure ms, live translate/command demo, with a judge-replayable method.
2. Realtime entity extractor: listen to a call (deal/appointment) and fill structured fields as words drop — the way Dealty won.
3. Accessibility agent: voice shopping/support for elderly or people with pronunciation difficulties — scores Accessibility directly.

## Judging criteria (the 4 dimensions judges look at)
1. Presentation — clear 4-5 minute video (problem 30s, live demo, business case).
2. Business Value — specific user + TAM + 1 revenue model + why AI is needed.
3. Technology — public demo URL that opens, spread-out repo commits, load-bearing AI.
4. Originality — a new angle only possible with this generation of models.

## Idea test (must pass all 4 before building)
- [ ] Core loop runnable in the first 24h?
- [ ] User is a specific niche (not 'everyone')?
- [ ] Demo ≤3 screens, judge gets it in 30s?
- [ ] Sponsor API cannot be removed (removing it kills the demo)?

> Lock the concept: load skill `lablab-idea-forge` in opencode with this BRIEF.
>
> ## Next steps (today)
> 1. `python3 agent/scaffold.py assemblyai-voice-agent-hackathon` — generate skeleton + demo script
> 2. Enroll on lablab.ai (by hand), join the event Discord
> 3. `python3 -c "from agent.store import set_status; set_status('assemblyai-voice-agent-hackathon','building')"`
> 4. Code 1 measurable MVP feature → shoot a 2-minute demo
> 5. `python3 agent/submit.py assemblyai-voice-agent-hackathon --check` before manual Submit
>
> _Safety rules: agent only codes + scans public. Enroll/Submit by hand in the browser._

_Note: English-only. All voice inputs are English (e.g. `cardiology/tomorrow morning/9 o'clock`)._
