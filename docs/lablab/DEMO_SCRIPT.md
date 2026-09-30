# DEMO SCRIPT — VoiceCare specialty-first flow (judge self-runs in 2 minutes)

> Live timeline 0:00-2:00 — judges open and run with no setup:
> 0:00-0:30 open demo URL + press RUN FULL DEMO → 0:30-1:00 agent shows CONFIRMATION → 1:00-2:00 auto YES → BOOKED + .ics + latency ms.
> Dialogue is English-only. Manual alternative below (same result as the one-click button):
> `Book a cardiology checkup tomorrow morning at 9`.
> Correction `No, 10 o'clock instead`; confirm `yes` (strict YES, transcript-proof); `uhm hmm ...` = unclear → escalate.

> Reset before each take (typed terminal mode self-books, so every take writes a slot):
> ```bash
> echo "[]" > src/bookings.json
> ```

One-command terminal take (typed, no key needed):
```bash
./video/run_demo.sh
# reset once -> realtime STT (no booking) -> YES books slot A
# -> barge-in slot B -> escalation (no booking) -> agent API -> TAM -> DONE
# Then switch to Streamlit and press RUN FULL DEMO (one click).
```

Golden path terminal (manual, same as the script above):
```bash
echo "[]" > src/bookings.json
python3 src/main.py "Book a cardiology checkup tomorrow morning at 9"
# -> booked 09:00 Cardiology/Dr. Nguyen + readback (terminal self-books; browser asks YES)

echo "[]" > src/bookings.json
python3 src/main.py "Book a checkup" --barge-in="cardiology tomorrow morning 9am instead"
# -> barge-in: newer utterance wins -> booked 9h

echo "[]" > src/bookings.json
python3 src/main.py "Book cardiology tomorrow morning at 9, no, 10 instead." --confirm="yes"
# -> booking {cardiology, tomorrow morning, 10h} + .ics (real consent path: strict YES writes)
```

Missing specialty (asks first, never guesses):
```bash
python3 src/main.py "Book a checkup tomorrow morning at 9" --confirm=""
# -> UNDERSTANDING: "Which specialty would you like? ..." (no booking)
```

Escalation (never guesses):
```bash
python3 src/main.py "uhm hmm ..."
# -> hands off to the nurse hotline
```

Voice Agent API (needs key for live voice):
```bash
python3 src/agent_api.py --print-session   # view inline en session, offline OK
python3 src/agent_api.py --src sample_en.wav  # one-time token + WS + TTS + tools
```

Browser (Streamlit live, ONE button):
1. Open demo URL, press `▶ RUN FULL DEMO`
   -> Turn 1 `general checkup day after tomorrow` (asks for time)
   -> Turn 2 `11 o'clock` (CONFIRMATION card: Specialty/Doctor/Date/Time/Available)
   -> Turn 3 auto YES → ✓ APPOINTMENT BOOKED + download .ics
2. Manual alternative: type `Book a cardiology checkup tomorrow morning` → Listen,
   type `9 o'clock` → CONFIRMATION card, press `YES, BOOK IT`.
3. Open Technical expander for judges: AssemblyAI + Gemini + latency.
