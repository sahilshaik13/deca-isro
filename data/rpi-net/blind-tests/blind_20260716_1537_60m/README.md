# Blind live test — `blind_20260716_1537_60m`

Archived run of the DECA blind live-network test on the CE-PE-CE Pi lab.

**Full write-up:** [`docs/results/BLIND_TEST_20260716_1537_60m.md`](../../../docs/results/BLIND_TEST_20260716_1537_60m.md)

## Artifacts

| File | Description |
| --- | --- |
| `ground_truth.sealed.jsonl` | What the network actually did (sealed at injection time) |
| `declarations.jsonl` | Every model state transition (class, ETA, severity, tier) |
| `scorecard.json` | Graded reconciliation (detection, lead, ETA, false alarms) |
| `run_meta.json` | Chaos seed and run parameters |
| `model_config.json` | Promoted classifier + loom config snapshot at test time |
| `fault_injection_log.csv` | Campaign-compatible injection log |
| `bgp_update_samples.csv` | Stamped BGP update-rate telemetry (lab Prom has no FRR counter) |
| `chaos.log` / `chaos_run.log` | Blind chaos scheduler timeline |
| `operator_feed.log` | Live NOC terminal feed (full run) |

## Headline result

4/4 circumstances **detected**, 2/4 first-class / **4/4 eventual-class**, 0 missed.
Near-miss FA 1/1 · 49 spurious. Full tables in the write-up; see also
[`docs/results/BLIND_TEST_AGGREGATE_20260716.md`](../../../docs/results/BLIND_TEST_AGGREGATE_20260716.md).
