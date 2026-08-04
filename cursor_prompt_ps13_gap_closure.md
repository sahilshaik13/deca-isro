# Cursor task: close PS13-required gaps (priority order)

> **STATUS (2026-08-01): DONE.** All five gaps closed and accepted under
> `data/deca/predictive/ps13_1to1_acceptance/SUMMARY.json`. Kept as historical
> prompt — do not re-open work from this file. Live truth:
> [`docs/DECA_SDWAN_PROCESS_FLOW.md`](docs/DECA_SDWAN_PROCESS_FLOW.md).

## Context (historical)
`docs/DECA_SDWAN_PROCESS_FLOW.md` §0 disclosed five gaps against PS13 Objectives 2 and 4.
Original task scoped four as in-scope; rekey was later closed as Phase 7 of the same gap-closure campaign (exporter + `rekey_anomaly.py` → Prom).

Read `docs/DECA_SDWAN_PROCESS_FLOW.md` for current pipeline context.

---

## Task 1 (do first) — Path asymmetry signal
**PS13 ask:** Objective 2 — "Routing instability detection... path asymmetry."
**Current state:** PE probes already measure GRE and eth0 RTT separately at ~1Hz (`sdwan_path_*` metrics in Prometheus). The differential exists in the data but isn't computed or surfaced as a named signal — GRE-vs-eth0 comparison is diagnostic only.
**Do:**
1. In the telemetry/preprocess stage (wherever `PREP` / 1Hz-align-and-EMA runs), add a derived feature: `path_asymmetry = abs(gre_rtt - eth0_rtt)` (and/or a directional ratio if one-way loss data is available) per PE pair, per sample window.
2. Feed this feature into the existing Q2 XGBoost input vector alongside the current latency/CPU/BGP features — retrain isn't required to start, but confirm the feature is at least present in inference so it can influence severity classification once labeled data supports it.
3. Surface `path_asymmetry` as its own field on the Decide card payload (not folded silently into the general Q2 line) — this is what lets you show it as a live signal, not just claim it exists.
4. Do not build a separate ML "asymmetry detector" model — a computed feature + threshold flag is sufficient to satisfy this objective honestly; don't overbuild.

## Task 2 — Multi-candidate playbook
**PS13 ask:** Objective 4 — "Automated playbook suggestion and action sequencing."
**Current state:** Every severity tier maps to exactly one fixed action (steer PE1 → eth0 backup via `force_path`). You already have 6 pinpoint SOPs in the RAG corpus (`rain_fade`, `cpu_exhaustion`, `ttc_sla_preempt`, `chaos_compound`, `bgp_instability`, `prom_metric_glossary`) that already describe alternate remediations in text.
**Do:**
1. Find where `payload.recommended_actions` is built (surfaces as "Playbook (MVP)" on Decide) and change it from a single hardcoded action to a small ranked list per severity class — e.g. for a BGP flap (3A/3B): [1] dampen BGP session, [2] steer to eth0, [3] clear inject if simulated. Source the action text/ordering from the existing SOPs so you're not inventing new remediation logic, just exposing what's already documented.
2. Keep the actual actuation (`force_path` on PE1) as the only thing HITL Approve executes for now — the other ranked candidates can be informational-only in this pass (shown on the card, not wired to the controller) if there isn't time to build multi-action actuation. That still satisfies "playbook suggestion," just not "action sequencing" — note that distinction back to me if you have to cut there.
3. If time allows, wire at least a second real action (e.g. BGP soft-clear via FRR, since you already have `inject_bgp_flap.sh` as a precedent for scripting FRR commands) so Approve isn't always the same one steer command regardless of severity class.

