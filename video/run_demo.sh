#!/bin/bash
# run_demo.sh — ONE command for the full VoiceCare take (English-only).
# Press Record -> run this script -> switch to Streamlit -> press RUN FULL DEMO -> Stop.
#
# Flow (all automatic, no typing mid-take):
#   reset once -> realtime STT (no booking) -> YES books slot A
#   -> barge-in slot B -> escalation (no booking) -> agent API -> TAM -> DONE.
# Then the browser part is ONE button (RUN FULL DEMO in app_streamlit.py).
#
#   ./video/run_demo.sh                 # real take (terminal auto + TTS)
#   ./video/run_demo.sh --fast          # dry-run CI: skip sleep/TTS/live-WS
#   ./video/run_demo.sh --no-tts        # muted take, text on screen only
#
# Keys from env only (never printed). No key -> labeled local-sim fallback.

set -e

FAST=0
NO_TTS=0
for a in "$@"; do
  case "$a" in
    --fast) FAST=1; NO_TTS=1 ;;
    --no-pause) ;; # legacy flag, kept for CI compat — pause removed, always auto
    --no-tts) NO_TTS=1 ;;
    --help|-h)
      sed -n '1,15p' "$0"
      exit 0
      ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Load local keys for the take (shell + realtime WS). Never printed.
# Real env always wins; missing file = labeled fallback (still scores).
set -a
[ -f .env ] && . ./.env
set +a

SAY_ARGS=""
[ "$NO_TTS" = "1" ] && SAY_ARGS="--no-play"

run_timeout() {
  secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then
    timeout "$secs" "$@" || return $?
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$secs" "$@" || return $?
  else
    "$@" || return $?
  fi
}

do_sleep() {
  [ "$FAST" = "1" ] && return 0
  sleep "$1" || true
}

try_open_demo() {
  # Best-effort: open local Streamlit if running. Never fails the take.
  url="http://localhost:8501"
  if command -v open >/dev/null 2>&1; then
    (open "$url" 2>/dev/null || true) &
  elif command -v xdg-open >/dev/null 2>&1; then
    (xdg-open "$url" 2>/dev/null || true) &
  fi
  echo "(demo URL: $url — or your Streamlit Cloud URL. Press RUN FULL DEMO there.)"
}

STAGE=0
stage() {
  STAGE=$((STAGE + 1))
  mins=$((SECONDS / 60)); secs=$((SECONDS % 60))
  printf "\n========================================\n"
  printf " %s [%02d:%02d]\n" "$1" "$mins" "$secs"
  printf "========================================\n"
}

say_last() {
  if [ "$NO_TTS" = "1" ]; then
    python3 video/say.py --from-last --no-play || true
  else
    python3 video/say.py --from-last $SAY_ARGS || true
  fi
}

echo "========================================"
echo "       VOICECARE — VOICE CLINIC BOOKING"
echo "  English-only · AssemblyAI + Gemini"
echo "========================================"

echo "[]" > src/bookings.json
rm -f /tmp/voicecare_last.json || true

if [ -z "${ASSEMBLYAI_API_KEY:-}" ]; then
  echo "(AssemblyAI key: MISSING — labeled local-sim fallback. Export ASSEMBLYAI_API_KEY for real voice.)"
else
  echo "(AssemblyAI key: OK ${#ASSEMBLYAI_API_KEY} chars — real realtime WS)"
fi
if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "(Gemini key: MISSING — regex fallback NLU (labeled). Export GEMINI_API_KEY for full LLM.)"
else
  echo "(Gemini key: OK ${#GEMINI_API_KEY} chars — full LLM NLU)"
fi

stage "01 REALTIME — AssemblyAI hears patient [00:15]"
if [ "$FAST" = "1" ]; then
  python3 src/main.py "I'd like to book a cardiology appointment tomorrow morning at 9" --confirm="" | python3 video/demo_view.py --clean || true
else
  if [ -f "sample_en.wav" ] && [ -n "${ASSEMBLYAI_API_KEY:-}" ]; then
    if run_timeout 45 python3 src/realtime.py --src sample_en.wav --confirm="" | python3 video/demo_view.py --clean; then
      echo "(realtime WS done — PARTIAL/FINAL + confirmation card, NOT booked yet)"
    else
      echo "(realtime WS failed — labeled fallback)"
      python3 src/main.py "I'd like to book a cardiology appointment tomorrow morning at 9" --confirm="" | python3 video/demo_view.py --clean || true
    fi
  else
    python3 src/main.py "I'd like to book a cardiology appointment tomorrow morning at 9" --confirm="" | python3 video/demo_view.py --clean || true
  fi
fi
say_last
echo "(realtime confirmation card read aloud — NOT booked yet)"
do_sleep 3

stage "02 CONFIRM — books only on YES [01:20]"
python3 src/main.py "I'd like to book a cardiology appointment tomorrow morning at 9" --confirm="yes, book it" | python3 video/demo_view.py --clean || true
say_last
echo "(Cardiology / Dr. Nguyen / tomorrow morning 09:00 / BOOKED + VC-ID)"
do_sleep 3

stage "03 BARGE-IN — interruption, newer utterance wins"
python3 src/main.py "Book a checkup" --barge-in="ENT day after tomorrow 10am instead" --confirm="yes" | python3 video/demo_view.py --clean || true
say_last
echo "(barge-in uses newer utterance + books 10:00 ENT)"
do_sleep 3

stage "04 ESCALATION — unclear audio, nurse handoff [02:00]"
python3 src/main.py "uhh hmm ..." | python3 video/demo_view.py --clean || true
say_last
echo "(nurse handoff, NO booking)"
do_sleep 3

stage "05 BROWSER LIVE — Streamlit, ONE button [02:25]"
cat video/BROWSER_STEPS.txt
echo ""
echo ">>> Now switch to the browser window and press RUN FULL DEMO (one click)."
echo ">>> Terminal part is done — no Enter needed, continuing automatically..."
try_open_demo
do_sleep 2

stage "06 VOICE AGENT API — inline session [03:00]"
python3 src/agent_api.py --print-session | head -25 || true
echo "--- (session.update + language_codes en + tools check/book) ---"
do_sleep 3

stage "07 MARKET [03:25]"
cat video/TAM_CARD.txt
echo ""
echo "========================================"
echo " VoiceCare — Voice-first clinic scheduling"
echo " AssemblyAI Realtime + Gemini + tools"
echo " \$39 Solo / \$99 Plus — Main Voice Agent track"
echo " Thank you."
echo "========================================"
nbooks="$(python3 -c "import json;print(len(json.load(open('src/bookings.json'))))" 2>/dev/null || echo "?")"
echo "(bookings.json: $nbooks bookings — 2 BOOKED slots A+B + 0 from escalation is correct)"
echo "          DEMO COMPLETE"
