# DECA scripts catalog

Inventory of every tool under [`scripts/`](../scripts/). Run all commands from the **repository root** with the project venv active:

```bash
cd /home/brain/deca-isro   # or your clone path
source .venv/bin/activate
```

Paths resolve via [`_paths.py`](../scripts/_paths.py) (`data/`, `models/`), not the shell cwd for I/O.

| Group | Scripts |
| --- | --- |
| Shared | `_paths.py` |
| Public lake | `fetch_public_data.py`, `routeviews.py`, `riperis.py`, `parse_bgp.py`, `ripe_atlas.py`, `bgpstream.py`, `ioda.py`, `ioda_client.py`, `cisco_scraper.py` |
| Lab campaign | `deca_fault_campaign.py` |
| Unify / train prep | `rebuild_unified.py`, `deca_school_exam_train.py`, `deca_mlops_orchestrator.py`, `deca_model_playground.py`, `deca_model_experts.py` |
| Station ops | `deca_deploy_stations.sh`, `deca_heal_telemetry.sh`, `deca_fix_prom_vpn.sh`, `deca_debug_vpn_prom.sh` |

**Not a script (training):** [`notebook/DECA_Model_Training.ipynb`](../notebook/DECA_Model_Training.ipynb) — see README / [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md).  
**Manual:** `data/raw/public/mawi_sample.csv` — no automatable download.

---

## Shared

### `_paths.py`

| | |
| --- | --- |
| **Purpose** | Single source of truth for repo-rooted directories. |
| **Use case** | Imported by other scripts; not run directly. |
| **Defines** | `REPO_ROOT`, `DATA_DIR`, `PUBLIC_DIR` (`data/raw/public`), `PROCESSED_DIR`, `RPI_NET_DIR`, `MODELS_DIR`, `SCRIPTS_DIR` |
| **Output** | Creates those dirs if missing. |

---

## Public data lake

Typical order: `fetch_public_data.py` (orchestrator) **or** run children one-by-one. Then optional Cisco + MAWI. Lab campaign is separate.

### `fetch_public_data.py`

| | |
| --- | --- |
| **Purpose** | Sequential orchestrator for public pulls (keeps RAM low). |
| **Use case** | Rebuild / refresh the public half of the lake after a clean clone. |
| **Command** | `python scripts/fetch_public_data.py` |
| **Flags** | `--skip-bgp-parse` · `--skip-atlas-full` · `--atlas-chunk-minutes N` |
| **Runs** | `routeviews` → `riperis` → `bgpstream` → `ioda` → `ripe_atlas` → `parse_bgp` |
| **Output** | Whatever the child scripts write under `data/raw/public/` and `data/processed/` (see below). |

### `routeviews.py`

| | |
| --- | --- |
| **Purpose** | Download RouteViews BGP MRT update dumps. |
| **Use case** | Raw BGP message archives for rate features. |
| **Command** | `python scripts/routeviews.py` |
| **Output** | `data/raw/public/route-views2_updates.*.bz2`, `route-views.linx_updates.*.bz2` (gitignored — large). |

### `riperis.py`

| | |
| --- | --- |
| **Purpose** | Download RIPE RIS RRC BGP MRT update dumps. |
| **Use case** | Same as RouteViews; second collector family. |
| **Command** | `python scripts/riperis.py` |
| **Output** | `data/raw/public/rrc00_updates.*.gz`, `rrc11_updates.*.gz` (gitignored). |

### `parse_bgp.py`

| | |
| --- | --- |
| **Purpose** | Memory-safe MRT → minute-level update rates. |
| **Use case** | After MRT downloads; builds the BGP rate series used in `rebuild_unified`. |
| **Command** | `python scripts/parse_bgp.py --resume` |
| **Flags** | `--limit N` · `--resume` · `--reset` |
| **Output** | `data/processed/bgp_update_rates_full.parquet` · `data/raw/public/bgp_update_rates_full.csv` · checkpoint `data/processed/bgp_parse_checkpoint.json` |

### `ripe_atlas.py`

| | |
| --- | --- |
| **Purpose** | RIPE Atlas ping RTT / loss (latest snapshot or chunked historical). |
| **Use case** | Public latency/loss context; full pull is large — prefer orchestrator flags. |
| **Command** | `python scripts/ripe_atlas.py` (baseline) · `python scripts/ripe_atlas.py --full --resume` (historical) |
| **Flags** | `--msm-id` · `--full` · `--start` / `--end` · `--chunk-minutes` · `--resume` · `--reset` |
| **Output** | `data/raw/public/ripe_atlas_ping_baseline.csv` and/or `ripe_atlas_ping_full.csv` · checkpoint `ripe_atlas_full_checkpoint.json`. Sampled subset used downstream: `ripe_atlas_ping_sampled.csv` (curated in lake). |

### `bgpstream.py`

