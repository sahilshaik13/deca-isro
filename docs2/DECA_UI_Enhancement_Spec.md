# DECA — UI/Presentation Enhancement Spec

**Goal:** Prove the ML model is live and genuinely predicting — readable by a non-technical judge in one glance, verifiable by an ML engineer in one tap.

---

## 1. Problem with current UI

- The backend trace panel is a raw scrolling log (`[MODEL_DETECT] POST /predict (XGBoost) -> [Severity: bgp_route_flap]`) repeated dozens of times per minute.
- It technically proves the model is being called, but nobody can parse it live — it reads as noise, not evidence.
- No visible link between a specific injected fault and a specific model response.

---

## 2. Fix: one card, two layers

Replace the raw log as the primary display. Build a single event card that expands on demand.

### Layer 1 — Default view (for anyone)
- Plain-language state line, e.g.:
  `Fault injected → Model detected BGP flap in 4.1s, 91% confident`
- Status flips: green (healthy) → red (fault detected) → green (steered/recovered)
- Small pulsing "Live inference" dot tied to the real POST call — stops pulsing if backend dies, so it can't be faked
- No numbers dump, no jargon

### Layer 2 — "Inspect" toggle (for ML engineers), collapsed by default
- Model identity: checkpoint name/version (`d2_e100_l6_mcw3`)
- The actual request/response pair for that prediction (real feature vector in, real JSON out, HTTP timestamp)
- Offline benchmark numbers next to live confidence, so it's checkable for consistency:
  - 0.884 holdout
  - 0.815 chaos_final
  - 0.655 GNS3 transfer
- Server-side inference latency (ms)
- "Replay this request" button — re-POSTs the same feature vector, confirms same class returns (proves determinism, not randomness theater)

---

## 3. Genuineness mechanics (kills the "is this scripted" doubt)

1. **Ground-truth vs detection clock** — show fault-injection timestamp next to first-correct-detection timestamp. The variable gap between them is real inference latency; a scripted demo has a fixed delay.
2. **Judge-picked faults** — let the judge/viewer choose which fault to inject from the existing Simple Faults panel. Removes any suspicion of a canned run.
3. **Blind trial scoreboard** — running tally across multiple injections: `Trials: 5 | Correct: 4/5 | Avg detection: 3.2s`. Show misses too — a perfect scoreboard reads as fake, an honest one reads as real.
4. **Feature-to-prediction trace** — show the 3-4 input values (e.g. `bgp_updates/sec`, jitter, loss) that fed the model right before it fired, next to what it returned.

---

## 4. Visual/UX polish

- Collapse the raw backend trace into a "Raw log" toggle inside Layer 2 — keep it for engineers who want to verify further, don't lead with it.
- Use color + iconography for state transitions (healthy/detected/steered) instead of text-only status.
- Animate the confidence flip (baseline confidence → post-fault confidence) rather than static numbers — motion signals "this just happened," not "this is a static mockup."
- Keep Telemetry Matrix (throughput/jitter/loss/BGP updates) as background context, but don't let it compete visually with the main event card — it should support, not distract from, the fault→prediction story.

---

## 5. Build priority

1. Event card (Layer 1) with live status flip — highest visual impact, lowest effort
2. Ground-truth vs detection clock — reuses existing injection timestamps and alert IDs
3. Inspect toggle (Layer 2) — for judges who want technical verification
4. Blind trial scoreboard — best for live, judge-interactive demos
