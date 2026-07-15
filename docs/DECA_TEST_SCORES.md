# DECA test scores

Score timeline for DECA after **Tier‑6 new campaign data** + the **School Exam classroom** (repeated holdout + promotion gate).

| Lake | Rows | BGP | VRF | Campaign |
| --- | ---: | ---: | ---: | --- |
| **Before** | 17,050 | 300 | 210 | `20260713_155333` |
| **After (now)** | **23,909** | **1,224** | **615** | + `20260714_165648_tier6_x10` (40 faults, 10×4) |

Sources: `models/school_exam/seed_report.md` · `models/school_exam/latest_exam.json` · `models/playground/scoreboard.md` · `models/companions_retrain.json`

---

## Timeline at a glance

| Stage | Lake | What | Fault classifier Macro‑F1 | BGP F1 | VRF F1 |
| --- | --- | --- | ---: | ---: | ---: |
| **1. Initial** | old 17k | Notebook Phase‑1 train | **0.721** | 0.42 | 0.52 |
| **2. Classroom** | new 24k | School Exam promote (`wm` head) | **0.725** | 0.45 | 0.46 |
| **3. Playground** | new 24k | Mixed blind paper (live models) | **0.802** | **0.58** | **0.63** |
| **4. Temporal Loom** | new 24k | Chronological sticky (`enter_k=3`) | **0.880** | **0.86** | **0.87** |

![Fault classifier Macro-F1 and rare recall across stages](assets/scores/fault_classifier_stages.png)

**Classroom** = School Exam engine (study hall β sweep + great exam + gate).  
**Did scores improve?** Yes on the rare faults that Matter — especially **BGP** (0.42 → **0.58** playground F1) after 4× more labelled flaps. Congestion / tunnel stay strong. VRF playground F1 also rose (0.52 → **0.63**).  
**Loom** adds another **+0.094 Macro‑F1** on the chronological network tail (raw 0.786 → sticky **0.880**) — see `docs/DECA_TEMPORAL_LOOM.md`.

---

## 1. Initial scores (old lake — Phase‑1 notebook)

Holdout: notebook stratified **25%**. Snapshot from first Phase‑1 train on 17,050 rows.

![Initial individual models](assets/scores/initial_individual_models.png)

### Every model

| Model | Primary metric | Score | Notes |
| --- | --- | ---: | --- |
| Isolation Forest + Platt | ROC‑AUC | **0.720** | Precursor / dashboard confidence |
| XGBoost Phase‑1 | Macro‑F1 | **0.721** | Acc **0.94** · no SMOTE |
| LSTM time‑to‑breach | MAE | **2.133 min** | 623 sequences · $T=16$ |
| Prophet ×3 | Fit | complete | 4,502 / 8,000 / 320 points |
| Topology | eccentricity | $e(v)=1$ ∀ | PE1–PE2–CORE |

### Fault classifier — per class (initial)

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.99 | 0.95 | 0.97 | 3,951 |
| congestion_breach | 0.84 | 0.94 | 0.89 | 108 |
| tunnel_degradation | 0.75 | 0.88 | 0.81 | 77 |
| bgp_route_flap | 0.31 | 0.68 | 0.42 | 75 |
| vrf_leakage | 0.43 | 0.65 | 0.52 | 52 |

Mean BGP+VRF recall ≈ **0.665**.

---

## 2. Classroom — just learnt (School Exam on new lake)

After Mode B ingest of the Tier‑6 campaign. Classroom = teach → test → examine → score → promote.

**Promoted head:** `wm` (KMeans cluster layer + regularized XGB) · $\beta=1.0$ · $\tau_{\mathrm{gate}}=0.60$.  
**Exam seed (promote sitting):** `1784130077` · baseline floor re‑set to **0.71** (old manifest 0.7498 was lake‑stale).

### Same-paper unit test vs classroom candidate

| Who | Macro‑F1 | Mean rare recall | Notes |
| --- | ---: | ---: | --- |
| Old deployed model (pre‑promote) | **0.335** | **0.00** | Trained on old lake — **stale** on new faults |
| Classroom candidate (`wm`) | **0.725** | 0.452 | Gate **PASS** → promoted |

### Candidate per-class F1 (promote exam paper)

| Class | F1 |
| --- | ---: |
| healthy | 0.944 |
| congestion_breach | 0.930 |
| tunnel_degradation | 0.838 |
| bgp_route_flap | 0.449 |
| vrf_leakage | 0.462 |

### Classroom stability (5 fresh papers — honest numbers)

Technique: **repeated holdout validation** + **promotion gate** (demo name: School Exam).

| Metric | Old lake (honest) | New lake (best family) | Δ |
| --- | ---: | ---: | ---: |
| Macro‑F1 | 0.714 ± 0.012 | **0.732 ± 0.004** | **+0.018** |
| BGP F1 | 0.408 ± 0.024 | **0.481 ± 0.015** | **+0.073** |
| VRF F1 | 0.466 ± 0.029 | 0.466 ± 0.021 | ~0 |
| `wm` beat `plain` | 0/5 | **4/5** | cluster head earns it |
| Gate PASS | 0/5 (stale floor) | **5/5** | after re‑baseline |

Full table: `models/school_exam/seed_report.md`.

### Companions at classroom stage

Retrained with `deca_retrain_companions.py` (classifier untouched):

| Model | Score after retrain |
| --- | ---: |
| Isolation Forest ROC‑AUC | **0.582** |
| LSTM MAE | **2.014 min** (1,316 sequences) |
| Prophet ×3 | Fit (5,344 / 8,000 / 320) |
| Topology | $e(v)=1$ |

