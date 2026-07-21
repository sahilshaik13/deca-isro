# DECA control FP check — 17 Jul 2026 (30 min)

**Date / time:** Friday **17 July 2026**, **09:30 – 10:00 IST** (04:00 – 04:30 UTC)

Post-fix all-healthy control after calm-path BGP densify + no-pulse evidence gate. Validates whether the Catch‑9 cry-wolf rate (especially invented `bgp_route_flap`) dropped under real Prom telemetry.

**Archive:** [`data/rpi-net/blind-tests/control_fp_check2_20260717_30m/`](../../data/rpi-net/blind-tests/control_fp_check2_20260717_30m/)

**Prior control (broken BGP path):** [`BLIND_TEST_CONTROL_20260716_1924_60m.md`](BLIND_TEST_CONTROL_20260716_1924_60m.md)

---

## Run summary

| Field | Value |
| --- | --- |
| **Run ID** | `control_fp_check2` |
| **Mode** | `--control` (no real faults) |
| **Budget** | 30 min |
| **Seed** | `379956` |
| **Near-miss baits** | 4 |
| **Baseline** | ~40 Mbps iperf3 |
| **Operator** | live (venv); densify-zero + BGP evidence gate |

---

## Scorecard vs prior control

| Metric | Prior `1924` (60 min) | **This run** (30 min) |
| --- | ---: | ---: |
| Near-miss FA | 3 / 4 | **4 / 4** |
| Spurious confirms | **21** | **5** |
| Of which `bgp_route_flap` | **18** | **0** |
| Spurious classes | mostly BGP | tunnel 3 + congestion 2 (all station2) |

**BGP invention is gone.** Spurious confirms fell sharply; remaining cry-wolf is tunnel/congestion on station2, plus every near-miss still baited a confirm on station1.

---

## Near-miss baits

| Bait | Stayed healthy? | Declared |
| --- | :---: | --- |
| nm01 | no | congestion_breach |
| nm02 | no | tunnel_degradation |
| nm03 | no | tunnel_degradation |
| nm04 | no | tunnel_degradation |

---

## Interpretation

1. **Fix validated for its target:** zero BGP confirms with no stamped pulses — the NaN→flap path is closed.
2. **Specificity not solved:** ~5 spurious / 30 min (~10/hour if linear) still too high for NOC trust; near-miss discrimination **worse** (4/4).
3. **Next chase (done):** tunnel/congestion calm FPs + near-miss gating — exam FAIL → [`SPECIFICITY_DATA_CAMPAIGN_20260717.md`](SPECIFICITY_DATA_CAMPAIGN_20260717.md) → retrain → exam **PASS** + control **0 spurious** ([`BLIND_TEST_AGGREGATE_20260718.md`](BLIND_TEST_AGGREGATE_20260718.md)). Not more BGP densify.

Do not quote the old “21/hour” as current; quote this control beside it.
