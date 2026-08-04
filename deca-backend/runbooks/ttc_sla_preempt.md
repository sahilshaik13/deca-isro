# SOP: TT&C SLA Preemption (Q1 Red Gate)

## Description
Multi-head Q1 LSTM predicts time-to-impact (TTI) to TT&C **latency 25 ms**, **loss 2%**, **jitter 5 ms**, and **util ~38 Mbps** ceilings. When any head ETA ≤ **120 s**, the path is hot (or rising), and Q2 severity is in the red set (**1B / 1C / 2B / 3B / 4B / 5B**), the math gate fires `POST /api/v1/simulation/seed-preemption` onto the Orchestrator **Decide** rail. The LLM (Q3) must **not** block this path.

## Gate rules (lab)
| Signal | Threshold |
| --- | --- |
| TT&C latency SLA | ≤ 25 ms on preferred path |
| Loss / jitter / util | ≤ 2% · ≤ 5 ms · ~38 Mbps HTB ceil |
| Red ETA | ≤ 120 s (any head) |
| Yellow ETA | ≤ 180–300 s (advisory; no force) |
| Severity (severity-mode Q2) | Prefer 1B/1C/2B/3B/4B/5B for red |
| Actuation | Approve → `:9280` · optional `bgp_soft_clear` then **`force_path`** on **PE1** |

## Operator Decide rail
1. Read title/summary: ETA, Q2 root-cause / severity, recommended path (`eth0` backup typical), blast-radius IDs.
2. Read **Q3 English NLP** (async) for runbook context — advisory only.
3. **Approve** → budgeted sequence: remediation `bgp_soft_clear` (when BGP class) then `force_path`; audit log records operator.
4. **Reject** → records decision only; autonomous AAR remains safety net if policy allows.

## Diagnostic Steps
1. Confirm Prom still scraping bridge `:9274` and edge `:9273` (no poisoned TSDB / out-of-bounds).
2. Verify alert `generation_path` / payload shows LSTM preemption (not stale sim).
3. Check mission state: `human_override`, `conflict`, active path gre vs eth0.

## Mitigation
1. **Immediate:** Approve preemptive steer before SLA breach.
2. **Safety net:** Controller AAR (`enter_k=3`) may still fail over if HITL is late.
3. **After event:** Clear force only when GRE (or chosen primary) is stable for `exit_k=10` polls.
4. **Never** wait for Phi-3 / RAG before Approve — math gate is authoritative.

## Notes
- Seed body fields: `eta_minutes`, `root_cause`, `severity`, `alert_class`, `path`, `correlated_alert_ids`.
- Q3 enrichment attaches `q3_nlp` asynchronously onto the same alert payload.