| | |
| --- | --- |
| **Purpose** | ASN BGP outage / routing labels via IODA BGP events (paginated). |
| **Use case** | Provenance / inventory of public BGP events (not applied as feature labels today — window mismatch). |
| **Command** | `python scripts/bgpstream.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]` |
| **Output** | `data/raw/public/bgp_routing_labels.csv` |

### `ioda.py`

| | |
| --- | --- |
| **Purpose** | IODA ASN outage labels (paginated API). |
| **Use case** | Same provenance role as `bgpstream.py`. |
| **Command** | `python scripts/ioda.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]` |
| **Output** | `data/raw/public/ioda_outage_labels.csv` |

### `ioda_client.py`

| | |
| --- | --- |
| **Purpose** | Shared IODA HTTP client with pagination. |
| **Use case** | Library for `bgpstream.py` / `ioda.py`; not run alone. |
| **Output** | None (returns Python lists/dicts). |

### `cisco_scraper.py`

| | |
| --- | --- |
| **Purpose** | Scrape Cisco DevNet Always-On Cat8000v Gi1 interface counters. |
| **Use case** | Optional public magnitude sample (sandbox; needs network + credentials in script). |
| **Command** | `python scripts/cisco_scraper.py` |
| **Output** | `data/raw/public/cisco_sandbox_sample.csv` |

---

## Lab fault campaign

### `deca_fault_campaign.py`

| | |
| --- | --- |
| **Purpose** | Quota-driven CE–PE–CE fault injection on the RPi lab (SSH + Prometheus). |
| **Use case** | Ground-truth supervised labels: congestion, tunnel degradation, BGP flap, VRF leakage. Tier-6 scale-up: `--per-type 10`. |
| **Needs** | Lab LAN up; `station1/2/3` SSH; Prometheus on laptop `:9090`. |
| **Command** | see below |
| **Flags** | `--per-type N` · `--min-per-type` / `--max-per-type` · `--run-id` · `--demo` |

```bash
# Exact 10 of each fault type (40 total), new run id
python scripts/deca_fault_campaign.py \
  --run-id "$(date -u +%Y%m%d_%H%M%S)_tier6_x10" \
  --per-type 10

# Resume interrupted job
python scripts/deca_fault_campaign.py --run-id <existing_id> --per-type 10
```

| **Output** (under `data/rpi-net/runs/<run-id>/`) | When |
| --- | --- |
| `fault_injection_log.csv` | continuously |
| `campaign_state.json` | continuously |
| `campaign_run.log` | continuously |
| `network_telemetry.csv` | **end** (Prom pull) |
| `network_campaign_export.csv` | **end** (pivoted + fault labels) |

Details: [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md) · station map: [`STATION_NETWORK_SETUP.md`](STATION_NETWORK_SETUP.md).

---

## Unify / train prep

### `rebuild_unified.py`

| | |
| --- | --- |
| **Purpose** | Fuse RPi campaign + public lake → raw long table + engineered feature matrix + `unified_label`. |
| **Use case** | After a new campaign finishes or public files change; **before** reopening the training notebook. |
| **Command** | `python scripts/rebuild_unified.py` |
| **Input** | Hardcoded campaign dir today: `data/rpi-net/runs/20260713_155333/` (+ all curated `data/raw/public/*`). Point `RPI_RUN` in the script at a newer run when Tier-6 completes. |
| **Output** | |
| | `data/processed/deca_unified_raw.parquet` |
| | `data/processed/deca_unified_dataset.parquet` (**canonical ~17,050** rows today) |
| | `data/processed/deca_unified_fault_log.csv` |
| | `data/processed/public_outage_labels_provenance.csv` (inventory only) |

Notes: synthetic = **0**; IODA/BGP outage CSVs are **not** applied as row labels; no upsample of sparse public series (see [`DATA_SAMPLE.md`](DATA_SAMPLE.md)).

### `deca_school_exam_train.py`

| | |
| --- | --- |
| **Purpose** | Mode A School Exam engine: **fresh stratified exam paper each run** → per‑head β sweep → promotion gate vs `manifest.json`. Heads: `plain` (champion booster), `wm` (KMeans **cluster** layer + mild reg), `moe` (**mixture of per‑fault experts** + stacked meta‑gate). |
| **Use case** | Low-level exam runs; prefer **`deca_mlops_orchestrator.py`** for automated promote/keep. |
| **Command** | `python scripts/deca_school_exam_train.py` · `--auto-promote` to apply gate · `--exam-seed 42` to replay |
| **Flags** | `--families plain,wm,moe` · `--report-seeds N` (repeated-holdout spread) · `--holdout-policy random\|time_tail` · `--exam-seed` · `--holdout-frac` · `--rare-boosts` · `--auto-promote` |
| **Output** | `models/school_exam/weight_sweep.csv` (per family+β), `latest_exam.json`; with `--report-seeds`: `seed_report.{json,md}` |
| **Gate** | Candidate must beat the **honest same-paper champion config** (`plain` retrained on the blind pool), floored at the manifest baseline. Deployed artifact's same-paper score is reported but **leakage-inflated** (not the bar). |
| **Note** | Head configs live in `scripts/deca_model_experts.py`. All heads share the exact same gated inference path — the machine promotes a deeper head **only if it beats the champion on a fresh paper**. On the current lake, `wm`/`moe` **lose** to `plain` (see ROI Tier 5.5). |

