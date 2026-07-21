# Specificity exam v1 — deterministic FP trust bar

**Design / runbook:** [`../DECA_SPECIFICITY_EXAM.md`](../DECA_SPECIFICITY_EXAM.md)  
**Playlist:** [`scripts/playlists/specificity_exam_v1.json`](../../scripts/playlists/specificity_exam_v1.json)

Fixed calm + near-miss phases (no RNG schedule, no real faults). Primary instrument for examining residual cry-wolf after the BGP densify/evidence-gate fix.

## Pass bar

| Check | Require |
| --- | ---: |
| Near-miss FA (confirmed) | **0 / N** |
| Spurious confirms in scored calm phases | **0** |
| BGP confirms (no-pulse invention) | **0** |

Grade: `python scripts/deca_blind_exam_report.py --run-id <id>` (also run by `deca_blind_test.sh` when `exam_phases.jsonl` exists).

## Loom trust knobs (promoted)

| Knob | Value | Why |
| --- | --- | --- |
| `circumstance_prearm` | **false** | Pre-arm shortened confirmed entry on near-miss onsets |
| `enter_k_by_class` tunnel / congestion / BGP / VRF | soft cumulative **4 / 3 / 3 / 3** | Patience after exam v1 (tunnel enter raised to 4) |
| BGP densify-zero + evidence gate | on | Calm-path NaN→flap closed |

## Retrain loop (post exam-v1 FAIL) — ready for re-exam

| Step | Status | Notes |
| --- | --- | --- |
| Loom knobs | done | tunnel enter **4**, others **3**; `circumstance_prearm=false`; soft-streak **on** |
| Data campaign | done | [`SPECIFICITY_DATA_CAMPAIGN_20260717.md`](SPECIFICITY_DATA_CAMPAIGN_20260717.md) — `spec_data_20260717_2352` nm_pe1 **8**, nm_pe2 **4**, reals **3×4** |
| `rebuild_unified --all-rpi-runs` | done | ~46k feature rows; `precursor_aborted` → healthy |
| School Exam promote | done | wm β=1.0; exam Macro-F1 **0.722** (bar 0.721 same-paper honest champ; baseline override 0.7157 vs stale floor) |
| `deca_score_temporal --soft-streak` | done | see loom scoreboard below |

### Offline loom scores (18 Jul 2026, post–spec-data lake)

`python scripts/deca_score_temporal.py --soft-streak` on chrono network tail (`n=9558`, from 2026-07-16). Soft entry: cumulative confidence ≥ `enter_k` (global **3**; tunnel **4**; congestion/BGP/VRF **3**). Exit frame-based (BGP/VRF exit **3**). Artifact: `models/temporal_persist_score.json` / `decision_thresholds.json` → `loom.metrics`.

| Tier | Macro-F1 | Acc | rareR | VRF F1 | BGP F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| raw_frame | 0.763 | 0.836 | 0.776 | 0.713 | 0.487 |
| **persistent (soft)** | **0.840** | **0.909** | 0.750 | 0.747 | 0.702 |
| advisory | 0.813 | 0.900 | 0.645 | 0.808 | 0.521 |

| Boost / lead | Value |
| --- | --- |
| ΔMacro-F1 (raw → sticky) | **+0.078** |
| Frames changed | 1405 |
| Fault frames suppressed | 834 (3404 → 2570) |
| Advisory mean lead | 7.1 frames (max 28); lead precision 0.35 |

Live exam remains the acceptance test (pass bar unchanged).

**Re-exam (18 Jul): PASS** — then ultimate 60+60 the same morning. See live attempt below.

## How to run

```bash
cd ~/deca-isro && source .venv/bin/activate
check stations   # or bash lab/deca_diagnostic.sh
scripts/deca_blind_test.sh specificity_exam_v1 "" 40 -- \
  --playlist scripts/playlists/specificity_exam_v1.json
```

## Live attempt — 18 Jul 2026 (re-exam) — **PASS**

