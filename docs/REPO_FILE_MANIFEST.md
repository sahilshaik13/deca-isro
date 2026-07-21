# DECA-ISRO — Repository File & Folder Manifest

**Purpose of this document:** a complete inventory of every meaningful file and folder in this repository, with a plain-language definition of what it contains — written to be handed to an external validator/judge who needs to understand the project's structure without reading every file.

**Scope note:** this covers the actual project deliverable. It excludes vendored/generated content that carries no project-specific information: `.git/`, `.venv/` (Python virtualenv), `.tools/` (a locally-downloaded Node.js binary + its own `node_modules`, used only to run the frontend), `__pycache__/` (compiled `.pyc` cache), and `node_modules/` inside `deca-frontend/`. `deca-frontend/` and `deca-backend/` themselves are separate local-only apps (demo UI + a chat/runbook backend) — the project's own `.gitignore` marks them **"not part of the ISRO data-gen share"**; they're described briefly at the end for completeness but are not the ML/data deliverable this manifest is really about.

Everything below is organized top-down: top-level files, then one section per top-level folder.

---

## Top-level files

| Path | What it is |
| --- | --- |
| `README.md` | The handover entrypoint. Explains what the project produces (a trainable feature matrix + model stack fusing physical Raspberry-Pi lab fault injection with public internet telemetry), links every doc, shows the repo layout, the quick-start commands to regenerate the data lake and retrain, the unified label vocabulary, and the lab topology summary. Start here. |
| `.gitignore` | Excludes: the two local apps (`deca-frontend/`, `deca-backend/`), Python/venv artifacts, large re-downloadable BGP MRT archives, backup files (`*.bak*`), editor files, and in-progress run logs. Everything else in this manifest is tracked or trackable. |

---

## `scripts/` — every data-generation, training, and ops tool

This is the code deliverable. **`docs/SCRIPTS.md` is the maintained, detailed catalog of the original core pipeline scripts** (purpose/command/output tables) — treat it as the canonical reference for those; this section covers the same scripts plus everything added afterward (blind-testing harness, compound-overlap campaigns, diagnostics, recalibration) that isn't yet folded into that doc.

### Shared

| File | What it is |
| --- | --- |
| `_paths.py` | Single source of truth for repo-rooted paths (`DATA_DIR`, `PROCESSED_DIR`, `RPI_NET_DIR`, `MODELS_DIR`, etc.). Every other script imports from this instead of hardcoding paths. |

### Public data lake (fetch/build the "context" half of the lake)

| File | What it is |
| --- | --- |
| `fetch_public_data.py` | Sequential orchestrator that runs all the public-data pulls below in order (keeps RAM low). |
| `routeviews.py` | Downloads RouteViews BGP MRT update dumps. |
| `riperis.py` | Downloads RIPE RIS RRC BGP MRT update dumps (second BGP collector). |
| `parse_bgp.py` | Memory-safe parser: MRT archives → minute-level BGP update-rate series. |
| `ripe_atlas.py` | RIPE Atlas ping RTT/loss — baseline snapshot or full chunked historical pull. |
| `bgpstream.py` | ASN BGP outage/routing event labels via IODA (paginated) — kept as provenance, not applied as row labels (date-range mismatch with lab telemetry). |
| `ioda.py` | IODA ASN outage labels — same provenance role as `bgpstream.py`. |
| `ioda_client.py` | Shared HTTP client (pagination) used by `bgpstream.py`/`ioda.py`. Not run directly. |
| `cisco_scraper.py` | Scrapes Cisco DevNet's public "Always-On" Cat8000v sandbox interface counters for an optional public magnitude sample. Uses Cisco's own published sandbox demo credentials (a public, intentionally-open test device, not a real customer system). |

### Lab fault campaign (the only source of supervised fault labels)