---

## 3. Playground scores (mixed general test — new lake)

Run: `python scripts/deca_model_playground.py --exam-seed 20260715 --prophet-refit`  
Lake **23,909** · exam **4,782** rows · live **promoted `wm`** classifier + retrained companions.

![Playground individual models](assets/scores/playground_individual_models.png)

### Every model individually

| Model | Primary metric | Score | Extra |
| --- | --- | ---: | --- |
| Isolation Forest + Platt | ROC‑AUC | **0.571** | AP 0.191 |
| Fault classifier (`wm`, promoted) | Macro‑F1 | **0.802** | Acc **0.925** · rareR **0.613** |
| LSTM time‑to‑breach | MAE | **2.467 min** | n=1,938 sequences on paper |
| Prophet ifInOctets | MAE | 1.816×10⁹ | sMAPE 2.00 · honest refit |
| Prophet jitter_ms | MAE | 185.8 | sMAPE 1.86 · honest refit |
| Prophet bgp_update_rate | MAE | 8882 | sMAPE 0.44 · honest refit |
| Topology | eccentricity | $e=1$ | structure only |

### Fault classifier — per class (playground paper)

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.96 | 0.95 | 0.96 | 3,992 |
| congestion_breach | 0.94 | 0.98 | 0.96 | 252 |
| tunnel_degradation | 0.83 | 0.95 | 0.88 | 170 |
| bgp_route_flap | **0.57** | 0.60 | **0.58** | 245 |
| vrf_leakage | **0.63** | 0.63 | **0.63** | 123 |

---

## Cross-stage comparison (fault classifier)

![Per-class F1 by stage](assets/scores/per_class_f1_stages.png)

| Metric | 1. Initial (old) | 2. Classroom (new) | 3. Playground (new) |
| --- | ---: | ---: | ---: |
| Macro‑F1 | 0.721 | **0.725** | **0.802** |
| Accuracy | 0.94 | — | **0.925** |
| Mean rare recall | ~0.665 | 0.452 | **0.613** |
| BGP F1 | 0.42 | 0.45 | **0.58** |
| VRF F1 | 0.52 | 0.46 | **0.63** |
| Holdout | notebook 25% | exam seed 1784130077 | exam seed 20260715 |

Papers differ across stages — treat playground as the **live stacked scoreboard**, and the **5‑seed classroom ranges** as the honest “did Tier‑6 help?” answer (BGP **yes**, VRF **steady**).

Re-run:

```bash
python scripts/deca_mlops_orchestrator.py --mode B --rpi-run <id>   # ingest + classroom
python scripts/deca_retrain_companions.py                          # IF / LSTM / Prophet
python scripts/deca_school_exam_train.py --report-seeds 5          # classroom stability
python scripts/deca_model_playground.py --exam-seed 20260715 --prophet-refit
```

---

## Cross-stage comparison (companions)

![Companions initial vs playground](assets/scores/companions_initial_vs_playground.png)

| Model | 1. Initial (old) | Retrain (new) | 3. Playground (new) |
| --- | ---: | ---: | ---: |
| Isolation Forest ROC‑AUC | 0.720 | 0.582 | 0.571 |
| LSTM MAE (min, ↓ better) | 2.133 | **2.014** | 2.467 |
| Prophet | fit-only | refit | honest-refit MAE (§3) |
| Topology $e(v)$ | 1 | 1 | 1 |

IF AUC dropped because the lake is denser in faults (anomaly rate ↑, contamination capped at 0.08) — expected, not a regression of “XGB got worse.” LSTM retrain improved; playground MAE is on a different sequence holdout.

---

## Per-fault F1 improvement (line chart)

Fault classifier F1 for each class: **Initial (old) → Classroom (new) → Playground (new)**.

> Cursor’s Markdown preview often strips SVG/HTML. Open in a browser:

**[Open line chart (HTML)](per_fault_f1_line.html)** · [PNG](per_fault_f1_line.png) · [SVG](per_fault_f1_line.svg)

| Fault | 1. Initial | 2. Classroom | 3. Playground | Δ (Initial → Playground) |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.97 | 0.944 | 0.96 | −0.01 |
| congestion_breach | 0.89 | 0.930 | **0.96** | **+0.07** |
| tunnel_degradation | 0.81 | 0.838 | 0.88 | +0.07 |
| bgp_route_flap | 0.42 | 0.449 | **0.58** | **+0.16** |
| vrf_leakage | 0.52 | 0.462 | **0.63** | **+0.11** |

---

## Bottom line

1. **New data worked** — BGP F1 rose in both honest multi-seed classroom (**+0.07**) and playground (**+0.16** vs initial).
2. **Classroom promoted a real upgrade** — replaced a model that scored **0.335** on the new lake with a `wm` cluster head at **0.725** exam / **0.802** playground Macro‑F1.
3. **Cluster head now earns wins** — `wm` beat `plain` on **4/5** fresh papers (it never did on the old lake).

---

## Related

| Doc / artifact | Role |
| --- | --- |
| [`MODELS.md`](MODELS.md) | Model catalog |
| [`DECA_MLOps_Continuous_Learning_Pipeline.md`](DECA_MLOps_Continuous_Learning_Pipeline.md) | School Exam / repeated-holdout |
| [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md) | Tier 5.5 / Tier 6 |
| `models/playground/scoreboard.md` | Latest playground |
| `models/school_exam/seed_report.md` | 5-seed classroom stability |
| Chart assets | `docs/assets/scores/*.png` |
