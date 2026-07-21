# VRF recall campaign — `vrf_recall_20260718_1752`

**Purpose:** After specificity PASS, adversarial blind missed a genuine PE2 `vrf_leakage`. Add **completed** VRF (and light tunnel) reals so retrain can pull VRF recall up **without** another large `precursor_aborted` dump.

**Driver:** [`scripts/deca_vrf_recall_campaign.py`](../../scripts/deca_vrf_recall_campaign.py)  
**Context:** [`../DECA_RESULTS_OVERVIEW.md`](../DECA_RESULTS_OVERVIEW.md) · [`BLIND_TEST_AGGREGATE_20260718.md`](BLIND_TEST_AGGREGATE_20260718.md)

## When / where

| Field | Value |
| --- | --- |
| **Run ID** | `vrf_recall_20260718_1752` |
| **Wall** | Sat **18 Jul 2026** ~17:52 – 20:23 IST |
| **Quotas** | VRF **5/5**, tunnel **2/2** |
| **Artifacts** | [`data/rpi-net/runs/vrf_recall_20260718_1752/`](../../data/rpi-net/runs/vrf_recall_20260718_1752/) |
| **Telemetry** | ~10.9k rows exported at end |

## Validation

WARN expected (no congestion/BGP in this lean campaign). VRF avg duration **6.6 min**, spread **1.8 min** (n=5) — not a collapsed-timestamp pattern.

## Downstream (same evening)

| Step | Result |
| --- | --- |
| `rebuild_unified --all-rpi-runs` | Features ~48.2k; `vrf_leakage` label rows **2220** |
| School Exam promote | wm Macro-F1 **0.717** (gate PASS) |
| Soft-streak | re-applied after promote |
| Trust re-check | **PASS** — exam v1 **0/3**, exam v2 **0/4**, control 30m **0/4** NM FA and **0** spurious ([`control_after_vrf_20260718_2142`](../../data/rpi-net/blind-tests/control_after_vrf_20260718_2142/)) |
| Detection re-check | adversarial blind in flight (post-recall) |
