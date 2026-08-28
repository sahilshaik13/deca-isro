# DECA Frontend — Destructive Audit (Keep / Fix / Cut)

Your build is already close to right — most of these panels match the plan. The actual problem is two components are showing the **same UI treatment for signals that don't have the same evidentiary strength**. That's the clutter and the overclaim risk. Fix those two, leave the rest alone.

Rule applied throughout: **only Q1 (LSTM: latency, jitter, loss, utilization) is genuine precursor forecasting. Q2 (XGBoost: BGP flap, CE-SLA) is post-hoc severity classification, not prediction.** Any panel that blurs that line gets fixed below.

---

## KEEP AS-IS

| Component | Why it's fine |
|---|---|
| `Header.tsx` | High-level status only, no per-signal claims — safe |
| `FleetStrip.tsx` | Ping/reachability, factual, not a model claim |
| `FabricSelect.tsx` / `TrafficButtons.tsx` / `FaultButtons.tsx` / `SimulationControl.tsx` | These are your genuineness mechanism — a judge picking the fault from here is your strongest anti-scripted-demo argument. Don't touch. |
| `MissionClasses.tsx` | Static SLA context, low risk, cheap to keep |
| `TerminalDrawer.tsx` | Debug-only overlay, correctly hidden by default |
| `BackendTraceVisualizer.tsx` | Already built exactly right — Layer 1 clean summary + blind scoreboard, Layer 2 checkpoint/benchmarks/raw feature vector. This is the model. Don't rebuild it. |

---

## FIX — TopologyMap.tsx

**Problem:** it currently gives every node the same "LED turns red + ETA on hover" treatment regardless of what kind of alert it is. That's an overclaim for two of your six fault families — BGP flap (L3) and CE-SLA/rekey (L6) are classified *after* the signal appears, not forecast ahead of it. Showing an ETA countdown for those implies precursor lead time you don't have.

**Fix:**
- Nodes flagged by an **L1/L2/L4/L5** signal (rain, CPU, loss, util) → keep the current "trending toward breach, ETA Xm" treatment. This is real.
- Nodes flagged by an **L3/L6** signal (BGP flap, CE-SLA) → different badge: "Anomaly detected" with elapsed time, not a forecast countdown. No ETA field.
- One boolean in the alert payload (`is_precursor: true/false`, derivable from which model produced it — LSTM vs XGBoost) drives which badge renders. No new backend work, just a UI branch.

---

## FIX — AlertRail.tsx (Decide Panel)

**Problem:** same issue as the map. It reads a generic `eta` field off every alert and presents it uniformly, whether the alert came from a genuine forecast or a reactive classification. This is the panel a judge scrutinizes hardest — it's the one place the overclaim will get caught.

**Fix:**
- Split the card header copy by source model:
  - LSTM-sourced (L1/L2/L4/L5): *"Predicted breach in {eta_minutes}"*
  - XGBoost-sourced (L3/L6): *"Detected {class}, {confidence}% confidence — {elapsed}s ago"* — no ETA, no "predicted" language
- Confidence score display stays the same for both — that's honest either way
- Approve/Reject flow stays identical — the fix is copy/label logic, not the action pipeline

---

## FIX — MethodologyModal.tsx

**Problem:** it's currently scoped to "methodology + offline benchmarks." That's necessary but not sufficient — this is your Judge's View, so it's the right place to put the honesty disclosure you already wrote, and right now it's not confirmed to be in there.

**Fix:** add the existing "gaps — do not claim" table verbatim:
- Packet-loss progression ML
- IPsec rekey anomaly detection (scoring)
- Path asymmetry detection
- Graph-based correlation
- Multi-candidate playbook engine

A judge who opens this modal and finds an honest gaps list trusts everything else in the dashboard more, not less.

---

## FIX — CopilotTerminal.tsx

**Problem:** no stated behavior for what happens when RAG retrieval comes back empty or low-relevance. An LLM under those conditions tends to fill the gap with a plausible-sounding but ungrounded answer — the exact failure mode that gets an offline copilot disqualified as "hallucinating."

**Fix:** explicit empty-state string when retrieval confidence/match is below threshold — *"No matching runbook found for this signal"* — instead of letting the LLM answer anyway. This is a one-line guard in the RAG pipeline, not a UI redesign.

---

## FIX — TelemetryGrid.tsx

**Problem:** risk of duplicating the same raw numbers already shown in `BackendTraceVisualizer`'s Layer 2 feature vector, which dilutes which panel is "the evidence."

**Fix:** keep `TelemetryGrid` as ambient/general context only (all metrics, all the time). `BackendTraceVisualizer` stays the only place that shows the *specific slice* of features tied to one inference call. Don't cross-post the same numbers into both with the same framing.

---

## CUT

Nothing needs to be removed outright — the panel set is right-sized already. The fixes above are all label/branch logic on existing components, not new builds and not deletions.

---

## Priority order

1. AlertRail label split (LSTM vs XGBoost) — highest scrutiny surface, cheapest fix
2. TopologyMap badge split (precursor vs detected) — same fix pattern, second-highest visibility
3. MethodologyModal gaps table — confirm it's actually in there
4. CopilotTerminal empty-state guard
5. TelemetryGrid framing check (likely already fine, just verify no duplication)
