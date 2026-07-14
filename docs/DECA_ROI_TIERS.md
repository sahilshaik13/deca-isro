# DECA ROI tiers — formulas, application, and next campaign

This note is the standalone handoff for the **prioritized escalation plan**. It complements [`DECA_Model_Development_Blueprint.md`](DECA_Model_Development_Blueprint.md) §4 / §7 and the Phase-1 code in [`notebook/DECA_Model_Training.ipynb`](../notebook/DECA_Model_Training.ipynb).

**Strategy rule:** squeeze the lake with math first (Tiers 1–3), refuse cosmetic synthetic inflation (Tier 4), then scale physical fabric (Tiers 5–6) if Macro-F1 is still below the **92%–96%** target band.

```
Phase 1  →  Tiers 1–3   (software / formula)     ✅ applied on current lake
Phase 2  →  Tier 4      (policy: no SMOTE)       ✅ refused
Phase 3  →  Tiers 5–6   (features + more faults) ⏭ next for rare-class F1
```

---

## Why tiers (not all knobs at once)

Over-applying every lever in one train over-engineers the stack and makes the scorecard unstable. Each tier answers a specific failure mode:

| Failure mode | Symptom on this lake | Tier |
| --- | --- | --- |
| Healthy mass drowns faults | Rare recall ~0.23–0.29 | **1** gate |
| Rare classes cheap to miss | BGP/VRF F1 stuck low | **2** weights |
| Argmax ignores ops cost | Precision-heavy, misses real flaps | **3** thresholds |
| Fake rows inflate F1 | Junior SMOTE fix | **4** refuse |
| Classes not separable in features | Precision stays bad after recall↑ | **5** protocol features |
| Support too small | ~52–75 test rows per rare class | **6** more lab faults |

---

## Tier 1 — Two-stage ensemble (anomaly gate)

### Formula / structure

1. **Gate** (binary): estimate $P(\text{anomaly}\mid x)$ with a weighted XGBoost on
   $y^{\mathrm{bin}} = \mathbf{1}[\texttt{unified\_label} \neq \texttt{healthy}]$.
2. If $P(\text{anomaly}\mid x) < \tau_{\mathrm{gate}}$ → predict `healthy`.
3. Else **fault head** (or full multiclass) scores the fault classes and picks a label using Tier-3 divisors (below).

This stops the ~93% `healthy` prior from owning every leaf of a flat multiclass tree.

### Application (this lake)

- Gate + fault/full heads fitted after median impute.
- Selected mode: **`weighted_multiclass`** with $\tau_{\mathrm{gate}} = 0.40$.
- Effect: mean BGP+VRF recall **~0.26 → ~0.67**.

Artifacts: `models/fault_classifier/fault_classifier_xgb.pkl`, `decision_thresholds.json`.

---

## Tier 2 — Inverse-frequency sample weights

### Formula

For a minibatch / fit set of size $N$ with $K$ classes and class counts $n_c$:

$$
w_i = \frac{N}{K \cdot n_{y_i}}
$$

Applied to the gate, the fault-only head, and the full multiclass head so a miss on BGP/VRF costs more than a miss on `healthy`.

### Application

- Weights recomputed on the **fit** split only (not the held-out test).
- Combined with Tier 1 so rare leaves are not both under-sampled and under-weighted.

---

## Tier 3 — Validation-tuned decision thresholds

### Formula

On the validation slice, sweep:

- gate thresholds $\tau_{\mathrm{gate}} \in \{0.20,0.30,0.40,0.50,0.60\}$
- per-class score divisors $t_c$ (rarer classes may get tighter/looser $t_c$)

Predict by maximizing $p_c(x) / t_c$ among eligible classes (after the gate). Select the grid point that maximizes the **rare-aware score**:

$$
S = 0.4\cdot\mathrm{Macro\text{-}F1} + 0.6\cdot\mathrm{mean}(F1_{\mathrm{rare}})
$$