| Field | Value |
| --- | --- |
| **Run ID** | `specificity_exam_v1` (archived `specificity_exam_v1_20260718_0848`) |
| **Date / time** | Saturday **18 July 2026**, **08:17 – ~08:48 IST** (02:47 – ~03:18 UTC) |
| **Seed** | `594596` |
| **Baseline** | ~82 Mbps |
| **Exam result** | **PASS** (trust bar met) |
| **Archive** | [`data/rpi-net/blind-tests/specificity_exam_v1_20260718_0848/`](../../data/rpi-net/blind-tests/specificity_exam_v1_20260718_0848/) |
| **Same-morning ultimate** | [`BLIND_TEST_20260718_0848_60m.md`](BLIND_TEST_20260718_0848_60m.md) · [`BLIND_TEST_CONTROL_20260718_0848_60m.md`](BLIND_TEST_CONTROL_20260718_0848_60m.md) |

### Vs prior attempts

| Metric | `fp_check2` control | Exam FAIL (17 Jul) | **Exam PASS (18 Jul)** |
| --- | ---: | ---: | ---: |
| Near-miss FA | 4 / 4 | 1 / 3 | **0 / 3** |
| Spurious / calm spurious | 5 | 2 | **0** |
| BGP | 0 | 0 | **0** |
| Trust bar | n/a | **FAIL** | **PASS** |

### Phase report

| Phase | Result | Detail |
| --- | --- | --- |
| warm | PASS | not scored |
| calm_a | PASS | spurious=0 |
| nm01 | PASS | stayed healthy |
| calm_b | PASS | spurious=0 |
| nm02 | PASS | stayed healthy |
| calm_c | PASS | spurious=0 |
| nm03 | PASS | stayed healthy |
| calm_d | PASS | spurious=0 |

### Interpretation

1. **Trust bar cleared** after campaign + retrain + soft loom patience.
2. **Same morning** ultimate control also clean (0 NM FA, 0 spurious); blind kept NM clean but missed one PE2 VRF — see [`BLIND_TEST_AGGREGATE_20260718.md`](BLIND_TEST_AGGREGATE_20260718.md).

---

## Live attempt — 17 Jul 2026 (first) — FAIL

| Field | Value |
| --- | --- |
| **Run ID** | `specificity_exam_v1_20260717_1022` |
| **Date / time** | Friday **17 July 2026**, **10:22 – 10:52 IST** (04:52 – 05:22 UTC) |
| **Seed** | `184740` (playlist fixed; seed only leftover campaign RNG e.g. baseline Mbps) |
| **Baseline** | ~23 Mbps |
| **Exam result** | **FAIL** (trust bar not met) |
| **Archive** | [`data/rpi-net/blind-tests/specificity_exam_v1_20260717_1022/`](../../data/rpi-net/blind-tests/specificity_exam_v1_20260717_1022/) |

### Vs prior random control (`control_fp_check2`, 30 min)

| Metric | Prior control | This exam |
| --- | ---: | ---: |
| Near-miss FA | **4 / 4** | **1 / 3** |
| Spurious confirms | **5** | **2** |
| BGP among spurious | 0 | **0** |
| Trust bar | n/a | **FAIL** |

### Phase report

| Phase | Result | Detail |
| --- | --- | --- |
| warm | PASS | not scored |
| calm_a | **FAIL** | spurious `vrf_leakage` @ station2 |
| nm01 | PASS | stayed healthy |
| calm_b | **FAIL** | spurious `tunnel_degradation` @ station2 |
| nm02 | PASS | stayed healthy |
| calm_c | PASS | clean |
| nm03 | **FAIL** | confirmed `tunnel_degradation` |
| calm_d | PASS | clean |

### Interpretation

1. **Exam ground works** — failures are pinned to named phases, not a random control soup.
2. **Trust knobs helped** — near-miss FA 4/4 → 1/3; spurious 5 → 2; BGP stays dead.
3. **Follow-up done:** loom patience (tunnel enter 4 / VRF 3) + [`SPECIFICITY_DATA_CAMPAIGN_20260717.md`](SPECIFICITY_DATA_CAMPAIGN_20260717.md) + retrain/promote → **18 Jul PASS**.

