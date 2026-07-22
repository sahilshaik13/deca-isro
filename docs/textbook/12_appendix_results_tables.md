# Chapter 12 — Appendix: Every Results Table

This chapter is a pure reference — every numeric result quoted anywhere
in this book, gathered into one place, organized by topic, so you don't
have to hunt back through earlier chapters to find a specific number.
Each table links back conceptually to the chapter where it was first
explained in context.

---

## A.1 — Original scoreboard (Phase 1, Tiers 1–3) — see Chapter 8

| Aggregate | Baseline | Phase 1 (Tiers 1–3) |
| --- | ---: | ---: |
| Accuracy | 0.97 | 0.94 |
| Macro-F1 | 0.716 | 0.721 |
| Mean rare recall (BGP+VRF) | ~0.26 | ~0.67 |

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.99 | 0.95 | 0.97 | 3,951 |
| congestion_breach | 0.84 | 0.94 | 0.89 | 108 |
| tunnel_degradation | 0.75 | 0.88 | 0.81 | 77 |
| bgp_route_flap | 0.31 | 0.68 | 0.42 | 75 |
| vrf_leakage | 0.43 | 0.65 | 0.52 | 52 |

---

## A.2 — Companion model scoreboard — see Chapter 6

| Component | Primary score | Notes |
| --- | --- | --- |
| Isolation Forest + Platt | ROC-AUC 0.720 | Unsupervised precursor / dashboard confidence |
| XGBoost Phase 1 (Tiers 1–3) | Macro-F1 0.721, Acc 0.94 | Rare recall ↑; no SMOTE |
| LSTM time-to-breach | MAE 2.133 min | 623 sequences, window length 16 |
| Prophet ×3 | Fit complete | 4,502 / 8,000 / 320 points |
| Topology graph | Eccentricity = 1 for all 3 stations | PE1–PE2–CORE |

---

## A.3 — Tier 5 / 5b / 5c — the VRF and BGP feature story — see Chapter 7 (Problems 6–8) and Chapter 8

| Milestone | `vrf_leakage` F1 | `bgp_route_flap` F1 | Candidate macro-F1 | Gate result |
| --- | ---: | ---: | ---: | --- |
| Original baseline | 0.52 | 0.42 | 0.721 | (pre-Tier-5) |
| After phantom-VRF fix + round 1 (`tier5_vrf_overlap`) | 0.59 | 0.45 | — | FAIL |
| After round 2 (`tier5_vrf_consolidate`, zero new BGP volume) | 0.63 | 0.35 | 0.6948 | FAIL |
| After live `bgp_flap_count` seed campaign | 0.63 | ~0.42 (gate stat) | 0.7110 | FAIL |
| After dedicated bgp+VRF round 1 (`_focus_`) | 0.65 | 0.41 | 0.7094 | FAIL |
| After dedicated bgp+VRF round 2 (`_focus2_`) | 0.65 | 0.43 | 0.7077 | FAIL |
| **After Tier 5c baseline-relative features (dry run)** | **0.76** | **0.51** | **0.7743** | (dry run) |
| **After Tier 5c baseline-relative features (promoted)** | **0.75** | **0.48** | **0.7642** | **PASS** |

| Metric | Value |
| --- | --- |
| Chronological (temporal loom) macro-F1, raw frame | 0.8233 |
| Chronological (temporal loom) macro-F1, with advisory tier | 0.8923 |
| Feature count before Tier 5c | 56 |
| Feature count after Tier 5c | 112 |
| Combined gain from two full campaign rounds (volume alone) | ~+0.015 macro-F1 |
| Gain from Tier 5c feature change alone (zero new lab data) | +0.055 to +0.065 macro-F1 |

---

## A.4 — Tier 5.5 — Deeper architectures, tested and rejected — see Chapter 6 and Chapter 8

| Head | Exam Macro-F1 | Mean rare recall | BGP F1 | VRF F1 |
| --- | ---: | ---: | ---: | ---: |
| `plain` (champion) | 0.722 | 0.55 | 0.51 | 0.47 |
| `wm` (clusters + regularization) | 0.719 | 0.52 | 0.49 | 0.45 |
| `moe` (mixture of experts) | 0.658 | 0.53 | 0.41 | 0.34 |

---

## A.5 — The temporal loom (persistence) boost — see Chapter 6

| Mode | Macro-F1 | Acc | BGP F1 | VRF F1 | Rare recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw frame (no loom) | 0.841 | 0.871 | 0.616 | 0.844 | 0.823 |
| Sticky loom, global settings only | 0.908 | 0.933 | 0.774 | 0.903 | 0.814 |
| Sticky loom + per-class exit tuning | **0.912** | **0.932** | **0.790** | **0.911** | 0.889 |

| Loom refinement | Result |
| --- | --- |
| Per-class `enter_k`/`exit_k` tuning (kept) | BGP F1 0.774 (baseline) vs 0.543 (naive fast-enter, rejected) vs 0.790 (patient exit, kept) |
| Two-tier loom (advisory + confirmed) | Mean lead time 3.8 frames; advisory-only window precision 0.269 |
| TTB gate (binding "what" + "when") | Rejected — strict setting dropped Macro-F1 to 0.628 and missed 6/15 real events |
| Soft streak (confidence-weighted entry) | Kept — BGP F1 0.790 → 0.874 |
| Branch agreement (plain + wm must agree) | Rejected — agreement rate only 41.5%; Macro-F1 dropped to 0.524 |
| Topology gate (neighbors must agree) | Rejected — Macro-F1 dropped from 0.9328 to 0.9271–0.9292 |