| File | What it is |
| --- | --- |
| `deca_fault_campaign.py` | The core quota-driven fault injector: SSHes into the Pi lab and Prometheus to inject/clear `congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage` on a schedule, logging ground truth throughout. Nearly every later campaign script reuses its injector functions. Also holds `PROM_QUERIES` (the PromQL for every scraped metric, including the Tier 5 `vrf_route_count` / `bgp_flap_count` additions). |
| `deca_circumstance_campaign.py` | Temporal-Loom "circumstance" experiment: captures run-up → breach → recovery phases per event, so the model can learn a forming fault's precursor pattern, not just the breach frame itself. |
| `deca_specificity_data_campaign.py` | Generates targeted near-miss / confusion-triangle data (aborted onsets that must stay labeled `healthy`) to fix false-positive specificity issues found in exam testing. |
| `deca_vrf_recall_campaign.py` | Lean, standalone `vrf_leakage`-only seed campaign (no compound faults) — used to restore VRF detection recall without diluting it with near-miss volume. |
| `deca_bgp_flap_recall_campaign.py` | Same pattern as above but for `bgp_route_flap` — the seed campaign that generated the first real telemetry for the new live `bgp_flap_count` feature (Tier 5b). |
| `deca_compound_overlap_campaign.py` | Generates **simultaneous** PE1+PE2 fault windows (e.g. `tunnel_degradation`+`vrf_leakage` at once) — teaches the model compound/overlapping fault signatures. Supports weighted scheduling (`--counts`) and checkpoint/resume (survives interruptions like power outages). |
| `deca_compound_overlap_pipeline.sh` | End-to-end wrapper: run the compound-overlap campaign → rebuild the lake → retrain/promote → re-score with the temporal loom → re-verify against the trust/blind suites, in one call. |
| `deca_train_circumstance.py` | Trains the Temporal Loom's "existence" head on the circumstance labels above (self-defers if the lake has no circumstance data yet). |

### Unify / train / evaluate

| File | What it is |
| --- | --- |
| `rebuild_unified.py` | The fusion step: turns raw lab-campaign CSVs + curated public CSVs into `data/processed/deca_unified_{raw,dataset}.parquet` with engineered rolling features (slope/rolling-std/rolling-mean/accel at a 10-min and 2-min window per metric) **and** their baseline-relative z-score companions (`_z_slope` etc., added Tier 5c — a per-`(run, metric)` robust median/MAD normalization so features express "deviation from this host's own normal" rather than a fixed absolute magnitude). This is the single most load-bearing script in the repo — nearly everything downstream reads its output. |
| `deca_school_exam_train.py` | The training engine ("Mode A School Exam"): draws a fresh stratified exam paper each run, sweeps a rare-class weighting parameter (β) per candidate head family (`plain`/`wm`/`moe`), and gates promotion against the current champion's score on the same paper. Also owns the binary anomaly gate (`build_gate`), the multiclass head builder (`build_full_head`), threshold tuning (`tune_thresholds`), and the `_align_to_estimator_features` schema-drift shim so older/newer feature sets don't crash scoring. |
| `deca_mlops_orchestrator.py` | Automates the teach→test→examine→score→improve loop: repeatedly calls the exam trainer with a fresh random paper until it clears the promotion gate or hits `--max-cycles`. No human judgment in the loop. |
| `deca_model_playground.py` | Scores every model in the stack (Isolation Forest, XGBoost, LSTM, 3× Prophet, topology) on one shared stratified holdout, for side-by-side comparison — does not retrain or promote anything. |
| `deca_model_experts.py` | Defines the two non-champion head architectures: `wm` (adds a KMeans cluster layer + regularization) and `moe` (cluster layer + one specialist model per fault class, blended by a stacked meta-learner). |
| `deca_retrain_companions.py` | Retrains everything *except* the promoted fault classifier (Isolation Forest+Platt calibrator, 3× Prophet, LSTM, topology graph) after a new campaign changes the lake's distribution. |
| `deca_inference.py` | The Temporal Loom's live persistence/hysteresis logic: per-class entry/exit frame counters so a single noisy frame can't flip a declaration; two-tier advisory/confirmed states. |
| `deca_score_temporal.py` | Runs the trained classifier + loom over a chronological (non-shuffled) telemetry stream to measure real detection lag and false-start behavior — the "does it work in time-order, not just on a shuffled exam" check. |
| `deca_recalibrate.py` | **Tier A onboarding tool**: re-runs only the threshold grid search (`tune_thresholds`) against a new labeled sample, patching `gate_thr`/`class_thr` in the already-fitted model — no tree is ever refit. This is the "recalibrate a new network in hours, not weeks" mechanism referenced in the ISRO portability docs. Dry-run by default; `--apply` backs up and writes. |
| `deca_bgp_diagnose.py` | One-off diagnostic (not part of the regular pipeline): instruments the anomaly gate's per-class recall and the full confusion matrix to distinguish a class-weighting artifact from a genuine data/feature-separability problem. Built to root-cause the `bgp_route_flap` F1 collapse; the finding (fabricated signal, no real traffic perturbation) directly motivated the new `bgp_flap_count` feature. |
| `deca_compound_flip_diagnostic.py` | At the moment a compound fault's "hit" leg gets confirmed, checks what score the "miss" leg had — used to distinguish "never detected" from "detected but outscored." |
| `deca_vrf_tunnel_diagnostic.py` | Offline slice answering: is `vrf_leakage` vs `tunnel_degradation` confusion a model problem or a lab-topology problem (i.e. is the VRF signal physically drowned by the tunnel fault in this specific lab wiring)? |
| `deca_multilabel_falsification.py` | Deliberately tests (and falsifies) a multi-label/decoupled-sigmoid architecture on compound-overlap data before committing to Tier 5 — the "0/25 pass rate proves the physical signal is genuinely drowned, not an architecture bug" experiment. |
| `deca_compound_series_rollup.py` | Aggregates a batch of compound-fault results (from `/tmp/deca_compound_results.jsonl`) into a single rollup markdown. |
| `deca_vrf_cleanup_admin_stub.py` | One-off repair script: removes a stray orphaned `router bgp 65001 vrf ADMIN` FRR config stanza left on `station2` by the (since-fixed) buggy VRF-leakage injector. Idempotent. |

