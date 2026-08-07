# Predict — Approve before the outage (TT&C / Decide)

**What it is:** The predictive part of the demo. Early symptoms appear; the LSTM estimates **time left** to the service limit; you Approve backup **before** breach.

**Keywords:** Q1, LSTM, TTI, eta_minutes, seed-preemption, Decide, Approve, red gate, 25 ms, 120 s, preemption, predictive

## Plain English (jury)
- **Naming the fault** (rain / CPU / BGP…) from live metrics = diagnosis.
- **Forecasting minutes to SLA** from the climb = prediction.
- Copilot explains in English; it must **not** block Approve.

## Simple rules
| Idea | Number |
| --- | --- |
| Critical timing limit (TT&C latency) | 25 ms |
| Act when time-to-impact is short | about ≤ 2 minutes (120 s) |
| Typical backup path | eth0 |
| Who must click | Human (Approve) |

## What to do on Decide
1. Read: what class, how confident, how many minutes left.
2. If time is short and the path is still degrading: **Approve backup**.
3. Read Copilot after (or while) — nice to have, not required to steer.
4. After the path is healthy again, clear the override.

## Do not
- Call the whole system “reactive” just because symptoms exist.
- Symptoms start the story; **time-to-impact + Approve before breach** is the predictive story.
- Never wait for the RAG/LLM answer before Approving.
