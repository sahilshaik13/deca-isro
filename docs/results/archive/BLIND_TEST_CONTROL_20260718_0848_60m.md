# DECA control — 18 Jul 2026 (60 min)

**Date / time:** Saturday **18 July 2026**, **09:51 – 10:52 IST** (04:21 – 05:22 UTC)

Ultimate 60+60 leg 2 — all-healthy control after the post–spec-data retrain. Zero real faults; four near-miss baits. Grades cry-wolf under calm Prom telemetry.

**Archive:** [`data/rpi-net/blind-tests/control_20260718_0848_60m/`](../../data/rpi-net/blind-tests/control_20260718_0848_60m/)

**Paired blind:** [`BLIND_TEST_20260718_0848_60m.md`](BLIND_TEST_20260718_0848_60m.md)

**Prior controls:** [`BLIND_TEST_CONTROL_20260716_1924_60m.md`](BLIND_TEST_CONTROL_20260716_1924_60m.md) · [`BLIND_TEST_CONTROL_FP_CHECK2_20260717.md`](BLIND_TEST_CONTROL_FP_CHECK2_20260717.md)

**Aggregate:** [`BLIND_TEST_AGGREGATE_20260718.md`](BLIND_TEST_AGGREGATE_20260718.md)

---

## Run summary

| Field | Value |
| --- | --- |
| **Run ID** | `control_20260718_0848_60m` |
| **Mode** | `--control` (no real faults) |
| **Budget** | 60 min |
| **Seed** | `1784348536` |
| **Near-miss baits** | 4 |
| **Ensemble** | off |
| **Model** | Same promoted stack as paired blind (soft loom, prearm off) |

---

## Scorecard vs prior controls

| Metric | Control `1924` (16 Jul, 60m) | `fp_check2` (17 Jul, 30m) | **This run** (60m) |
| --- | ---: | ---: | ---: |
| Near-miss FA | 3 / 4 | 4 / 4 | **0 / 4** |
| Spurious confirms | **21** | **5** | **0** |
| Of which BGP | **18** | **0** | **0** |

**Clean hour.** No confirmed alarms of any class while nothing was wrong.

---

## Near-miss baits

| Bait | Stayed healthy? | Declared |
| --- | :---: | --- |
| nm01 | **yes** | — |
| nm02 | **yes** | — |
| nm03 | **yes** | — |
| nm04 | **yes** | — |

---

## Interpretation

1. **Catch-9 cry-wolf closed on this instrument** — 0 spurious / hour and 0 near-miss FA under the same loom that passed the specificity exam the same morning.
2. **Do not quote the old “21/hour” as current** — quote this control (and the exam PASS) beside the 16 Jul broken path and the 17 Jul BGP-fix check.
3. **Remaining gap is not calm FP** — paired blind still missed one PE2 VRF and carried 3 station2 spurious during the adversarial hour. Severity remains out of scope for a ship claim.
