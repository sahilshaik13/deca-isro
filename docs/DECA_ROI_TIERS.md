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

## Tier 5 — Protocol-level features (Phase 3 — in progress)

### Intent

After Tiers 1–3, rare-class F1 is still **precision-bound** (~0.42 BGP / ~0.52 VRF). Compound overlap falsification (**0/25** multi-label passes on drowned legs) proved traffic-only features cannot separate co-occurring PE1+PE2 faults — add **orthogonal protocol signals**:

- **VRF route counts / leakage fingerprints** → [`TIER5_VRF_ROUTE_COUNT.md`](TIER5_VRF_ROUTE_COUNT.md) (phase 1: `station2`)
- BGP hold-timer / session state churn (phase 2: `station1`, BGP-under-VRF flip)
- Tunnel SA lifetime / rekey anomalies

### Application status

**Phase 1 wired and verified live end-to-end:** `docs/TIER5_VRF_ROUTE_COUNT.md`. Telegraf exporter deployed on station1/station2, Prometheus scraping confirmed, `PROM_QUERIES` / `METRIC_MAP` / allow-list wired. A pre-existing bug in `inject_vrf_leakage()` (targeted a non-existent `vrf ADMIN` bgp instance instead of the real `vrf-admin`) was found and fixed during wiring — every prior `vrf_leakage` run never leaked a real route; only the accompanying synthetic netem ramp gave it shape. Corrected leak verified live (BGP table `0 → 4` on inject, `4 → 0` on revert).

**Two campaigns in, still gate-FAIL, and the picture is now clearer than "collateral dip":** `tier5_vrf_overlap_20260720_0252` (2× each PE1+VRF) raised `vrf_leakage` exam F1 0.47→0.59 but `bgp_route_flap` dipped 0.51→0.45. The follow-up `tier5_vrf_consolidate_20260720_1418` deliberately weighted toward tunnel+VRF/congestion+VRF and **scheduled zero new bgp+VRF compounds**, hypothesizing the BGP dip was a dilution-by-volume artifact that skipping bgp+VRF would let recover. It didn't: `vrf_leakage` kept climbing (0.59→0.63) but `bgp_route_flap` **kept dropping anyway (0.45→0.35)**, and its live BGP+VRF compound blind got strictly worse (1/2 → 0/2, both legs missed). Candidate macro-F1 0.6948 is flat against the 0.6948 honest same-paper champion — no regression, no net gain, bar still 0.717.

**Read:** adding VRF-only training volume isn't diluting BGP by crowding it out of the schedule — something else is pulling BGP recall down independent of how many bgp+VRF compounds get injected.

**Diagnosed 21 Jul (`scripts/deca_bgp_diagnose.py`, reusable) — not a β-sweep/weighting artifact, a fabricated-feature problem:**
`build_gate()` in `deca_school_exam_train.py` always trains the binary anomaly gate with `boost=1.0, rare_ids=set()` — the β rare-boost sweep only ever touches the downstream multiclass head, so two campaigns' worth of weighting/volume changes could never have moved the gate at all. Instrumenting the gate directly on the current lake (exam_seed=42, family=plain, β=1.5):

| class | mean gate p(anomaly) | flagged @ thr=0.50 |
| --- | --- | --- |
| congestion_breach | 0.861 | 95.4% |
| tunnel_degradation | 0.845 | 90.4% |
| vrf_leakage | 0.738 | 78.9% |
| **bgp_route_flap** | **0.516** | **46.6%** |

Confusion matrix confirms the failure mode is a **gate miss, not head confusion**: of 539 true `bgp_route_flap` exam rows, 288 (53%) are silently predicted `healthy`, vs. only 30 misclassified into another *fault* class. `bgp_route_flap`'s raw fit-pool count (1,724) is close to `tunnel_degradation`'s (1,538, 90.4% flagged) — so this isn't explained by relative volume either.

**Root cause, traced into the injector:** `inject_bgp_route_flap()` (`deca_fault_campaign.py`) does only `vtysh clear bgp soft` + `stamp_bgp_update_pulse()` — and that pulse is a **fabricated scalar written straight into a CSV** ("Prom has no BGP series... each flap stamps a pulse"), not a live scrape, and there is **no accompanying `tc`/`netem` traffic perturbation at all** — the one fault type with zero footprint outside that single stamped number. Compare: `tunnel_degradation`/`congestion_breach` both directly ramp real `netem`/`tbf`; `vrf_leakage`'s injector explicitly *adds* a synthetic netem ramp on PE2 specifically because "pure RT-wait left almost no telemetry shape." `bgp_route_flap` alone has no such crutch. This is the same category of bug as the phantom-VRF finding, one level deeper: the signal isn't just weak, part of it isn't even real.

