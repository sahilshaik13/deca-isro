# Calibration Campaign Spec — Onboarding DECA to a New Network

**Purpose:** the concrete procedure referenced by [`ISRO_PORTABILITY.md`](ISRO_PORTABILITY.md). This is written to be demoable — every step below runs against our own lab today; onboarding a new network repeats the same steps against theirs.

**Explicit non-goal:** this is not a claim that ISRO's network needs zero new data. It needs a *short, quota-bounded* labeled sample — hours of campaign time, not weeks of retraining, and importantly, run by ISRO under their own permissions since we have no access to their telemetry or authority to fault-inject on their infrastructure.

---

## Two onboarding tiers, by cost

### Tier A — Threshold-only recalibration (fastest, config stays code-free)

**When this is enough:** the underlying protocol/traffic *shape* of ISRO's fault signatures is similar to ours, and the only real difference is scale (different baseline traffic volume, different absolute jitter/loss magnitudes) — i.e., the classifier's learned decision boundaries are approximately right, just miscalibrated.

**Mechanism — shipped 21 Jul, `scripts/deca_recalibrate.py`:** loads the already-fitted active gate + multiclass head (`models/fault_classifier/fault_classifier_xgb.pkl`) exactly as-is — no tree is refit — and re-runs the existing `tune_thresholds()` grid search against a labeled sample. Two modes:

```bash
# Demo mode: no target-network data needed, proves the mechanism end-to-end
# against a fresh holdout draw from our own lake.
python scripts/deca_recalibrate.py

# Real onboarding: point at the target network's labeled sample (already run
# through rebuild_unified.py so it's in the unified schema).
python scripts/deca_recalibrate.py --sample-parquet path/to/isro_sample.parquet --apply
```

Default is a dry run — prints old vs. new `gate_thr`/`class_thr` and the macro-F1 delta from recalibration alone, no files touched. `--apply` backs up the previous `models/fault_classifier/` state, then patches only the threshold fields in the pkl bundles + `decision_thresholds.json` — the underlying XGBoost trees are never touched.

Demo output against our own lake (expected result — see honest caveat below):
```
Recalibration sample: 18549 rows, classes=[healthy, congestion_breach, tunnel_degradation, bgp_route_flap, vrf_leakage]
BEFORE — gate_thr=0.5  class_thr={...}
  scored on THIS sample with OLD thresholds: macro_f1=0.7964  rare_recall=0.6660
AFTER  — gate_thr=0.5  class_thr={...}
  scored on THIS sample with NEW thresholds: macro_f1=0.7964
Δ macro-F1 from recalibration alone (no retrain): +0.0000
```
**Honest caveat on this specific demo output:** the delta is zero here because the sample is drawn from the *same* lake the active model's thresholds were already tuned against — there's nothing to recalibrate. That's the correct, expected result for this demo, not a bug. Say this explicitly if a judge runs it and sees a flat delta: it proves the mechanism runs and produces a real before/after score, not that recalibration always changes nothing. A genuinely different network's sample would show a nonzero shift.

**Output:** an updated `decision_thresholds.json` for ISRO's network, same schema as ours, no retrain.

### Tier B — Lightweight retrain (when Tier A isn't sufficient)

**When needed:** if ISRO's fault physics genuinely differs enough (different topology depth, different tunnel/VRF implementation details) that the tree splits themselves need to adapt, not just the thresholds.

**Mechanism:** exactly the pipeline used throughout this project —
```bash
python scripts/rebuild_unified.py          # fold ISRO's labeled sample into the feature lake
python scripts/deca_school_exam_train.py --auto-promote   # retrain + threshold sweep + gate
```
Our lab data stays in the lake as a prior (transfer learning by data pooling, not fine-tuning) — ISRO's sample doesn't need to be large enough to train from scratch, only large enough to shift the decision boundary toward their traffic's specific signature.

---

## The labeled-sample generation step (what ISRO actually has to run)

This is the part that requires access to *their* network, under *their* permissions — the one thing we cannot substitute with public data or our lab, and said plainly rather than glossed over.

```bash
python scripts/deca_fault_campaign.py \
  --run-id "isro_calibration_$(date -u +%Y%m%d_%H%M)" \
  --per-type 3
```

- `--per-type 3` → 3 injections × 4 fault classes = 12 total events. Quota-driven (`deca_fault_campaign.py` already supports `--min-per-type`/`--max-per-type`/`--per-type` and rests ~15–25 min of normal ops between injections, matching the same cadence used for every lab campaign in this project).
- Wall-clock estimate, extrapolated from our own campaign logs: 12 events × (~8 min fault + ~20 min rest) ≈ **5–6 hours**, run once, ideally overnight or during a maintenance window.
- Requires: SSH/API access to ISRO's routers with permission to run the equivalent fault primitives (`tc`/`netem`-style traffic shaping, `vtysh`-equivalent BGP soft-clears, VRF route-target misconfiguration) — this is a permissions and access conversation with ISRO, not an engineering one on our side.
- If ISRO cannot permit live fault injection on production hardware at all: the fallback is a **passive-only** calibration — collect a healthy-traffic sample (no injected faults) long enough to recalibrate the anomaly gate's `healthy` baseline (this is the autoencoder-style “normal” fingerprint concept, adapted to the current XGBoost gate), while classification-side thresholds stay at lab-trained defaults until a fault-labeled sample becomes available. Weaker, but requires zero fault injection on their live network.

---

## What we can demo today, without ISRO's network

Everything upstream of "point it at ISRO's telemetry" is demoable right now, on our own lab, as a stand-in:

1. Run `deca_fault_campaign.py --per-type 2` (a *mini* calibration campaign) end-to-end live, narrating it as "this is the exact procedure ISRO would run."
2. Show `rebuild_unified.py` folding the new run into the lake.
3. Show `decision_thresholds.json` diffing before/after a retrain — concrete proof that onboarding changes ~8 JSON values, not a from-scratch model.
4. Show the public-data healthy-baseline blend (MAWI/RIPE Atlas rows tagged `source=public`) in the unified dataset as evidence the gate's "healthy" concept already spans more than one network's traffic pattern.

## Honest gaps to state proactively if asked

- Features are now baseline-relative (median/MAD z-score companions, shipped 21 Jul — see `ISRO_PORTABILITY.md`), which is what makes Tier A calibration plausible in the first place: absolute-scale features would have made "same thresholds, different network scale" mostly wishful. This is no longer a gap, but worth stating that it's a recent addition, not something battle-tested across networks yet.
- We have never run this procedure against a second real network. The claim is "the tooling and mechanism exist and are fast," not "we've already proven cross-network transfer empirically." Say this distinction explicitly — it's the difference between an engineering claim and an unfalsified promise.
- Tier A assumes the target network's fault classes map onto our four (`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage`). If ISRO's network has fault modes outside this taxonomy, Tier A recalibration won't surface them — that requires new labeled data and likely Tier B, not just a threshold shift.
