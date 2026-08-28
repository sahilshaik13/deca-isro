# DECA — NOC Dashboard Frontend Plan

**Approach:** ML output gets routed *into* the panels you already have (topology map, Decide panel). Only one genuinely new panel is needed — the LLM copilot query interface, since that doesn't exist yet. No new panel for ML predictions on their own.

---

## 0. Scope discipline — build only what's real

Map every dashboard element to what's actually trained/wired, not the full PS13 wishlist. Per current model state:

**Built — safe to show on the dashboard:**
- Q1 forecasting (LSTM heads: latency, jitter, loss, utilization) with time-to-impact estimate
- Q2 severity classification (XGBoost) for the six fault families (rain, CPU, BGP flap, loss, util, CE-SLA)
- Offline LLM copilot (Phi-3 + RAG over Chroma) for natural-language explanation
- Orchestrator Approve/Reject steering, SR-TE path control

**Not built — do NOT surface as a live feature (Phase-2, disclose only if asked):**
- Route-flapping *precursor* detection (current model classifies flap severity after the fact, not before)
- Path asymmetry detection
- IPsec rekey anomaly *scoring* (rules/ambient only, no ML)
- Graph-based multi-signal correlation
- Multi-candidate playbook engine (single recommended action only)

Any dashboard copy that implies these exist gets flagged and cut before judging.

---

## 1. Map the three operator questions to existing UI

| Question | Where it lives | What's new |
|---|---|---|
| **Q1** — What fails next, and when? | Topology map (node/link color) + Decide panel header | Feed LSTM time-to-impact into existing node states, not a new widget |
| **Q2** — Why is risk elevated? | Decide panel, expandable "Inspect" section | Feature-trace table (the few signals that drove the call) |
| **Q3** — What should I do? | Decide panel Approve/Reject flow + new Copilot panel | Copilot gives the operator-language recommendation; Decide panel executes it |

---

## 2. Topology map (existing panel — enhance, don't replace)

- Node/link color already reflects health — wire the Q1 forecast into that color *before* a hard threshold breach, not just at breach (this is the "precursor lead time" story, scoped to the fault types the model actually predicts early: congestion/utilization/latency drift, per LSTM heads)
- Hover/click on a node → small popover with plain-language forecast: *"PE1 link trending toward saturation, ~6 min to breach"*
- No separate ML panel competing with the map — the map **is** the Q1 answer surface

---

## 3. Decide panel (existing panel — this becomes the Q2/Q3 surface)

### Layer 1 (default, for anyone)
- Plain-language line per proposal: *"BGP flap detected, 91% confidence, TT&C SLA at risk"*
- Status flip (healthy → detected → steered) using the same Approve/Reject flow already built
- Live-inference indicator tied to the actual POST call (proves it's not scripted)

### Layer 2 ("Inspect" toggle, collapsed by default — for technical judges)
- Model identity (checkpoint name, e.g. `d2_e100_l6_mcw3`)
- Feature-to-prediction trace: the 3-4 input signals (e.g. `bgp_updates/sec`, jitter, loss) that fed this specific call
- Offline benchmark numbers next to the live confidence (holdout / chaos_final / GNS3 transfer) so an engineer can sanity-check consistency
- Ground-truth vs detection clock: injection timestamp → first-correct-detection timestamp
- Raw backend trace log — demoted here, not on the main screen

### Genuineness mechanics (carried into this panel, not separate UI)
- Let the judge pick which fault to inject from the existing Simple Faults panel
- Blind trial scoreboard (small strip at the top of Decide): `Trials: 5 | Correct: 4/5 | Avg lead time: 3.2s` — show misses too

---

## 4. Copilot panel (new — this is the one genuinely missing piece)

Objective 3 requires a natural-language query interface; the current dump has no chat surface, so this is real net-new UI, kept minimal:

- Simple chat/query box, docked or slide-out, not a full-screen takeover
- Structured response format per query, matching the copilot's actual RAG output:
  - Predicted issue
  - Confidence score
  - Root-cause hypothesis (from retrieved runbook/incident context)
  - Affected scope
  - Recommended action
- Pull answers only from local RAG context (topology, runbooks, past incidents) — no fabricated confidence if retrieval comes back empty; say so explicitly
- Link each copilot answer back to the Decide panel proposal it's explaining, rather than living in isolation

---

## 5. Telemetry matrix (existing panel — demote, don't remove)

- Keep as background/context strip, not a competing focal point
- It supports the Decide panel's feature trace (Layer 2) — don't duplicate the same numbers in two places

---

## 6. Build priority

1. Wire Q1 forecast into topology map node states (reuses existing map, highest judge-visible impact)
2. Decide panel Layer 1 event card + live-inference indicator
3. Decide panel Layer 2 Inspect toggle (feature trace, benchmarks, ground-truth clock)
4. Copilot chat panel (new UI, structured response format)
5. Blind trial scoreboard strip
6. Demote raw backend trace + telemetry matrix to supporting/collapsed roles