### Blind-testing harness (the "does it work live, with nobody grading it in advance" suite)

| File | What it is |
| --- | --- |
| `deca_live_common.py` | Shared helpers for the whole blind-test harness: Prometheus queries (`PROM_QUERIES`), feature windowing, model loading. |
| `deca_live_operator.py` | "The model flying blind" — polls live Prometheus telemetry, runs it through the promoted classifier + loom, and declares faults in real time with no foreknowledge of what's about to be injected. |
| `deca_blind_chaos.py` | The adversary: a scheduler that injects real faults / near-misses on its own randomized timeline while the operator above is running, then seals the ground truth so it can't leak into grading until after the fact. |
| `deca_blind_scorecard.py` | Opens the sealed ground truth after a run and grades the operator's declarations against it. |
| `deca_blind_aggregate.py` | Combines multiple graded blind-test runs into a trustworthy aggregate detection-rate range (single-run n is too small to trust alone). |
| `deca_blind_exam_report.py` | Grades the deterministic specificity-exam playlists (see `scripts/playlists/`) — the calm/near-miss false-positive check, phase-aware. |
| `deca_blind_ensemble_head.py` / `deca_blind_ensemble_eval.py` | Train + honestly evaluate whether the `wm` head adds real second-opinion value in an ensemble blind-test context, or is just an echo of the champion. |
| `deca_blind_test.sh` | Orchestrates a full hands-off blind run: arms the operator + chaos scheduler together, waits for chaos to finish, stops the operator, grades it. |
| `deca_blind_vrfcheck.sh` | A VRF-recall-focused live check variant: forces every real fault slot to include the PE2 VRF leg. |
| `deca_blind_after_vrf.sh` | Post–VRF-recall-campaign adversarial detection re-check. |
| `deca_ultimate_60_60.sh` | The largest single harness run: 60 min adversarial blind + 60 min all-healthy control back-to-back, archived and aggregated automatically. |
| `deca_durability_then_vrf.sh` | Runs a durability/trust exam, then chains into a lean VRF recall campaign. |
| `deca_trust_recheck_after_vrf.sh` | Re-runs the specificity/trust exam after a VRF-focused promotion, to confirm it didn't reopen cry-wolf false positives. |
| `deca_post_compound_chain.sh` | Waits for a compound-fault series to finish, rolls it up, then runs an isolated VRF proof blind. |
| `deca_bgp_recheck_wait.sh` | Waits for a BGP+VRF compound re-check campaign to finish, then verifies gates and archives/grades it. |

### Station operations (shell — talk to the physical Pi lab)

