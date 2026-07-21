# Data campaigns / runs — cumulative

**Folder:** `data/rpi-net/runs/`  
**This file is the only campaign scoreboard you need.** Detailed write-ups archived under [`docs/results/archive/`](../../../docs/results/archive/).

**Related:** [Blind cumulative](../blind-tests/CUMULATIVE.md) · [Live trust cumulative](../live/CUMULATIVE.md)

---

## How to read this

These are **labelled training windows** (fault injection + Prom export), not live model grades. After a run finishes: `rebuild_unified.py --all-rpi-runs` then School Exam / soft-streak before trusting a new promote.

---

## Campaign inventory

| Run ID | When | Purpose | Quotas / outcome |
| --- | --- | --- | --- |
| `20260713_155333` | 13–14 Jul | Early CE–PE–CE fault volume | Foundational lake |
| `20260714_165648_tier6_x10` | 14 Jul | Tier‑6 scale (`--per-type` style) | Volume |
| `20260715_191519_circ_v2` | 15 Jul | Circumstance 3-phase (5×4) | **VALIDATION PASS** |
| `spec_data_20260717_2352` | 17–18 Jul | Specificity teaching: NM PE1+PE2 + confusion-triangle reals | nm **8+4**, reals **3×4**; duration WARN **hand-checked OK** |
| `vrf_recall_20260718_1752` | 18 Jul | Completed VRF (+tunnel) for recall after blind miss | VRF **5**, tunnel **2**; telemetry exported |
| `compound_overlap_20260719_1735` | 19 Jul | PE1×VRF overlap wave 1 | **6/6** compounds; lake rebuilt; **promote FAIL** (0.703 &lt; 0.717); tunnel blind **1/2** |
| `compound_overlap_w2_20260719_2045` | 19–20 Jul | Wave 2 — 4× each PE1+VRF | **12/12** compounds; **promote FAIL** (0.704 &lt; 0.717); tunnel blind **1/2** (VRF miss); BGP blind **1/2** (BGP miss, VRF hit) |
| `tier5_vrf_overlap_20260720_0252` | 20 Jul | **Tier 5**: `vrf_route_count` (FRR BGP table, station2) wired end-to-end; injector bug fixed (`vrf ADMIN`→`vrf-admin`); 2× each PE1+VRF | **6/6** compounds; exported `vrf_route_count` real signal (station2 0→4, mean 2.5; station1 flat 0 — confirms fix); **promote FAIL** (0.6965 &lt; bar 0.717, but beats honest same-paper champion 0.6949); **vrf_leakage exam F1 0.47→0.59**, bgp_route_flap F1 0.51→0.45 (collateral dip) |
| `tier5_vrf_consolidate_20260720_1418` | 20–21 Jul | Follow-up weighted toward tunnel+VRF / congestion+VRF, **skip bgp+VRF**, to consolidate the VRF gain without further diluting BGP — 4 tunnel + 4 congestion total (2 tunnel done pre-outage). Mid-run power outage killed the lab (not this host); resumed cleanly at the same `--run-id` after adding checkpoint/resume support to `deca_compound_overlap_campaign.py` (auto-detects completed compounds from the log, continues numbering, restores true campaign start for the Prom export window) — no lab state left dangling, `deca_diagnostic.sh` 8/8 post-recovery | **6/6** remaining compounds (2 tunnel + 4 congestion); **promote FAIL** (0.6948 &lt; bar 0.717, ties honest same-paper champion 0.6948 — flat, not regressed); **vrf_leakage exam F1 0.59→0.63** (keeps climbing) but **bgp_route_flap F1 0.45→0.35 (kept dropping despite skipping bgp+VRF compounds)**; live re-verify: control **0/0 clean**, tunnel+VRF blind **1/2** (VRF still drowned under tunnel, unchanged), BGP+VRF blind **0/2** (both legs missed — worse than wave 2's 1/2) |
| `bgp_flap_recall_20260721_0406` | 21 Jul | **Tier 5b seed**: standalone `bgp_route_flap` x6 (no VRF compound) — first real telemetry for the new live `bgp_flap_count` exporter (`connectionsDropped` was verified dead first — `clear bgp soft` doesn't reset the session; `messageStats.routeRefreshSent/Recv` does, +6/+3 over 3 live test clears). Existing lake had **zero** rows with this feature (exporter deployed after the last campaign's window closed — `rebuild_unified.py` only reads already-exported per-run CSVs, can't retroactively backfill a metric that wasn't being scraped) | **6/6** real runs (1 transient SSH timeout self-recovered, still logged); gate diagnostic (`deca_bgp_diagnose.py`) vs pre-feature baseline: `bgp_route_flap` mean gate p(anomaly) **0.516→0.542**, flagged@0.50 **46.6%→49.4%**, confusion-matrix recall **41.0%→43.8%** — real, consistent, small (only ~18% of the class's rows carry the new signal, rest are legacy NaN); **overall candidate macro-F1 0.6948→0.7110**, closest gap yet to the 0.717 bar (0.006); **promote still FAIL** but this is additive evidence, not a dead end — next bgp+VRF campaign should compound on top of this instead of starting from the fabricated-signal baseline |
| `tier5_bgp_vrf_focus_20260721_0618` | 21 Jul | **Dedicated bgp+VRF compound campaign**, 6× `bgp_route_flap`+`vrf_leakage` only (0 tunnel, 0 congestion this round) — banking real `bgp_flap_count` volume on top of the seed campaign, same playbook that worked for VRF two rounds ago ("give the underperforming class its own targeted volume instead of trying not to dilute it") | **6/6** compounds (1 transient SSH timeout on traffic-gen self-recovered, faults unaffected); `bgp_route_flap` lake rows 2,838→**3,378**; **promote FAIL** — candidate macro-F1 **0.7094** vs bar 0.7170, but gap narrowed from 0.0222 (last round) to **0.0076**, closest yet; `bgp_route_flap` exam F1 **0.35→0.41** (recovering, still short of the 0.45 peak from 2 rounds ago); `vrf_leakage` F1 **0.63→0.65** (kept climbing even with zero fresh non-BGP VRF volume this round); live re-verify: control **0/0 clean**, tunnel+VRF blind **1/2** (tunnel hit, VRF still silent-missed, unchanged pattern), BGP+VRF blind **1/2 detected but 0/2 correctly classed** (`vrf_leakage` triggered but mislabeled as `bgp_route_flap`, `bgp_route_flap` itself flagged nothing) — detection is improving faster than classification on this specific compound |
| `tier5_bgp_vrf_focus2_20260721_1159` | 21 Jul | **Second dedicated bgp+VRF round** (same design as prior: 6× `bgp_route_flap`+`vrf_leakage`, 0 tunnel/congestion) — testing whether the monotonic F1 trend (0.35→0.41) predicts a cheap gate clear with one more round of volume, per explicit user-approved sequencing (volume first, feature-interaction only if it stalls) | **6/6** compounds (1 more transient SSH blip, self-recovered); `bgp_route_flap` exam F1 **0.41→0.43** (kept climbing, hypothesis still holds at the per-class level); `vrf_leakage` F1 **0.65→0.65** (held steady, still no trade-off); but **aggregate candidate macro-F1 0.7094→0.7077** (flat-to-down, gap widened 0.0076→0.0093) and **BGP+VRF live blind regressed 1/2→0/2** (both legs missed this draw, vs. detected-but-mislabeled last round) — control and tunnel+VRF blinds unchanged (clean / 1/2 respectively); **promote FAIL**. Read: per-class exam F1 didn't plateau, but the number the gate actually judges did — two consecutive rounds of added BGP+VRF volume haven't moved the aggregate toward the bar, and the live single-draw blind got worse, not better. Closer to the pre-agreed "stall" condition than the "cheap win" condition, though both aggregate noise (random exam paper each run) and blind-test variance (n=2 events) mean this isn't conclusive on its own |
| *(no new campaign — feature engineering only)* | 21 Jul | **Baseline-relative (robust z-score) companion features**, per the pre-agreed stall trigger: since two rounds of bgp+VRF volume stalled the aggregate gate while per-class F1 kept climbing, pivoted to the feature-interaction lever instead of a third volume round. Added `{metric}{suffix}_z_slope/_z_rolling_std/_z_rolling_mean/_z_accel` to `engineer_features()` — same 4 stats as the existing absolute features, computed on a per-(run, metric) robust median/MAD-normalized series instead of raw value. No new lab data, existing lake, doubled feature count 56→112/114 | **Promotion gate PASS** — ran twice on different random exam papers. Dry run: `plain` (unchanged champion architecture) β=1.0, exam macro-F1 **0.7743** (not saved). Promotion run: `plain` scored 0.7637 on its own paper (the bar), `wm` (cluster-augmented booster) edged it by 0.0005 at **0.7642** and is the config actually **promoted** into `models/fault_classifier/` (previous classifier backed up to `fault_classifier.bak_20260721_170939`) — the plain/wm gap is noise, not an architecture win; the real driver is the feature change, confirmed by `plain` alone jumping ~0.71→0.76+ on two independent draws. Per-class F1 for the **promoted** `wm` config: `bgp_route_flap` **0.43→0.48**, `vrf_leakage` **0.65→0.75**. Temporal loom re-score on chronological tail: raw-frame macro-F1 **0.8233** (`bgp_route_flap` F1 0.759, `vrf_leakage` F1 0.878), advisory tier macro-F1 0.8923. Live re-verify (against the promoted `wm` model): control **0/2 clean**; tunnel+VRF blind **1/2** (tunnel hit, VRF still drowned — unchanged, expected, this round didn't target that leg); BGP+VRF blind **1/2 detected, and this time correctly classed** (`vrf_leakage` labeled correctly, not confused with `bgp_route_flap` as in the prior round) — `bgp_route_flap` leg itself still missed, but the cross-class confusion problem flagged after the second volume round is gone. Two full rounds of dedicated campaign volume moved macro-F1 by ~+0.015 total; this single feature change moved it by **+0.055–0.065** using zero new lab time — confirms the stall diagnosis was right: separable in volume terms, not in feature terms |

Drivers: `scripts/deca_fault_campaign.py`, `deca_circumstance_campaign.py`, `deca_specificity_data_campaign.py`, `deca_vrf_recall_campaign.py`, `deca_compound_overlap_campaign.py`.  
Script backups: `scripts/backup/`.

---

## What each recent campaign changed

| Campaign | Intended effect | What happened next |
| --- | --- | --- |
| `spec_data_*` | Teach aborted onsets = healthy; keep detection | Exam v1 **PASS**; blind detection **3/4** (missed PE2 VRF) — precision/recall trade |
| `vrf_recall_*` | Pull VRF recall without new NM flood | Trust re-check **PASS**; forced compound later: VRF **raised as tunnel**, not silent miss — class confusion still open |
| `compound_overlap_20260719_1735` | Teach simultaneous PE1+VRF windows | Lake +450 VRF rows; candidate exam **0.703** &lt; bar **0.717** — **models unchanged**; tunnel+VRF blind still **1/2** (VRF silent miss on station2) |
| `tier5_vrf_overlap_20260720_0252` | Give the model an orthogonal, station2-local control-plane feature the traffic drowning can't touch | Lake +48 features (was 40); `vrf_leakage` exam F1 **+0.12** (0.47→0.59) — the hypothesis holds on the exam paper; but macro-F1 still **0.6965 &lt; 0.717 floor** (candidate does edge the honest same-paper champion 0.6949) and `bgp_route_flap` F1 dipped **0.51→0.45**; **models unchanged**, live blinds not yet re-run against this candidate since it wasn't promoted |
| `tier5_vrf_consolidate_20260720_1418` | Consolidate the VRF gain (more tunnel+VRF, congestion+VRF) while *skipping* bgp+VRF entirely, hoping BGP recovers with no new dilution | `vrf_leakage` kept climbing (**0.59→0.63**) but `bgp_route_flap` **kept dropping anyway (0.45→0.35)** even with zero new bgp+VRF compounds — the earlier dip wasn't purely a dilution-by-volume effect, something about the wider VRF-feature lake is itself pulling BGP recall down; macro-F1 candidate **0.6948 ≈ 0.6948 champion** (flat, no regression, no gain); **models unchanged** (gate FAIL); live re-verify shows BGP+VRF compound blind got *worse* (1/2 → 0/2) — this needs a dedicated BGP-focused round before another VRF push, not more VRF volume |
| `bgp_flap_recall_20260721_0406` | Confirm the new live `bgp_flap_count` signal (routeRefresh churn) is real before spending more lab time on BGP | Gate separability up (p(anomaly) 0.516→0.542) and confusion-matrix recall up (41.0%→43.8%) on the ~18% of rows carrying the new feature; macro-F1 candidate jumped **0.6948→0.7110**, closest gap yet to the bar — confirms the fabricated `bgp_update_rate` signal was the real bottleneck, not a weighting artifact; **models unchanged** (gate still FAIL) |
| `tier5_bgp_vrf_focus_20260721_0618` | Give `bgp_route_flap` its own dedicated compound volume (mirroring the VRF playbook), now compounding on top of the real `bgp_flap_count` signal instead of the fabricated one | `bgp_route_flap` F1 recovered **0.35→0.41**, `vrf_leakage` kept climbing anyway (**0.63→0.65**) — no BGP-vs-VRF trade-off this round, both moved together; macro-F1 candidate **0.7094**, narrowest miss yet (bar 0.7170, gap 0.0076); **models unchanged** (gate FAIL); live BGP+VRF blind shows detection improving ahead of classification — one leg fires but the model currently mislabels `vrf_leakage` as `bgp_route_flap` inside the compound, a class-confusion problem rather than a miss problem |

---

## Rebuild note (post `vrf_recall`)

- Features ~48k rows; `vrf_leakage` labels ~2220  
- Promoted wm Macro-F1 **0.717**; soft sticky **0.803**
- Validation section checked duration spread (“not a collapsed-timestamp pattern”) — VRF timestamp bug lesson internalized.

---

## Script note (`deca_vrf_recall_campaign.py`)

Builds a fixed schedule up front; **no retry** if a single injection fails mid-campaign — that slot is permanently lost. Did not bite on `vrf_recall_20260718_1752` (5/5), but an SSH hiccup on a future campaign would quietly burn quota.

---

## Update rule

After every new `data/rpi-net/runs/<id>/`: add one row here (quotas + whether Prom CSV exported). Keep `fault_injection_log.csv` + `network_telemetry.csv` in the run dir.
