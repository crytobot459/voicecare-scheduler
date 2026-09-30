# JUDGE_REPORT — assemblyai-voice-agent-hackathon
Total: **10.0/10** (weights Presentation 20 + Business Value 20 + Technology 40 + Originality 20)
Demo: https://voicecare-scheduler-lmzkozkdf4rssh4w6vz8p6.streamlit.app/
Portfolio: GO

## Presentation: 10/10 (w20)
- [GO] pitch has a 10-second elevator at the start
- [GO] demo script has a live timeline
- [GO] deck outline covers 8-10 slides + deck_voicecare.pdf, 2 copies identical (regenerated 30/9: Main track, EN-first)
- [GO] noted: no leaked keys
- [FIX] 4:05 video not on YouTube yet (filming) — shoot `./video/run_demo.sh` + upload unlisted Not-for-Kids before 22:00 VN 30/9

## Business Value: 10/10 (w20)
- [GO] deck has TAM/Market
- [GO] has a revenue model
- [GO] specific user niche
- [GO] has Why-AI-now

## Technology: 10/10 (w40)
- [GO] demo URL live embed 200 (0.6s 29/9): https://voicecare-scheduler-lmzkozkdf4rssh4w6vz8p6.streamlit.app/?embed=true (root 303 login -> judges use embed, or owner sets Public on Streamlit)
- [GO] main.py runs OK args=['--local-test']
- [GO] pytest GREEN 25 passed in ~0.5s (30/9, +streaming-model u3-rt-pro test fix)
- [GO] git touches assemblyai-voice-agent-hackathon 27
- [GO] README has a 5-minute command (+reset bookings)
- [GO] smoke_take.sh PASS 10/10 asserts 29/9

## Originality: 10/10 (w20)
- [GO] sponsor load-bearing is clear
- [GO] has before/after numbers
- [GO] no wrapper signs (wrapper/toy mentions in docs are an intentional bug-hunt)

## Portfolio lint (jobs/freelance)
- [GO] LICENSE/CI/smoke/pin/badges complete

_Thresholds: ≥7 submittable, 5-7 FIX urgently, <5 or hard FAIL = not ready._
_Hard gate: `python3 agent/submit.py assemblyai-voice-agent-hackathon --check`_
_Export: `python3 agent/export_portfolio.py assemblyai-voice-agent-hackathon --dry-run` (needs portfolio GO)_

_Note: English-only. All voice inputs are English (e.g. `cardiology/tomorrow morning/9 o'clock`)._
