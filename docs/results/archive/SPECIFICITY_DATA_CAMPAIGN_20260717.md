# Specificity data campaign — `spec_data_20260717_2352`

**Purpose:** After specificity exam v1 **FAIL**, teach the lake aborted onsets (stay healthy) on PE1 + PE2 and keep balanced real faults so retrain does not forget detection.

**Driver:** [`scripts/deca_specificity_data_campaign.py`](../../scripts/deca_specificity_data_campaign.py)  
**Injectors:** [`scripts/deca_fault_campaign.py`](../../scripts/deca_fault_campaign.py) (`inject_near_miss_aborted`, `inject_near_miss_pe2_aborted`, real fault injectors)  
**Exam design:** [`../DECA_SPECIFICITY_EXAM.md`](../DECA_SPECIFICITY_EXAM.md)  
**Exam scoreboard:** [`SPECIFICITY_EXAM_V1.md`](SPECIFICITY_EXAM_V1.md)

## When / where

| Field | Value |
| --- | --- |
| **Run ID** | `spec_data_20260717_2352` |
| **Wall clock** | Fri **17 Jul 2026** 23:52 IST start → Sat **18 Jul** ~05:39 IST done (~5.8 h) |
| **UTC** | 2026-07-17 **18:22** → 2026-07-18 **00:09** |
| **Baseline traffic** | ~17–85 Mbps (iperf eth0 station1→station2; refreshed after each real fault) |
| **Artifacts** | [`data/rpi-net/runs/spec_data_20260717_2352/`](../../data/rpi-net/runs/spec_data_20260717_2352/) |

## Quotas (all met)

| Bucket | Target | Done | Label |
| --- | ---: | ---: | --- |
| PE1 near-miss | 8 | **8/8** | `precursor_aborted` → healthy in rebuild |
| PE2 near-miss | 4 | **4/4** | `precursor_aborted` (station2 netem abort) |
| Real tunnel | 3 | **3** | `tunnel_degradation` |
| Real congestion | 3 | **3** | `congestion_breach` |
| Real VRF | 3 | **3** | `vrf_leakage` |
| Real BGP | 3 | **3** | `bgp_route_flap` |
| **Total log rows** | 24 | **24** | |

Command used:

```bash
python scripts/deca_specificity_data_campaign.py \
  --run-id spec_data_20260717_2352 \
  --near-misses-pe1 8 --near-misses-pe2 4 --per-type 3
```

## How this campaign differs from prior lab campaigns

| | Tier-6 / fault campaign | Circumstance `circ_v2` | **This run** |
| --- | --- | --- | --- |
| Goal | Volume / diversity of **real** faults | 3-phase circumstance labels | **Cry-wolf teaching** + detection retention |
| Near-miss | optional / random hold | included | **Quota:** 8 PE1 + 4 PE2, fixed hold ladder |
| PE2 abort | no | no | **yes** (`inject_near_miss_pe2_aborted`) — exam failed VRF/tunnel @ station2 |
| Real mix | quota × type | 5×4 circumstance | **3×4** confusion-triangle first, BGP last |
| Schedule | long rests (15–25 min) | circumstance phases | Short rests **4–7 min**; settle **3–5 min** after reals |
| Validation | duration spread checks | PASS 5×4 | **WARN** (small-n duration uniformity) — OK to train |

Fixed near-miss holds (seconds): PE1 `[25,30,35,40,45,50,30,40]`, PE2 `[30,35,40,45]`.

## Outcome

**SUCCESS** — quotas complete; usable for Mode-B rebuild/train.

| Check | Result |
| --- | --- |
| Quotas | nm_pe1 **8/8**, nm_pe2 **4/4**, reals **3 each × 4 types** |
| Validation | **WARN** — congestion/BGP avg duration spread flagged on n=3. **Hand-check (18 Jul):** congestion **9.70 / 9.88 / 11.03** min (spread **1.33**); BGP **9.34 / 10.15 / 10.89** min (spread **1.55**). Not a collapsed-timestamp bug — OK to train. |
| Ops hiccups | SSH timeout/banner on station1 during nm_pe1_007 cleanup and late BGP flap #3 — events still logged |
| Telemetry export | Initially missing at campaign end; **backfilled** 18 Jul ~02:30 UTC via Prom export + BGP pulse merge (~35.8k telemetry rows). Script now exports at end for future runs. |

### Real-fault duration summary (validation)

| Type | n | avg | spread |
| --- | ---: | ---: | ---: |
| congestion_breach | 3 | 10.2 min | 0.7 min (WARN) |
| tunnel_degradation | 3 | 7.0 min | 1.9 min |
| bgp_route_flap | 3 | 10.1 min | 0.8 min (WARN) |
| vrf_leakage | 3 | 5.3 min | 1.0 min |

### On-disk artifacts

| File | Role |
| --- | --- |
| `fault_injection_log.csv` | 24 labeled windows |
| `campaign_run.log` | Full audit trail |
| `bgp_update_samples.csv` | Stamped BGP pulses for real flaps |
| `network_telemetry.csv` | ~35.8k long-form Prom rows (backfill) |
| `network_campaign_export.csv` | ~6.0k wide rows + labels |

## Downstream (18 Jul 2026)

| Step | Result |
| --- | --- |
| `rebuild_unified.py --all-rpi-runs` | Features ~46k; `precursor_aborted` → healthy |
| School Exam promote | wm Macro-F1 **0.722** (same-paper bar 0.721) |
| Soft-streak loom | chrono persistent Macro-F1 **0.840** (Δ+0.078) — see [`SPECIFICITY_EXAM_V1.md`](SPECIFICITY_EXAM_V1.md) |
| Live re-exam | **PASS** 18 Jul — [`SPECIFICITY_EXAM_V1.md`](SPECIFICITY_EXAM_V1.md) |
| Ultimate 60+60 | same morning — blind [`BLIND_TEST_20260718_0848_60m.md`](BLIND_TEST_20260718_0848_60m.md) · control [`BLIND_TEST_CONTROL_20260718_0848_60m.md`](BLIND_TEST_CONTROL_20260718_0848_60m.md) · [`BLIND_TEST_AGGREGATE_20260718.md`](BLIND_TEST_AGGREGATE_20260718.md) |

## Script backups

Pre-specificity injectors preserved under [`scripts/backup/`](../../scripts/backup/) (see that folder’s README). Live driver remains `scripts/deca_specificity_data_campaign.py`.