---

## A.6 — Blind test detection scoreboard — see Chapter 9

| Run | Detect | Class first→eventual | Confirmed lead | Near-miss false alarms | Spurious |
| --- | ---: | ---: | ---: | ---: | ---: |
| `blind_20260716_1537_60m` | 4/4 | 50%→100% | 2.6 min | 1/1 | 49 |
| `blind_20260716_1924_60m` | 5/5 | 80%→100% | 3.0 min | 2/2 | 17 |
| `blind_20260718_0848_60m` | 3/4 | 75%→75% | 4.6 min | 0/2 | 3 |
| `blind_20260718_2219_60m` | 4/4 | 100%→100% | 4.8 min | 0/0 | 6 |
| `blind_echo_20260719_1102_45m` | 3/3 | 100%→100% | 6.3 min | 1/2 | 0 |
| `blind_vrf_isolated_20260719_1333_45m` | 2/2 | 100%→100% | −3.4 / +3.6 min (per leg) | 0/1 | 0 |

---

## A.7 — Specificity exam and control run scoreboard — see Chapter 9

| Run | Type | Near-miss false alarms | Spurious | Result |
| --- | --- | ---: | ---: | --- |
| `control_20260716_1924_60m` | All-healthy control | 3/4 | 21 (18 fabricated BGP) | Original failure |
| `specificity_exam_v1_20260717_1022` | Fixed playlist exam | 1/3 | 2 | FAIL |
| `specificity_exam_v1_20260718_0848` | Fixed playlist exam (re-run after fix) | 0/3 | 0 | PASS |
| `specificity_exam_v2_20260718_1752` | Fixed playlist exam (unseen playlist) | 0/4 | 0 | PASS |
| `control_20260718_0848_60m` | All-healthy control | 0/4 | 0 | PASS |
| `control_echo_20260719_1027_30m` | All-healthy control (post echo-gate) | 0/4 | 0 | PASS |

---

## A.8 — Ensemble agreement check (`plain` + `wm`) — see Chapter 6, Chapter 9

| Head | Exam Macro-F1 | Rare recall |
| --- | ---: | ---: |
| `plain` (promoted) | 0.815 | 0.791 |
| `wm` (study-only) | 0.792 | 0.736 |

Agreement rate between the two heads: 96.6%. Requiring agreement before
confirming suppressed 91 out of 521 (17%) of `plain`-alone false alarms
on that specific exam paper.

---

## A.9 — Recalibration demo output — see Chapter 10

```
Recalibration sample: 18,549 rows, classes=[healthy, congestion_breach,
  tunnel_degradation, bgp_route_flap, vrf_leakage]
BEFORE — scored on THIS sample with OLD thresholds: macro_f1=0.7964  rare_recall=0.6660
AFTER  — scored on THIS sample with NEW thresholds: macro_f1=0.7964
Δ macro-F1 from recalibration alone (no retrain): +0.0000
```

(Explained fully in Chapter 10: this zero delta is the *expected*,
*correct* result when recalibrating against the same lake the model was
already tuned on — it proves the mechanism runs and produces a real
before/after comparison, not that recalibration never changes anything.)

---

## A.10 — Calibration campaign time estimate — see Chapter 10

| Onboarding step | Estimated cost |
| --- | --- |
| Labeled sample generation (`--per-type 3`, 12 events) | ~5–6 hours, one overnight/maintenance window |
| Tier A recalibration (thresholds only) | Minutes, no retraining |
| Tier B lightweight retrain (only if Tier A insufficient) | Comparable to one existing training cycle |

---

## A.11 — Quick reference: the full tier ladder — see Chapter 8

| Tier | Change | Biggest measured win |
| --- | --- | --- |
| 1 | Binary anomaly gate before multiclass decision | Rare recall 0.26 → 0.67 |
| 2 | Inverse-frequency sample weighting | Supports Tier 1's gain |
| 3 | Validation-tuned decision thresholds | Macro-F1 0.716 → 0.721 |
| 4 | Refused SMOTE / synthetic data | Protected the honesty of every later number |
| 5 (5a–5b) | Real protocol features (`vrf_route_count`, `bgp_flap_count`); fixed two silently broken fault signals | Two major bug fixes; macro-F1 climbing toward 0.71 |
| 5.5 | Tested deeper architectures (`wm`, `moe`) | Confirmed data/features, not model capacity, was the bottleneck |
| 5c | Baseline-relative (z-score) feature family | Macro-F1 0.71 → 0.76+, gate PASS, unlocked portability |
| 6 | More raw campaign volume | Ongoing, used selectively |

---

## End of the book

That completes all twelve chapters. If you are new to this project, the
best next step is to go back to
[Chapter 0 — Start Here](00_START_HERE.md) and use its table of contents
to revisit any chapter that's most relevant to what you're working on
next. If you are presenting this project to someone else, Chapter 7
(*Risen from the Fallen*) and this appendix are the two chapters most
likely to be useful to have open side by side.