## Task 3 — Packet-loss progression model
**PS13 ask:** Objective 2 — "Tunnel health degradation scoring — packet loss progression, jitter trends, rekey anomalies." (loss + jitter parts only for this task)
**Current state:** Loss is already a captured feature in the same protocol corpus (`data/deca/predictive/protocol/20260729T104715Z/`) that trains Q1's latency LSTM. It's used as a static SLA threshold, not forecast.
**Do:**
1. Reuse the Q1 LSTM training pipeline (`train_q1_lstm`) — same preprocessing, same windowing — but retarget the label to time-to-loss-SLA-breach (Payload ≤2.0%, TT&C ≤0.1%) instead of time-to-latency-breach. Check first whether a second full model is worth it vs. adding loss as an additional output head on the existing Q1 LSTM (multi-task output) — the latter is cheaper and keeps one model to maintain.
2. Add jitter progression the same way if the corpus has clean jitter windows; if not, note that as a follow-up rather than blocking on it.
3. Wire the new ETA (loss) into the same red-gate logic pattern as the existing 120s ETA gate, and surface it on the Decide card as a second ETA field (don't overwrite the existing latency ETA — they're different failure modes).
4. Do not claim this is done until it's actually trained and evaluated against held-out chaos data the same way Q1 was — run `eval_chaos` against it before it goes in the docs as verified.

## Task 4 — Lightweight topology correlation
**PS13 ask:** Objective 4 — "Continuous topology awareness and dynamic graph-based event correlation."
**Current state:** Topology is small and static (PE1, PE2, CORE, two CE sites) but there's no graph structure anywhere in the live path — Prom → preprocess → LSTM/XGB → gate → alert is linear per-metric, with no notion of "what else is downstream of this failure."
**Do:**
1. Build a minimal static topology graph (a plain adjacency structure is fine — NetworkX if convenient, but don't over-engineer given only 5 nodes) encoding: Branch CE → PE1 → CORE → PE2 → {DC CE, Hub CE}, plus the eth0 backup edge.
2. When a Decide alert fires on a given node/link, compute which downstream sites/services are affected (blast radius) using that graph, and add an `affected_scope` list to the Decide payload beyond the single `host` field that's there now.
3. Keep this genuinely "continuous topology awareness" — i.e., don't hardcode the blast-radius answer per alert type, compute it from the graph structure so it would still work if the topology changes.
4. This does not need to detect multi-fault correlation across separate simultaneous alerts (that's a bigger feature) — computing blast radius for a single alert against a known topology is enough to honestly claim "topology-aware," not full graph anomaly detection.

---

## Explicitly out of scope for this task
**Do not attempt:** IPsec rekey anomaly detection. No rekey telemetry/labeled corpus exists yet; building a detector without that data would be guesswork. Leave it disclosed as Phase-2 in the docs. If you want to lay groundwork, the one acceptable action is confirming whether strongSwan/charon rekey and SA renegotiation events are already flowing into the existing syslog ingest — report back on that, but don't build detection logic on top of it this pass.

**Do not attempt:** Dual-P CORE netns cutover, Prophet/graph-anomaly models. Both are correctly deprioritized — not required by PS13's literal text (single "P" role suffices; Prophet is a suggested-tool option, not a mandate).

## Acceptance criteria — run these and report back
```bash
# Path asymmetry
curl -s 'http://127.0.0.1:9090/api/v1/query?query=path_asymmetry' | jq .
# confirm it's non-empty and changes under a rain-fade or asymmetric-loss injection

# Playbook
# trigger a 3A/3B (BGP flap) alert and confirm the Decide card shows >1 ranked action,
# not just the single eth0-steer action

# Loss ETA
.venv-predictive/bin/python -m predictive.eval_chaos --model <loss-eta-model-path>
# confirm precision/recall/lead-time reported the same way Q1 latency was evaluated

# Topology / blast radius
# trigger an alert on PE1 and confirm the Decide payload's affected_scope lists
# the correct downstream sites (DC CE, Hub CE) rather than just "host: PE1"
```

## Constraints (historical)
- Don't regress anything currently verified working: LDP/MPLS-on-GRE, SR-TE/pathd, orchestrator API, Q1/Q2/Q3.
- Dual-P / Prophet / generic graph-anomaly ML remain **not claimed**.
- Rekey anomaly was later closed (see STATUS banner at top) — ignore the older "don't build rekey" line.
- Acceptance artifacts: `data/deca/predictive/ps13_1to1_acceptance/SUMMARY.json`.