where “rare” = the lower half of fault-class support on the fit split.

### Application

- Chosen operating point this train: mode `weighted_multiclass`, $\tau_{\mathrm{gate}}=0.40$, class thr $=1.0$.
- Macro-F1 **0.716 → 0.721**; accuracy **0.97 → 0.94** (expected: more anomaly calls).

---

## Tier 4 — SMOTE / synthetic inflation — **REFUSED**

### Why not

Naive SMOTE (or row duplication in feature space) breaks the **chronological physics** of 10-minute windows (slope / rolling_std / accel). Cosmetically higher F1 would be dishonest for network telemetry.

### Application

Encoded in artifacts:

- `smote: false`
- `smote_policy: refused_tier4_temporal_integrity`

Panel line: we will not invent timesteps to pad the scorecard.

---

## Tier 5 — Protocol-level features (roadmap)

### Intent

After Tiers 1–3, rare-class F1 is still **precision-bound** (~0.42 BGP / ~0.52 VRF). If classes overlap in the current 20 rolling features, more injections alone help slowly — add **discriminative protocol signals**:

- BGP hold-timer / session state churn
- VRF route counts / leakage fingerprints
- Tunnel SA lifetime / rekey anomalies

### Application status

Not wired into `rebuild_unified.py` yet. Track as Phase 3 when campaign volume alone is insufficient.

---

## Tier 6 — Scale CE–PE–CE fault campaign (next physical step)

### Intent

Current usable campaign (`20260713_155333`): **21** fault windows. Test support for rare classes is still tiny (~52–75). **More real labelled faults** raise precision without rolling back recall.

### Applied process

`scripts/deca_fault_campaign.py` is **quota-driven**: it continues until each of

`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage`

hits a per-type target. Set `--min-per-type` = `--max-per-type` for an **exact** count (or use `--per-type`).

Between faults the campaign rests ~15–25 minutes of normal ops — expect a 10×4 job to take **many hours** wall-clock. Prefer `tmux` / `nohup`.

### After the job finishes

```bash
python scripts/rebuild_unified.py
jupyter notebook notebook/DECA_Model_Training.ipynb   # retrain; compare Stage 6 tables
```

---

## Scoreboard snapshot (Phase 1 vs baseline)

| Aggregate | Baseline | Phase 1 (Tiers 1–3) |
| --- | ---: | ---: |
| Accuracy | 0.97 | **0.94** |
| Macro-F1 | 0.716 | **0.721** |
| Mean rare recall (BGP+VRF) | ~0.26 | **~0.67** |

| Class | Baseline R | Phase 1 R | Phase 1 F1 |
| --- | ---: | ---: | ---: |
| `bgp_route_flap` | 0.23 | **0.68** | 0.42 |
| `vrf_leakage` | 0.29 | **0.65** | 0.52 |

Reading: Phase 1 did the formula job (recall↑). Remaining F1 gap is scarcity / separability → **Tier 6** (and Tier 5 if needed).

---

## Command — new campaign, 10 faults of each type

From the **repo root**, with Pis reachable and Prometheus on `:9090`:

```bash
cd /home/brain/deca-isro
source .venv/bin/activate

# New run id + exactly 10 injections per fault type (40 total)
python scripts/deca_fault_campaign.py \
  --run-id "$(date -u +%Y%m%d_%H%M%S)_tier6_x10" \
  --per-type 10
```

Equivalent without the shorthand:

```bash
python scripts/deca_fault_campaign.py \
  --run-id "$(date -u +%Y%m%d_%H%M%S)_tier6_x10" \
  --min-per-type 10 \
  --max-per-type 10
```

Resume an interrupted job (same directory / quota):

```bash
python scripts/deca_fault_campaign.py --run-id <existing_run_id> --per-type 10
```

Outputs land under `data/rpi-net/runs/<run-id>/` (`fault_injection_log.csv`, Prom exports, `campaign_state.json`).
