# DECA → ISRO: Portability & Deployment Story

**One-line pitch:** *We're not shipping ISRO a black-box model — we're shipping a fault-detection pipeline with externalized, protocol-standard configuration that onboards to a new network via a short calibration campaign, not a multi-week retrain.*

---

## The honest starting position

DECA's models are trained on a 3-node Raspberry Pi lab. They will **not** drop into ISRO's production network with frozen weights and work unmodified — no judge with ML experience will believe that claim, and making it would cost more credibility than it buys. What *is* true, and defensible, is narrower and stronger: the **fault taxonomy, feature methodology, and calibration tooling** transfer, even though the specific trained weights don't.

## What actually transfers

### 1. The fault taxonomy is protocol-level, not lab-specific
`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage` are the standard fault classes for any MPLS/L3VPN CE-PE-CE topology — BGP peering, VRF segmentation, and tunnel encapsulation are protocol mechanics, not hardware artifacts of our Pi lab. If ISRO's backbone/ground-segment network uses the same protocol family (very likely, given BGP + VRF + tunneling are the standard building blocks for any carrier-grade multi-site network), the fault *physics* — what a route leak or a session flap looks like in telemetry — carries over even before any retraining.

### 2. Decision logic is externalized config, not hardcoded weights — **verified in the repo today**
`models/fault_classifier/decision_thresholds.json` holds:
- `gate_thr` — the anomaly-gate probability cutoff
- `class_thr` — per-class decision thresholds
- `loom.enter_k_by_class` / `loom.exit_k_by_class` — per-class hysteresis (how many consecutive confident frames before declaring / clearing a fault)

None of this is buried in code. The deployable claim: *point our Prometheus queries at your telemetry endpoints, then recalibrate these ~8 values against a short labeled sample from your network.* That's a calibration pass, not a from-scratch retrain — and it's demoable (see the companion calibration-campaign spec).

### 3. Healthy-baseline generalization is already partially validated with public data
The training lake already blends lab telemetry with public network data (MAWI, RIPE Atlas, Cisco sandbox, BGP update-rate feeds) labeled as `healthy` — roughly 8,000+ rows from networks we've never touched. The anomaly gate's notion of "normal" is not fit to one lab's specific traffic pattern alone. This is a real, already-built argument for "our healthy baseline isn't overfit," independent of the fault-labeled data (which, as established separately, has no public schema-matched source and legitimately requires the lab).

### 4. Onboarding tooling already exists and is fast
`scripts/deca_fault_campaign.py --per-type N` is a working, tested quota-driven campaign runner. Demoing it live (or in a recording) on our own lab *is* the demo of "how ISRO onboards a new network" — the tooling to run a calibration campaign already exists and takes hours, not weeks.

### 5. Features are now baseline-relative, not just absolute-scale — **shipped 21 Jul**
`engineer_features()` (`rebuild_unified.py`) computes, for every metric, a robust per-`(run, host)` median/MAD baseline (unsupervised — no fault labels needed, robust to the fault-minority contaminating the estimate) and emits a full companion feature family (`_z_slope`, `_z_rolling_std`, `_z_rolling_mean`, `_z_accel`) alongside the original absolute-value features. The model can now learn "3 MAD above this host's own normal," not just "above 40 Mbps" — the "deviation from normal, not fixed magnitude" claim is implemented, not aspirational. This was validated immediately: retraining on the enriched feature set (no new lab data) raised the `plain`-family champion's own macro-F1 from ~0.71 to **0.7637–0.7743** (two runs, different random exam papers) — an apples-to-apples, architecture-unchanged gain. The model actually promoted that round was the `wm` head (cluster-augmented booster) at **0.7642**, beating `plain`'s **0.7637** on the same paper by 0.0005 — noise-level, not an architecture win. The gate is currently PASS either way; the promoted artifact in `models/fault_classifier/` is the `wm` config. Full writeup: `docs/DECA_ROI_TIERS.md`, Tier 5c.

## What does NOT transfer yet (say this proactively — it's stronger than hiding it)

- **Trained model weights are lab-specific today.** The XGBoost gate and multiclass head are fit to our lab's traffic scale and topology. Expect degraded accuracy on ISRO's raw telemetry until recalibrated — though the baseline-relative features above should narrow this gap materially, since the model's decision boundaries are now expressed in relative terms rather than our lab's specific absolute traffic magnitudes.
- **No live ISRO data exists or is expected before onboarding.** The calibration campaign (below) is explicitly the mechanism that closes this gap on their network, under their permissions, on their schedule — not something we can fake with public data.
- **Cross-network transfer is an engineering claim, not yet an empirically proven one.** We have baseline-relative features and externalized config; we have not yet run this procedure against a second real network. Say this distinction explicitly if asked.

## The pitch line

*"Four protocol-standard fault classes, a config-driven decision layer already externalized in JSON, and a tested campaign tool that recalibrates it in hours — that's what's inheritable. The weights are a starting prior, not the deliverable."*

---
*Companion doc: [`CALIBRATION_CAMPAIGN_SPEC.md`](CALIBRATION_CAMPAIGN_SPEC.md) — the concrete onboarding procedure this doc references.*
