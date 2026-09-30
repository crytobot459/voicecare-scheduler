# CONCEPT_SCORED — assemblyai-voice-agent-hackathon (stack voice)
Weights: Presentation 20 + Business Value 20 + Technology 40 + Originality 20 = 100

| # | Idea | Pres | Biz | Tech | Orig | Total/10 | ≥7 |
|---|---|---|---|---|---|---|---|
| 1 | Latency proof: an agent with >300ms delay loses — measure ms, live translate/command demo, with a judge-replayable method | 7 | 4 | 9 | 7 | **7.2** | 3/4 |
| 3 | Accessibility agent: voice shopping/support for elderly or people with speech difficulties | 5 | 7 | 7 | 7 | **6.6** | 3/4 |
| 2 | Realtime entity extractor: listen to a call (deal/appointment) and fill structured fields as words drop — the way Dealty won | 4 | 7 | 7 | 7 | **6.4** | 3/4 |

## Winner: idea 1 — 7.2/10, wins 3/4 dimensions (needs ≥3 dimensions ≥7)
> Latency proof: an agent with >300ms delay loses — measure ms, live translate/command demo, with a judge-replayable method.

### Why it won (matched keywords)
- Presentation 7/10: base 4 (demoable in 24h); +2 measured/before-after numbers; +1 live
- Business Value 4/10: base 4 (1 real job)
- Technology 9/10: base 3; +4 sponsor hits: latency,live; +2 runnable proof
- Originality 7/10: base 4; +3 hard-to-copy angle

### Ablation test (removing the sponsor must kill it)
- [ ] Remove the sponsor SDK/key → does the demo die? (survives = Tech/Orig deduction)
- [ ] Core loop in 24h? Niche? ≤3 screens?

> Lock in by hand: copy the winner into `build/assemblyai-voice-agent-hackathon/CONCEPT.md`, then `python3 agent/scaffold.py assemblyai-voice-agent-hackathon --hf`
> Gap log: `work/gaps/assemblyai-voice-agent-hackathon.md` | Rubric: `config/rubrics/assemblyai-voice-agent-hackathon.yaml`

_Note: English-only. All voice inputs are English (e.g. `cardiology/tomorrow morning/9 o'clock`)._