| File | What it is |
| --- | --- |
| `deca_deploy_stations.sh` | Full plug-and-play restore of the lab from cold boot: CE network-namespace units, FRR/strongSwan service ordering, watchdog, VRF static safety-net routes, hostnames, Prometheus ownership check. |
| `deca_heal_telemetry.sh` | Lighter touch than the above — restarts just the namespace/FRR/IPsec/Telegraf services when telemetry flakes after a partial boot. |
| `deca_fix_prom_vpn.sh` | Targeted fix for two specific recurring failures: a poisoned Prometheus TSDB (`out of bounds` errors) and missing VRF underlay static routes when the VPNv4 table has 0 prefixes. |
| `deca_debug_vpn_prom.sh` | Read-only-ish deep diagnostic that precedes the fix script above — checks clock skew, Telegraf timestamps, VPN reachability, BGP/VRF state. |

### `scripts/backup/` — frozen pre-edit snapshots

| File | What it is |
| --- | --- |
| `README.md` | Explains the backup convention: dated `.bak_*` snapshots of campaign driver scripts taken before risky injector edits, so a regression can be reverted with a single `cp`. |
| `deca_fault_campaign.py.bak_pre_spec_20260718`, `deca_fault_campaign.py.bak_working_20260718`, `deca_circumstance_campaign.py.bak_20260715` | The actual frozen copies described by the README. |

### `scripts/playlists/`

| File | What it is |
| --- | --- |
| `specificity_exam_v1.json`, `specificity_exam_v2.json` | Deterministic phase playlists (calm stretches + fixed-timing near-miss baits, no real faults) used by the specificity/cry-wolf exam harness. v2 exists as an "unseen" variant to check the model wasn't just overfit to v1's exact timing. |

---

## `lab/` — laptop-side ops for the physical Pi cluster (untracked working scripts)

Day-to-day helpers that live on the operator's laptop, separate from `scripts/` because they're lab-hardware ops rather than data-pipeline code (see `lab/README.md`).

