# DECA Frontend Panels Guide (v2 — live pipeline proof added)

This document maps the DECA NOC Dashboard interface, what each panel does, and — new in this
version — exactly how to wire `TerminalDrawer.tsx` into a live, multi-pane proof view so a
technical jury watches fault → telemetry → inference → copilot happen in raw terminals, not
just a polished GUI.

---

## 1. Top Navigation & Global State

### Header & Global Status Bar (`Header.tsx`)
* **Purpose:** 10,000-foot view of network health and current mission state.
* **Data:** `telemetry.current` (anomaly score, overall time-to-impact), `orch.runId`, orchestrator state.

### Methodology Modal (`MethodologyModal.tsx`)
* **Purpose:** Hidden "Judge's View." Scientific methodology, training sets, offline benchmarks — the proof layer.
* **Data:** Static architectural info + offline ML performance metrics (cite board: 0.884 / 0.815 / 0.655 / 0.992 / 7.1s — keep this the single source of truth, don't let stale numbers drift in here).

### Fleet Strip (`FleetStrip.tsx`)
* **Purpose:** Horizontal ribbon, connection status of all sites/stations.
* **Data:** `orch.fleet.sites` (ping/reachability per edge node).

---

## 2. Left Column: Control & Operations (Network View)

### Fabric & Simulation Controls (`FabricSelect.tsx`, `TrafficButtons.tsx`, `FaultButtons.tsx`, `SimulationControl.tsx`)
* **Purpose:** Operator/judge drives the network live — switch Pi ↔ GNS3, inject traffic, trigger faults.
* **Data:** `POST /api/v1/fabric`, `/api/v1/traffic`, `/api/v1/faults`, `/api/v1/simulation`.
* **This is the trigger for the whole pipeline proof below** — clicking a fault button here is what
  the jury watches cascade through the terminal panes.

### Topology Map (`TopologyMap.tsx`)
* **Purpose:** **PS13-Q1 surface** ("what's likely to fail, when"). LSTM forecasting head lights a
  node red when trending toward SLA breach; hover shows ETA.
* **Data:** `orch.fleet.topology`, `telemetry.stations`, `orch.alerts` (Q1 `eta_minutes`).

### Mission Classes (`MissionClasses.tsx`)
* **Purpose:** Active SLA context (Gold vs Bronze).
* **Data:** `orch.fleet.mission`.

### Telemetry Grid (`TelemetryGrid.tsx`)
* **Purpose:** Raw speeds-and-feeds — throughput, jitter, loss, BGP updates.
* **Data:** `telemetry.current` (raw Prometheus metrics via `fetch_live_network`).

### Inference Evidence Card (`BackendTraceVisualizer.tsx`)
* **Purpose:** "Transfer proof" card — AI decision-making transparency.
  * **Layer 1:** Injection→detection latency (seconds) + blind-trial scoreboard.
  * **Layer 2 (expanded):** Model checkpoint id, offline benchmarks, raw live feature vector JSON.
* **Data:** Delta between `orch.faultStatus` (inject time) and `orch.alerts` (detect time), plus
  raw `telemetry` for the feature vector dump.
* **This card is your Q1 lead-time claim made visual** — the number here should match what the
  terminal pane 2→3 lag shows live (see below). If they disagree, that's a bug to fix before demo day.

---

## 3. Right Column: AI Analysis & Steering (Action View)

### Decide Panel / Alert Rail (`AlertRail.tsx`)
* **Purpose:** **PS13-Q2 surface** (severity / "why"). Shows AI proposal, confidence, Approve/Reject.
* **Data:** `orch.alerts` where `status: 'active'` — `class` (e.g. `bgp_route_flap`), `confidence`, `eta`.
* **Note:** if multiple TTI heads are firing (compound), surface `firing_tti_heads` here too, not
  just the single argmax `class` — this is your honest multi-fault disclosure, don't hide it.

### Copilot Chat Panel (`CopilotTerminal.tsx`)
* **Purpose:** **PS13-Q3 surface** (natural-language mitigation). Active-anomaly-only. Queries
  local Phi-3 via RAG against internal SOPs/runbooks.
* **Data:** `telemetry.copilotResponse` (`root_cause`, `runbook_steps`, `mitigation_checklist`).

---

## 4. Global Overlays

### Terminal Drawer (`TerminalDrawer.tsx`)
* **Purpose (existing):** Bottom-docked raw shell access to edge nodes for manual NOC debugging.
* **Data (existing):** WebSocket to backend terminal manager (`/api/v1/terminals/{id}/ws`).
* **This is the component to extend for the jury demo — see Section 5.** You already built the
  exact primitive needed (a live WS-backed terminal pane); it just needs to default-open with the
  right tabs during a demo run instead of being a single ad-hoc shell.

---

## 5. NEW — Live Pipeline Proof: Multi-Tab TerminalDrawer

**Why this section exists:** a technical jury trusts raw terminal output more than a chart. You
already have the WebSocket terminal primitive (`TerminalDrawer`) — this section turns it into 4-5
labeled tabs, each streaming one stage of the real pipeline, so clicking a fault button in
`FaultButtons.tsx` visibly cascades left-to-right across tabs in real time.

### Tab layout (extend `TerminalDrawer.tsx` to support named tabs, one WS session per tab)

| Tab | Backend command / stream | What the jury sees |
| --- | --- | --- |
| **1. Inject** | The actual `inject_fault.sh --fault <id> --end <n>` invocation triggered by `FaultButtons.tsx`'s `POST /api/v1/faults` | Real command echoed, schedule sidecar ticking (`util_ceil_schedule.jsonl` / `bgp_flap_schedule.jsonl` style output) |
| **2. Telemetry** | `tail -f` on the live Prometheus/Kafka-bridge feed, filtered to the metric(s) relevant to the active fault | Raw metric values climbing in real time — `loss_gre_pct: 0.0 → 4.0 → 8.0...` |
| **3. Inference** | `infer_q1_q2_live` stdout, one line per scored window | `[t+4s] window scored: severity=4A conf=0.87 eta=38s` — this is where Q1/Q2 become visible as a *process*, not just a final card |
| **4. Copilot / RAG** | Copilot backend's retrieval + generation log (not just the final chat bubble — the retrieval step) | `retrieved: runbook_L4_loss.md, topology_ctx.json` **then** the generated response streaming in — proves it's grounded, not hallucinated |
| **5. Decide (optional)** | Arbitration output — `firing_tti_heads`, primary class, playbook selection | Shows the fusion policy (OR-gate, argmax primary, min-ETA) actually running, not just its final output card |

### Implementation notes
* **One WS connection per tab**, each hitting a small backend endpoint that just tails/pipes the
  relevant log or stdout — you don't need new ML code, only a thin streaming wrapper around
  scripts/processes that already exist (`inject_fault.sh`, `infer_q1_q2_live`, the RAG service).
* **Print clean lines, not raw JSON dumps**, in tabs 1–4 — one short human-readable line per event.
  Save the full JSON for `BackendTraceVisualizer`'s Layer 2 (ML-engineer-facing), not the terminal
  tabs (jury-facing).
* **Default-open state for demo mode:** when `SimulationControl.tsx` starts a run, auto-open
  `TerminalDrawer` with all tabs visible and pre-connected, so there's no fumbling — the jury
  should see the drawer already live before the fault button is clicked.
* **The lag between tabs is the actual PS13-SUCCESS proof.** Don't hide or minimize the few
  seconds between tab 1 (inject) and tab 3 (inference firing) — that gap *is* the lead-time claim.
  Let it be visible.
* **Consistency check before demo day:** the injection→detection delta shown in
  `BackendTraceVisualizer` Layer 1 must match what the jury just watched happen live across tabs
  1→3. If your cite board number and the live terminal timing disagree, fix that before anything
  else — it's the single easiest thing for a technical jury to catch.

---

## Cross-reference: which panel answers which PS13 question

| PS13 question | Primary panel | Supporting proof |
| --- | --- | --- |
| Q1 — what fails, when | `TopologyMap.tsx` (red node + ETA) | Terminal tab 3 (Inference) + `BackendTraceVisualizer` Layer 1 |
| Q2 — why elevated | `AlertRail.tsx` (class + confidence) | Terminal tab 3 + tab 5 (Decide) |
| Q3 — what to do | `CopilotTerminal.tsx` (NL response) | Terminal tab 4 (Copilot/RAG) — shows the grounding, not just the answer |
