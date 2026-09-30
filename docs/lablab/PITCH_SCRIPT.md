# PITCH SCRIPT — VoiceCare 4:05 take (single timeline, matches QUAY_CAM+SRT)

> English-only take + EN overlays. One terminal command + one browser button.

## Elevator 0:00-0:10 (first-10-seconds hook)
Overlay: `VoiceCare Scheduler — Speak to book your clinic visit`
Face the camera 10s, silent. One problem line at 0:10.

## 0:10-0:30 Problem
Overlay:
```
Elderly patients give up on tiny-text apps.
One confusing screen — or a trip just to ask.
```
TAM card: 12M over-60 VN, 5k clinics, SAM 500 x $39 = $234k ARR.

## 0:30-0:45 Solution
Overlay: `Say one sentence -> agent confirms aloud -> books only on YES`
Terminal is already running `run_demo.sh`. Browser Streamlit is open.

## 0:45-1:30 Turn 1 (terminal, automatic)
One command runs everything:
```
./video/run_demo.sh
# realtime sample_en.wav (no booking) -> YES books slot A cardiology/tomorrow/09:00
```
Overlay: `Realtime speech (AssemblyAI) + Entity + Confidence`
No typing mid-take. Machine voice comes from `video/say.py --from-last`.

## 1:30-2:10 Turn 2 barge-in (slot B — never reuse slot A on camera)
Automatic inside the same script:
```
# slot B: "Book a checkup" + barge-in "ENT day after tomorrow 10am instead" -> books 10:00 ENT
```
Then press `▶ RUN FULL DEMO` in the browser for slot C `11 o'clock` (see BROWSER_STEPS.txt).
Overlay: `Barge-in — agent stops, uses newer utterance`.

## 2:10-2:40 Escalation
```
python3 src/main.py "uhm hmm ..."
```
Overlay: `Low confidence -> human hotline. Never guesses.`

## 2:40-3:25 Voice Agent API + booking
```
python3 src/agent_api.py --print-session
python3 src/agent_api.py --src sample_en.wav  # needs key; without key use --print-session only
```
Browser already pressed `RUN FULL DEMO` → success + .ics. Overlay:
```
Voice Agent API: token + live WS + TTS + 2 tools
Fallback STT kept runnable — remove AssemblyAI, demo is deaf
```

## 3:25-3:30 TAM card
Overlay:
```
Vietnam 12M over-60 (UNFPA 2023), ~5k clinics
Start 500 clinics — $234k ARR estimate
```

## 3:30-4:05 Ask
Face close. Overlay:
```
VoiceCare Scheduler
Accessible voice-first booking — AssemblyAI Realtime + Entities + TTS
$39 Solo / $99 Plus — cheaper than $250 receptionist
Built for Main Voice Agent track. Thank you.
```
YouTube unlisted + Not for Kids. Every machine-spoken line comes from the real pipeline, no dubbed audio.