| File | What it is |
| --- | --- |
| `README.md` | Explains why these live in-repo (reproducibility) instead of scattered in `$HOME`. |
| `deca-deploy.sh` | The authoritative, most up-to-date plug-and-play deploy script (superset of `scripts/deca_deploy_stations.sh`) — also installs the Tier 5 (`vrf_route_count`) and Tier 5b (`bgp_flap_count`) Telegraf exporters and their sudoers rules on `station1`/`station2`. |
| `deca-heal-telemetry.sh` | Quick heal for `[7/8]` VPN ping / `[8/8]` Telegraf scrape failures after a partial boot. |
| `deca-vrf-route-count.sh` | The Tier 5 exporter itself: queries FRR's BGP table for a VRF (via `vtysh`) and emits an Influx line-protocol metric for Telegraf's `inputs.exec`. |
| `deca-bgp-flap-count.sh` | The Tier 5b exporter: sums FRR's `routeRefreshSent`/`routeRefreshRecv` neighbor counters (the live signal that actually reacts to `clear bgp soft`, unlike `connectionsDropped`) into a Telegraf metric. |
| `deca_diagnostic.sh` | Interactive master diagnostic — prompts once for the station sudo password, then checks Layer-3 reachability, services, VRF, VPN, and telemetry end to end (`[1/8]`–`[8/8]`). |
| `check_stations.sh` | Post-boot health check: SSHes into all three stations, checks uptime/IP, and confirms FRR/strongSwan/chrony/`deca-ns` are enabled. |
| `check_step7.sh` | Focused check on the CE-A↔CE-B data plane specifically (namespace + veth existence). |
| `trace_step7.sh` | Runs a `tcpdump` inside the CE-A namespace while triggering a ping, to trace exactly where step-7 data-plane traffic dies. |
| `apply_boot_fix.sh` | Prompts for the station password once, then applies a boot-ordering fix. |
| `run_traffic.sh` | Infinite loop: restarts an `iperf3` server on `station2` and blasts 60s of traffic from `station1` — background traffic generator (explicitly *not* run during real campaigns per the top-level README's design notes, since it fights the campaign's own traffic baseline). |
| `startupppp` | Enables the FRR/strongSwan/Telegraf/pmacctd/Prometheus systemd services across all three stations + the laptop on boot. (Typo'd filename, functional script — not renamed to avoid breaking any existing muscle-memory/aliases.) |
| `forwardss` | Fixes kernel return-traffic routing for CE network namespaces (forces the veth interface to own return traffic). |
| `link_home.sh` | Symlinks `~/deca_diagnostic.sh` etc. back into this folder, so any older doc/muscle-memory reference to the `$HOME` copies still resolves. |
| `cisco_scraper.py` | Local working copy of `scripts/cisco_scraper.py` (Cisco DevNet sandbox scrape) — kept here for on-the-lab-laptop convenience. |

---

## `docs/` — all documentation

### Core reference docs (read these for the pipeline itself)

| File | What it is |
| --- | --- |
| `DATA_GEN.md` | The data-lake reproduction recipe — which scripts to run, in what order, from a clean clone. |
| `SCRIPTS.md` | Canonical, detailed catalog (purpose/use-case/command/output tables) of the original core pipeline scripts. See `scripts/` section above for the additions made since. |
| `MODELS.md` | Catalog of every artifact under `models/` — what trained it, what it scores, where its plots live. |
| `DATA_SAMPLE.md` | Inventory of every curated data file with sample rows/columns — the "what's actually in each CSV/parquet" reference. |
| `STATION_NETWORK_SETUP.md` | The physical/logical lab network reference: Pi CE/PE systemd units, IPsec config, VRF setup, Prometheus scrape config. |
| `what_is_this.md` | Top-level technical architecture explainer — the actual ML blueprint (binary XGBoost anomaly gate → multiclass XGBoost head → temporal-loom hysteresis layer), rewritten 21 Jul to replace an earlier, outdated autoencoder-based description. |
| `DECA_Full_Pipeline.md` | Earlier end-to-end pipeline write-up (predates some of the above; kept for history/context). |
| `DECA_Model_Development_Blueprint.md` | The theoretical/mathematical blueprint — formulas, ROI framing, and the applied results from the first full training run. |
| `DECA_ROI_TIERS.md` | The living "prioritized escalation plan" doc — Tiers 1 through 5c, each tier's rationale, what was built, and the measured before/after result. This is the most continuously-updated results narrative in the repo. |
| `DECA_MLOps_Continuous_Learning_Pipeline.md` | Describes the "teach→test→examine→score→improve" training methodology (`deca_mlops_orchestrator.py`) as opposed to one-shot manual retraining. |
| `DECA_TEMPORAL_LOOM.md` | Design + measured sweeps for the sticky-hysteresis persistence layer that sits on top of the frame-level classifier (per-class entry/exit counters, advisory vs. confirmed tiers). |
| `DECA_SPECIFICITY_EXAM.md` | Design + runbook for the deterministic calm/near-miss false-positive exam (the "cry-wolf" trust bar). |
| `DECA_BLIND_TEST.md` | Runbook for the adversarial blind live-network test harness (chaos scheduler + live operator + scorecard). |
| `DECA_TEST_SCORES.md` | Score timeline: initial models → School Exam → playground, in one place. |
| `DECA_RESULTS_OVERVIEW.md` / `DECA_WHITE_PAPER.md` | Higher-level overview / white-paper drafts synthesizing the results docs into a narrative. |
| `TIER5_VRF_ROUTE_COUNT.md` | The complete end-to-end spec for the Tier 5 `vrf_route_count` feature — exporter → Telegraf → Prometheus → `rebuild_unified.py`, including the phantom-VRF bug discovery and fix. |
| `ISRO_PORTABILITY.md` | The portability/deployment pitch for ISRO — what actually transfers to a new network (fault taxonomy, externalized config, calibration tooling) vs. what explicitly doesn't yet (trained weights, proven cross-network transfer). |
| `CALIBRATION_CAMPAIGN_SPEC.md` | The concrete onboarding procedure referenced by the portability doc: Tier A (threshold-only recalibration, `deca_recalibrate.py`) vs. Tier B (lightweight retrain), plus the labeled-sample generation step ISRO itself would need to run. |
| `REPO_FILE_MANIFEST.md` | This document. |

### `docs/results/` — the results index

| File | What it is |
| --- | --- |
| `README.md` | Points to the **three** canonical cumulative scoreboards (below) and warns that everything else under `results/archive/` is historical detail, not current truth. |
| `archive/README.md` | Explains the archive is frozen history; new results go into the CUMULATIVE docs, not new files here. |
| `archive/*.md` (12 files: `BLIND_TEST_*` ×8, `SPECIFICITY_*` ×3, `VRF_RECALL_CAMPAIGN_20260718.md`) | Individual per-run write-ups that predate the CUMULATIVE-doc convention — kept for detail/history on specific dated runs. |

**The three canonical, continuously-updated scoreboards** (referenced constantly from the docs above, physically located under `data/`, not `docs/`):
- `data/rpi-net/blind-tests/CUMULATIVE.md` — adversarial detection blind-test results.
- `data/rpi-net/live/CUMULATIVE.md` — specificity exams + all-healthy control results (trust/cry-wolf, *not* detection).
- `data/rpi-net/runs/CUMULATIVE.md` — data-generation campaign results (what fed training, and why).

### `docs/assets/` and loose images

| Path | What it is |
| --- | --- |
| `assets/models/*.png` (8 files) | Plots referenced by `MODELS.md`: per-class F1, precision/recall, feature attribution, topology diagram, fault-signature strip charts (one per fault class), scorecard. |
| `assets/scores/*.png` (6 files) | Plots referenced by `DECA_TEST_SCORES.md`: per-class F1 across training stages, initial vs. playground model comparisons. |
| `fault_classifier_stages.png`, `per_fault_f1_line.png` | Loose copies of two of the above, referenced directly from some docs at the `docs/` root. |

### Non-markdown docs

| File | What it is |
| --- | --- |
| `DECA SETUP.pdf` | Lab physical setup PDF (hardware wiring / initial bring-up), referenced from the top-level README. |
| `[Pub] ISRO BAH 2026 _ Idea Submission Template.pdf` | The official hackathon idea-submission template document. |

---

## `data/` — the data lake

### `data/raw/public/` — curated public-internet context data

| File | What it is |
| --- | --- |
| `route-views2_updates.*.bz2`, `route-views.linx_updates.*.bz2` | Raw RouteViews BGP MRT update dumps (multiple 6-hour chunks) — gitignored (re-fetchable, large), input to `parse_bgp.py`. |
| `rrc00_updates.*.gz`, `rrc11_updates.*.gz` | Same, from RIPE RIS (gitignored, if present locally). |
| `bgp_update_rates_full.csv` | Parsed minute-level BGP update-rate series (output of `parse_bgp.py`, tracked — this derived CSV stays even though the raw MRTs don't). |
| `bgp_routing_labels.csv` | IODA BGP outage event labels — provenance only, not used as row labels (date mismatch with lab telemetry window). |
| `ioda_outage_labels.csv` | IODA ASN outage labels — same provenance role. |
| `ripe_atlas_ping_baseline.csv` | RIPE Atlas baseline ping RTT/loss snapshot. |
| `ripe_atlas_ping_sampled.csv` | The curated, trimmed subset of the full historical Atlas pull actually used in the lake (kept public:lab ratio ~3:1 instead of hundreds:1). |
| `cisco_sandbox_sample.csv` | Output of `cisco_scraper.py` — public Cisco DevNet sandbox interface counters. |
| `mawi_sample.csv` | Manually-copied 15-minute traffic sample from the public MAWI Samplepoint-F page (no automated pull — page doesn't allow it) — magnitude anchor only, not a trajectory. |

### `data/processed/` — the fused, trainable output

| File | What it is |
| --- | --- |
| `deca_unified_raw.parquet` | Long-form fused telemetry (lab + public) before feature engineering. |
| `deca_unified_dataset.parquet` | **The canonical training table** — engineered features (absolute + Tier 5c z-score companions) + `unified_label` per row. Everything trains on this file. |
| `deca_unified_fault_log.csv` | Flattened fault-injection ground truth log across all merged campaign runs. |
| `public_outage_labels_provenance.csv` | Inventory of the IODA/BGP outage-label rows (provenance record, not fed into training as labels). |
| `bgp_parse_checkpoint.json` | Resume checkpoint for `parse_bgp.py`'s MRT parsing. |
| `bgp_update_rates_full.parquet` | Parquet copy of the parsed BGP rate series. |
| `*.bak_pre_rebuild` (on the two main parquets) | One-generation-back safety copies, auto-taken before a rebuild. |

### `data/rpi-net/runs/` — raw lab fault-campaign output (one folder per campaign)

Each run folder (e.g. `tier5_bgp_vrf_focus_20260721_0618/`, `vrf_recall_20260718_1752/`, `compound_overlap_20260719_1735/`, `bgp_flap_recall_20260721_0406/`, `20260714_165648_tier6_x10/`, `20260715_191519_circ_v2/`, `spec_data_20260717_2352/`, and others — 12 total campaign runs to date) contains the **same file set** by convention, produced by whichever campaign script (`deca_fault_campaign.py`, `deca_compound_overlap_campaign.py`, `deca_vrf_recall_campaign.py`, `deca_bgp_flap_recall_campaign.py`, `deca_specificity_data_campaign.py`, `deca_circumstance_campaign.py`) generated it:

| File (inside each run folder) | What it is |
| --- | --- |
| `campaign_run.log` | Full console/timing log of that campaign's execution. |
| `fault_injection_log.csv` | Ground truth: exactly when each fault was injected/cleared, and its type. |
| `network_telemetry.csv` | Raw Prometheus-scraped telemetry pulled at the end of the run, over the full campaign window. |
| `network_campaign_export.csv` | Telemetry pivoted wide + joined against the fault log — the per-run input `rebuild_unified.py` actually reads. |
| `compound_overlap_state.json` (compound-overlap runs only) | Resume checkpoint: which compound types/counts are already done, and the original campaign start time (for the Prometheus export window) — added specifically to survive interruptions like a power outage mid-campaign. |
| `bgp_update_samples.csv` (some runs) | Raw BGP-side metric samples captured alongside the main telemetry pull. |
| `circumstance_log.csv` (circumstance runs only) | Event-phase ground truth (`circumstance_start`/`breach_time`/`recovery_time`) for the run-up→breach→recovery labeling. |

Also at this level: `CUMULATIVE.md` (the canonical, continuously-updated write-up of every campaign's rationale and result — see `docs/results/README.md`), a couple of orchestrator/pipeline `.log` files from wrapper scripts, and `archive/20260713_184356/` (one older campaign's raw logs, kept but superseded by the current lake).

### `data/rpi-net/live/` — live blind-test harness working directory

Each subfolder (42 total, named things like `blind_20260718_2219_60m/`, `specificity_exam_v1_20260717_1022/`, `control_fp_check2/`, `blind_baseline_feature_bgp_20260721_2321_40m/`) is one run of the live operator + chaos/playlist harness, written in real time. Typical contents per folder: `chaos_run.log` / `operator_feed.log` (what the adversary did / what the model declared, live), `fault_injection_log.csv`, `bgp_update_samples.csv`, `declarations.jsonl` (the model's timestamped fault declarations), `ground_truth.sealed.jsonl` (the adversary's schedule, sealed until grading), `scorecard.json` (the graded result), `run_meta.json`. Some folders are specificity-exam playlist runs instead of adversarial-chaos runs (no `ground_truth.sealed.jsonl`/`declarations.jsonl`, since those use the deterministic playlist grader instead). `CUMULATIVE.md` at this level is the canonical trust/specificity scoreboard (exams + all-healthy controls — **not** detection).

### `data/rpi-net/blind-tests/` — graded blind-test archive

`README.md` describes this as the curated archive of **graded** blind-test artifacts (a subset of what accumulates in `live/`), with its own `CUMULATIVE.md` as the canonical adversarial-detection scoreboard, plus `aggregate_*.json` files (multi-run trustworthy-range aggregates from `deca_blind_aggregate.py`).

---

## `models/` — every trained artifact

| Path | What it is |
| --- | --- |
| `manifest.json` | The training-run manifest: row counts by source, class counts, the full engineered feature-column list — the record of exactly what a given promoted model was trained on. |
| `fault_classifier/` | **The currently active, promoted model** — `fault_classifier_xgb.pkl` (gate + multiclass head bundle), `label_encoder.pkl`, `decision_thresholds.json` (externalized `gate_thr` / per-class `class_thr` / loom hysteresis config — the "config, not code" onboarding mechanism). |
| `fault_classifier.bak_*/` (8 dated folders) | Pre-promotion backups of the above, one per promotion event — standard practice before every swap, so a regression can be reverted instantly. |
| `isolation_forest/` | The unsupervised anomaly companion model: `isolation_forest.pkl`, its `feature_scaler.pkl`, and a Platt `confidence_calibrator.pkl`. |
| `lstm/` | Sequence model companion: `fault_lstm_v1.keras` + `lstm_scaler.pkl`. |
| `prophet_bgp_update_rate/`, `prophet_ifInOctets/`, `prophet_jitter_ms/` | Three per-metric Prophet time-series forecasters (one pkl each) used as companion baseline-deviation signals. |
| `topology/` | `topology_graph.json`/`.pkl` — the network topology graph used for the (currently off-by-default) neighbor-agreement gate in the temporal loom. |
| `circumstance/` | `circumstance_xgb.pkl` + `metrics.json` — the Temporal Loom's "existence" head trained on circumstance/run-up labels. |
| `school_exam/` | Training-run artifacts from `deca_school_exam_train.py`/`deca_mlops_orchestrator.py`: `latest_exam.json`, `weight_sweep.csv` (per-family β sweep results), `seed_report.{json,md}` (repeated-holdout spread), `orchestrator_latest.json`/`orchestrator_history.jsonl`, and assorted named `.log` files from specific historical training runs (`multiscale_promote.log`, `newlake_seed42.log`, etc.). |
| `playground/` | Output of `deca_model_playground.py`: `scoreboard.md`/`.csv` and `latest_playground.json` — the side-by-side comparison of every model on one shared holdout. |
| `scoreboard_per_class.csv`, `scoreboard_summary.csv` | Top-level scoreboard exports (per-class and summary) from an evaluation run. |
| `notebook_results_latest.json` | Latest results snapshot written by the training notebook. |
| `temporal_persist_score.json` / `temporal_persist_run.log` | Output + log of `deca_score_temporal.py` — the chronological-stream loom evaluation (raw vs. persistent vs. advisory scores, lead time, etc.). |
| `companions_retrain.json` / `companions_retrain.log` | Output + log of `deca_retrain_companions.py`. |
| `multilabel_falsification_report.json` | The falsification test result for the (rejected) multi-label/decoupled-sigmoid architecture. |

---

## `notebook/` — the training notebook

| File | What it is |
| --- | --- |
| `DECA_Model_Training.ipynb` | The interactive training notebook: builds and evaluates the full model stack (IF+Platt, XGBoost gate+head, Prophet, LSTM, topology) against `data/processed/deca_unified_dataset.parquet`, with inline stage plots. |
| `.ipynb_checkpoints/DECA_Model_Training-checkpoint.ipynb` | Jupyter's automatic checkpoint copy of the above. |
| `figures/fault_behaviour/*.png` (5 files) | Per-fault-class telemetry "strip chart" figures (one per fault type) + a `cheat_sheet.png`, generated by the notebook to visually show each fault's signature. |

---

## `obsidian/` — architecture diagram vault

Not documentation prose — a small Obsidian vault meant to be opened in Cursor's Markdown/Obsidian preview to render embedded diagrams.

| File | What it is |
| --- | --- |
| `Home.md` | Vault entry note. |
| `DECA_Model_Architectures.md` | Diagrams of the IF / XGBoost / LSTM / Prophet / topology model architectures. |
| `DECA_Training_Architecture.md` | Diagram of the school-exam / orchestrator training loop. |
| `.obsidian/*.json` | Obsidian app config (appearance, enabled core plugins, community plugins list, workspace layout) — editor settings, not project content. |
| `.obsidian/plugins/cursor-integration/` | The Cursor↔Obsidian integration plugin (`main.js`/`manifest.json`) that enables the preview rendering above. |

---

## Out of scope for this deliverable (present on disk, gitignored)

| Path | What it is |
| --- | --- |
| `deca-frontend/` | A separate Next.js/React demo UI app (own `package.json`, `app/`, `components/`, `node_modules/`). Not part of the ISRO data-gen share per the project's own `.gitignore`. |
| `deca-backend/` | A separate Python backend (`main.py`, `deca_pipeline.py`, `telemetry_service.py`, `prometheus_feed.py`, `generate_runbooks.py`, a `chroma_store/` vector DB, `runbooks/`) that presumably serves the frontend demo. Same gitignore exclusion. |
| `.venv/` | Python virtual environment — third-party package installs, not project code. |
| `.tools/` | A locally-downloaded Node.js 20 binary distribution (with its own bundled `node_modules`) used to run the frontend without a system-wide Node install. |
| `__pycache__/` (top-level and under `scripts/`) | Compiled Python bytecode cache — regenerated automatically, safe to delete. |