**Confirmed a live fix exists:** `vtysh -c "show bgp neighbor 10.1.3.1 json"` on station1 already exposes `connectionsDropped` — a real, monotonically-increasing FRR counter that increments on every actual session reset (verified live: 2 drops recorded from real `clear bgp soft` calls). This is the direct BGP analog of the BGP-table `vrf_route_count` fix: replace/augment the fabricated `bgp_update_rate` pulse with a Telegraf-scraped `bgp_flap_count` (or `connectionsDropped` delta) from FRR's own neighbor state.

**Next step, in order of leverage:** (1) build the live `connectionsDropped`-based feature (Tier-5-style exporter, same pattern as `vrf_route_count`) — this is what's actually capping the ceiling, not campaign volume; (2) a dedicated bgp+VRF compound campaign still helps (fixes the 0/2 live-blind exposure gap) but won't lift the gate's separability on its own since it's training more examples of the same thin signal; (3) VRF needs no further attention right now — it's climbing on its own (0.47→0.59→0.63).

### Tier 5b — `bgp_flap_count` shipped and verified live (21 Jul)

Built and deployed the fix above. **`connectionsDropped` turned out to be a dead signal too** — verified live before wiring anything: `clear bgp <nbr> soft` (the injector's actual command) is a route-refresh, not a session reset, so `connectionsEstablished`/`connectionsDropped` never move (3 test clears, zero movement). What does move: the neighbor's own `messageStats.routeRefreshSent`/`routeRefreshRecv` (`show bgp neighbor 10.1.3.1 json`), confirmed +6 sent / +3 recv over 3 test clears while keepalives/opens stayed flat.

- **Exporter:** `lab/deca-bgp-flap-count.sh` — station1 only (10.1.3.1 = station3's loopback, the only BGP neighbor `inject_bgp_route_flap()` touches). Parses with `python3` (no `jq` on the Pis), unlike the VRF script's `awk`.
- **Sudoers:** separate drop-in `/etc/sudoers.d/91-telegraf-bgp-flap` (not appended to the Tier 5 VRF one) so re-running the VRF section's overwriting `tee` can't clobber it.
- **Wired:** `PROM_QUERIES` in `deca_live_common.py` + `deca_fault_campaign.py`, `METRIC_MAP` + allow-list in `rebuild_unified.py`, `lab/deca-deploy.sh` (idempotent install + verify), metric list in `DECA_Full_Pipeline.md`.
- **Verified live end-to-end** (deployed directly to station1, not just written to `deca-deploy.sh`): Prometheus series `bgp_flap_count_value{host="station1",neighbor="10.1.3.1"}` **53 → 56** through the full Telegraf→Prometheus pipeline after 2 real `clear bgp soft` calls — same verification style as the VRF `0→4` check.
- **Not yet done:** rebuild the lake (`rebuild_unified.py`) to backfill `bgp_flap_count_*` engineered features, retrain, and re-run the diagnostic (`deca_bgp_diagnose.py`) to confirm the gate's `bgp_route_flap` separability actually improves before deciding on the bgp+VRF campaign.

### Tier 5b — seed result (21 Jul): real signal, diluted by legacy data, not yet conclusive

Existing lake had **zero** rows with `bgp_flap_count` — the exporter went live *after* the last campaign's telemetry window closed, and `rebuild_unified.py` only reads each run's already-exported `network_telemetry.csv`, so there's no live re-query that can retroactively backfill a metric Telegraf wasn't scraping at the time. Ran a lean standalone seed (`scripts/deca_bgp_flap_recall_campaign.py`, mirrors `deca_vrf_recall_campaign.py`'s pattern — no VRF compound): 6× real `bgp_route_flap`, then rebuild → school exam → `deca_bgp_diagnose.py` against the pre-feature baseline (0.516 mean gate p(anomaly), 46.6% flagged @0.50):

| class | mean p(anomaly) before → after | flagged@0.50 before → after |
| --- | --- | --- |
| **bgp_route_flap** | **0.516 → 0.542** | **46.6% → 49.4%** |
| congestion_breach | 0.861 → 0.849 | 95.4% → 94.4% |
| tunnel_degradation | 0.845 → 0.850 | 90.4% → 92.3% |
| vrf_leakage | 0.738 → 0.730 | 78.9% → 76.9% |

Confusion-matrix recall for `bgp_route_flap` moved the same direction (41.0%→43.8% correctly classified, silent-`healthy` misses 53.4%→50.8%) — consistent across two independent readouts, so this is a real effect, not noise. But it's small: only ~382 of the class's ~2,106 fit-pool rows (≈18%) carry the new signal, the rest are still legacy `NaN`. The **overall** candidate macro-F1 moved more than the isolated gate stat did — **0.6948 → 0.7110**, the closest any round has gotten to the 0.717 bar (gap now 0.006, was 0.022) — still gate FAIL, still nothing promoted.

**Read:** additive, not conclusive on its own. The next bgp+VRF compound campaign will bank more real `bgp_flap_count` volume on top of this (diluting the legacy-NaN majority further) while also fixing the live-blind 0/2 exposure gap — it should compound this gain rather than start over from the fabricated-signal baseline the last two campaigns were stuck with.

### Tier 5b — dedicated bgp+VRF compound campaign (21 Jul): gap narrows to 0.008, no BGP/VRF trade-off this time

Ran `tier5_bgp_vrf_focus_20260721_0618` — 6× `bgp_route_flap`+`vrf_leakage` compounds only (zero tunnel, zero congestion), the same "give the underperforming class its own dedicated volume" playbook that pulled `vrf_leakage` up two rounds ago, now compounding on top of the real `bgp_flap_count` signal instead of the fabricated `bgp_update_rate` one. `bgp_route_flap` lake rows 2,838→3,378.

| metric | before this round | after |
| --- | --- | --- |
| candidate macro-F1 | 0.7110 | **0.7094** |
| gap to bar (0.717) | 0.006 | **0.0076** |
| `bgp_route_flap` exam F1 | 0.41 (gate stat, not exam) | **0.41** |
| `vrf_leakage` exam F1 | 0.63 | **0.65** |

Note the headline macro-F1 dipped slightly (0.7110→0.7094) despite `bgp_route_flap`'s underlying gate/confusion stats holding — this exam used a different random exam-seed draw than the seed campaign's diagnostic readout, so the two numbers aren't a strict apples-to-apples delta; the more reliable comparison is against the *last promotion-gate* run (`tier5_vrf_consolidate`, 0.6948), against which this is a clear gain (+0.0146) with `bgp_route_flap` F1 recovering 0.35→0.41 and, unlike every prior round, **no BGP/VRF trade-off** — `vrf_leakage` kept climbing in the same round BGP recovered, instead of one gaining at the other's expense.

Live re-verify: control blind **0/0 clean** (no false positives). Tunnel+VRF blind **1/2** (tunnel hit, VRF still silently missed under the tunnel — this specific drowning pattern is unchanged by the BGP-focused round, as expected). BGP+VRF blind **1/2 detected but 0/2 correctly classed**: `vrf_leakage` fired but was mislabeled `bgp_route_flap`, while `bgp_route_flap` itself triggered nothing. Read: detection is now improving *ahead of* classification on this compound — the gate is starting to flag the window, but the multiclass head still can't tell the two apart when they overlap. That's a different (and more tractable) problem than the 0/2 total-miss from the last round.

**Read:** the dedicated-volume approach validates for BGP the same way it did for VRF — no further "avoid diluting the other class" caution needed, both can be pushed together. Still gate FAIL, 0.0076 short. Next lever is either (a) more of the same (bank another round of bgp+VRF volume — the trend line is monotonic: 0.35→0.41 F1 over two rounds) or (b) attack the compound-specific class confusion directly now that detection works (e.g. feature interaction between `vrf_route_count` and `bgp_flap_count` so the head can tell *which* protocol signal moved, not just that *something* did).

### Tier 5b — second dedicated bgp+VRF round (21 Jul): per-class F1 keeps climbing, aggregate gate stalls

Explicit sequencing agreed with the user: run one more round of the same dedicated bgp+VRF volume (cheap, tests a real monotonic prediction) before committing to the heavier feature-interaction build; only pivot if the round stalls. Ran `tier5_bgp_vrf_focus2_20260721_1159` — same design as the prior round, 6× `bgp_route_flap`+`vrf_leakage`, 0 tunnel/congestion.

| metric | round 1 (`_focus_`) | round 2 (`_focus2_`) |
| --- | --- | --- |
| candidate macro-F1 | 0.7094 | **0.7077** |
| gap to bar (0.717) | 0.0076 | **0.0093** |
| `bgp_route_flap` exam F1 | 0.41 | **0.43** |
| `vrf_leakage` exam F1 | 0.65 | **0.65** |
| BGP+VRF live blind | 1/2 detected, mislabeled `vrf_leakage`→`bgp_route_flap` | **0/2 — both legs missed** |
| tunnel+VRF live blind | 1/2 (tunnel hit, VRF miss) | 1/2 (unchanged) |
| control blind | 0/0 clean | 0/0 clean |

**Mixed result, not a clean stall or a clean win.** The per-class hypothesis that motivated this round held: `bgp_route_flap` exam F1 kept climbing (0.35→0.41→0.43) with no plateau, and `vrf_leakage` held steady rather than trading off. But the number the promotion gate actually judges — aggregate candidate macro-F1 — didn't move toward the bar across either round (0.7094→0.7077, gap widened not narrowed), and the specific BGP+VRF live-blind draw got *worse*, not better (1/2→0/2). Something is absorbing the per-class BGP/VRF gains before they reach the aggregate — plausibly cross-class confusion (consistent with round 1's finding that the model conflates the two signals when they co-occur) or dilution elsewhere in the now-larger lake (`healthy`/`congestion_breach`/`tunnel_degradation`).

Two honest caveats against over-reading this as a definitive stall: the exam paper is randomly redrawn each run (no fixed `--exam-seed`), so ±0.01–0.02 aggregate noise between rounds is normal on its own; and the live blind is n=2 events per test, so a single hit/miss flip is high-variance, not yet a trend line.

**Read against the pre-agreed decision rule:** closer to "volume alone isn't closing the gap" than "one more round clears it cheaply." Per-class F1 climbing without the aggregate following, plus a live-blind regression on exactly the compound this campaign targets, is the signal that was defined in advance as the trigger to graduate the feature-interaction idea (`vrf_route_count` × `bgp_flap_count` interaction feature) from "good idea for later" to "the actual next thing to build" — the classes look separable in volume terms (per-class F1 keeps improving) but not yet in feature terms (the head still can't disambiguate them when they overlap, which is exactly what an interaction feature would target).

### Tier 5c — baseline-relative features: the stall trigger paid off immediately (21 Jul)

Acted on the pre-agreed rule: pivoted from a third volume round to the feature lever. Rather than building the specific `vrf_route_count`×`bgp_flap_count` interaction column first, went one level more general — added a **baseline-relative companion family** to every engineered metric in `engineer_features()` (`rebuild_unified.py`): for each `(run_id, metric)` group, compute a robust median/MAD center+scale from that run's own series (unsupervised, no label dependency, robust to the fault-minority contaminating the estimate), then emit the same four stats (`_slope`, `_rolling_std`, `_rolling_mean`, `_accel`) on the resulting z-score alongside the existing absolute-value versions. Zero new lab data — same lake, feature count 56→112.

This was also motivated independently by the ISRO portability conversation: absolute-scale features were a real, verified gap in the "recalibrate config, don't retrain" pitch (see `docs/ISRO_PORTABILITY.md`). Fixing it for portability reasons turned out to also be the fix for the BGP/VRF stall — the two problems were the same problem.

**Result — two separate retrains, ran back-to-back on different random exam papers (default `--holdout-policy random` draws a fresh paper each run):**

1. **Dry run** (no `--auto-promote`): winner was `plain` (the unchanged champion architecture) at β=1.0, exam macro-F1 **0.7743**, `bgp_route_flap` F1 0.51, `vrf_leakage` F1 0.76. Not saved to disk — used only to confirm the feature change itself was the driver, with zero architecture change.
2. **Promotion run** (`--auto-promote`, different random exam paper): `plain` β=1.0 scored 0.7637 on this paper (the "champion" bar); `wm` (cluster-augmented booster) edged it by 0.0005 at **0.7642** and won the tiebreak — this is the config actually in `models/fault_classifier/` right now. `bgp_route_flap` F1 **0.48**, `vrf_leakage` F1 **0.75** for this specific promoted artifact.

The 0.0005 gap between `plain` and `wm` on the same paper is noise, not an architecture win — worth stating plainly rather than letting "wm beat the bar" read as an architecture story. The real story is `plain` alone, unchanged, jumping from ~0.71 pre-feature to 0.7637–0.7743 post-feature across two independent exam draws.

| metric | before | after (promoted `wm` config) |
| --- | --- | --- |
| candidate macro-F1 | 0.7094 (best of 3 prior rounds) | **0.7642** |
| gate | FAIL (2 rounds straight) | **PASS** — promoted |
| `bgp_route_flap` exam F1 | 0.43 | **0.48** |
| `vrf_leakage` exam F1 | 0.65 | **0.75** |
| temporal (chronological tail) macro-F1 | — | **0.8233** raw-frame, 0.8923 advisory tier |
| BGP+VRF live blind | 0/2 (last volume round) | **1/2 detected, correctly classed** (was mislabeled in the round before) |
| tunnel+VRF live blind | 1/2 | 1/2 (unchanged — not this feature's target) |
| control live blind | 0/0 clean | 0/0 clean |

Two full rounds of dedicated bgp+VRF campaign volume moved macro-F1 by roughly +0.015 total across both rounds combined. This single feature-engineering change — using data that already existed, no new fault injection — moved it by **+0.055 (promoted config) to +0.065 (dry-run plain config)**, at least 3x the combined volume gain, and is what actually cleared the gate. Confirms the stall diagnosis: the classes were separable in *volume* terms (per-class F1 kept climbing every round) but not in *feature* terms (absolute-scale features couldn't express "how far from this host's own normal," which is what a route leak or session flap actually looks like relative to background noise) — exactly the condition the pre-agreed rule was designed to detect.

The specific cross-class confusion flagged in the second volume round (BGP+VRF detected but `vrf_leakage` mislabeled as `bgp_route_flap`) is also gone in this round's live blind — consistent with baseline-relative features giving the head a cleaner signal to disambiguate which protocol channel actually moved, without needing a hand-built interaction column between the two specific metrics.

**Previous classifier backed up** to `models/fault_classifier.bak_20260721_170939` before promotion, per standard practice.

---

## Tier 5.5 — Deep heads: cluster layer & mixture-of-experts (tested → gate-rejected)

### Intent

Ask whether *architecture* — more "thinking" capacity, clustering, and specialist experts — can lift rare-class F1 without new data. Implemented as opt-in fault-classifier heads in `scripts/deca_model_experts.py`, all sharing the exact gated inference path so the **School Exam gate is the judge**:

- **`plain`** — the current champion booster (XGB, lr 0.08, depth 5, no reg). The control.
- **`wm`** — KMeans **cluster** layer (centroid distances + soft memberships appended to the 20 features) + a deeper, mildly regularized booster (`min_child_weight`, `gamma`, L1/L2 — previously all unset).
- **`moe`** — a generalist booster **plus one one-vs-rest expert per fault class**, blended by a logistic "gating" meta-learner trained on out-of-fold predictions (a stacked / mixture-of-experts head).

### Result (same blind paper, `--exam-seed 42`)

| Head | Exam Macro-F1 | Mean rare recall | BGP F1 | VRF F1 |
| --- | ---: | ---: | ---: | ---: |
| `plain` (champion config) | **0.722** | 0.55 | 0.51 | 0.47 |
| `wm` (clusters + reg) | 0.719 | 0.52 | 0.49 | 0.45 |
| `moe` (experts + gate) | 0.658 | 0.53 | 0.41 | 0.34 |

### Reading

- The **cluster layer is a wash** (−0.003 macro): 8 KMeans centroids on 20 rolling features add no signal the trees didn't already have.
- The **mixture-of-experts is clearly worse** (−0.064 macro): with ~40–60 rare test rows, per-class experts + a meta-gate have far too many parameters and overfit — the same failure mode that made Tier-4 SMOTE a bad idea.
- All three **fail the promotion gate**, so the machine keeps the champion. This is the point: capacity is not the bottleneck, **separable rare-fault physics is**.

### Application status

Heads stay wired and **auto-audited every orchestrator cycle** (`--families plain,wm,moe`). They are *not* the default champion. When Tier 6 / Tier 5 supply more separable rare faults, the gate will promote a deeper head **the moment it actually earns it** — no manual switch. Until then: **data > architecture.**

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