### `deca_mlops_orchestrator.py`

| | |
| --- | --- |
| **Purpose** | **Teach → test → examine → score → improve** loop with a **fresh random exam paper every cycle** until GATE PASS (promote) or `--max-cycles`. No human judge. |
| **Use case** | Continuous learning on current lake (Mode A) or after a completed campaign (Mode B). |
| **Command** | `python scripts/deca_mlops_orchestrator.py` · `--max-cycles 5` · `--once` · `--dry-run` · `--mode B --rpi-run <id>` |
| **Flags** | `--max-cycles` · `--once` · `--dry-run` · `--mode A\|B` · `--rpi-run` · `--families plain,wm,moe` · exam flags |
| **Output** | `orchestrator_latest.json`, `orchestrator_history.jsonl`, exam artifacts; promotes `models/fault_classifier/` on PASS |

### `deca_model_playground.py`

| | |
| --- | --- |
| **Purpose** | Mixed blind test playground: one stratified random paper → score **every** model individually (IF, XGB, LSTM, Prophet ×3, topology). No retrain / no promote. |
| **Use case** | Compare the live stack on the same general mixed holdout after School Exam promote. |
| **Command** | `python scripts/deca_model_playground.py` · `--exam-seed 42` · `--prophet-refit` for honest Prophet |
| **Flags** | `--holdout-frac` · `--holdout-policy` · `--exam-seed` · `--prophet-refit` · `--skip-lstm` · `--skip-prophet` |
| **Output** | `models/playground/scoreboard.md`, `scoreboard.csv`, `latest_playground.json` |

---

## Station operations (shell)

Run from the laptop on the USB lab NIC (`192.168.50.1`). Lab form: `192.168.50.x` with **x = 10 / 20 / 30** (PE1 / PE2 / CORE).

### `deca_deploy_stations.sh`

| | |
| --- | --- |
| **Purpose** | Full plug-and-play restore: CE netns units, FRR/strongSwan ordering, watchdog + VRF static safety-net, hostnames, Prom ownership check. |
| **Use case** | Cold boot / sticky IPsec / broken CE-ns / VPN path dead despite ESTABLISHED. |
| **Command** | `bash scripts/deca_deploy_stations.sh` |
| **Output** | Side effects on Pis (systemd units, vtysh routes); console progress. Not a data file. |

### `deca_heal_telemetry.sh`

| | |
| --- | --- |
| **Purpose** | Quick heal: restart `deca-ns` / FRR / IPsec / Telegraf on PEs; nudge CORE Telegraf. |
| **Use case** | After partial boot when `[7/8]` VPN or `[8/8]` scrapes flake without a full redeploy. |
| **Command** | `bash scripts/deca_heal_telemetry.sh` |
| **Output** | Service restarts on stations; prints active status. |

### `deca_fix_prom_vpn.sh`

| | |
| --- | --- |
| **Purpose** | Targeted fix for the two confirmed failures: Prom `out of bounds` (wipe TSDB + `prometheus:prometheus` ownership) and VPN/VRF statics when VPNv4 has 0 prefixes. |
| **Use case** | After `deca_debug_vpn_prom.sh` points at poisoned TSDB or missing VRF underlay routes. |
| **Command** | `bash scripts/deca_fix_prom_vpn.sh` |
| **Output** | Cleared `/var/lib/prometheus/metrics2` + restored CE VRF statics via SSH. |

### `deca_debug_vpn_prom.sh`

| | |
| --- | --- |
| **Purpose** | Deep diagnostic for Prom scrape `out of bounds` and CE-A→CE-B 100% loss with IPsec up. |
| **Use case** | Before/after heal — clock skew, Telegraf timestamps, VPN ping, BGP/VRF clues. |
| **Command** | `bash scripts/deca_debug_vpn_prom.sh` |
| **Output** | Console report only (may attempt mild fixes). Prefer `deca_fix_prom_vpn.sh` for the wipe/statics remediation. |

---

## End-to-end recipe (pointers)

1. Public: `python scripts/fetch_public_data.py` (+ manual MAWI, optional `cisco_scraper.py`)  
2. Lab: `python scripts/deca_fault_campaign.py --per-type …`  
3. Fuse: `python scripts/rebuild_unified.py`  
4. Train: `jupyter notebook notebook/DECA_Model_Training.ipynb`  
5. Stations sticky: `bash scripts/deca_deploy_stations.sh` then `bash ~/deca_diagnostic.sh`

Full narrative: [`DATA_GEN.md`](DATA_GEN.md) · inventory: [`DATA_SAMPLE.md`](DATA_SAMPLE.md) · networking: [`STATION_NETWORK_SETUP.md`](STATION_NETWORK_SETUP.md).
