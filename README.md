# DECA-ISRO

**Distributed Enterprise Connectivity Anomaly (DECA)** — physical Raspberry Pi lab faults plus public internet context, fused into trainable matrices for Nvidia-style digital fingerprinting (autoencoder + supervised classification).

Built for ISRO handover: authentic lab ground truth first; public data as scale/context only — not a substitute for the campaign.

---

## What you get

| Layer | Role |
| --- | --- |
| **RPi CE–PE–CE campaign** | Only supervised labels: congestion, tunnel degradation, BGP flap, VRF leakage |
| **Public BGP / Atlas / Cisco / MAWI** | Macro context + magnitude calibration (`fault_type=none` in features) |
| **`deca_unified_*.parquet`** | Trainable feature matrix ready for ML |
| **`models/` + notebook** | Blueprint stack (IF+Platt, Phase-1 XGB, Prophet, LSTM, topology) |

Current campaign job: `20260713_155333` — **21 usable fault runs** (validation PASS). Trainable snapshot: **17,050** feature rows · **1,246** fault-labeled (network only).

---

## Docs index

| Doc | Use when |
| --- | --- |
| [`docs/DATA_GEN.md`](docs/DATA_GEN.md) | Reproduce the data lake (script map + recipe) |
| [`docs/SCRIPTS.md`](docs/SCRIPTS.md) | Every script: purpose, use case, command, outputs |
| [`docs/MODELS.md`](docs/MODELS.md) | Every model: purpose, metrics, artifacts + graphs |
| [`docs/DECA_TEST_SCORES.md`](docs/DECA_TEST_SCORES.md) | Initial → School Exam → playground scores in one place |
| [`docs/DECA_MLOps_Continuous_Learning_Pipeline.md`](docs/DECA_MLOps_Continuous_Learning_Pipeline.md) | School Exam MLOps — `python scripts/deca_mlops_orchestrator.py` |
| Playground | `python scripts/deca_model_playground.py` → `models/playground/scoreboard.md` |
| [`docs/DATA_SAMPLE.md`](docs/DATA_SAMPLE.md) | Inventory of every curated file / sample tables |
| [`docs/DECA_Model_Development_Blueprint.md`](docs/DECA_Model_Development_Blueprint.md) | Formulas, Phase-1 ROI, scorecards |
| [`docs/DECA_ROI_TIERS.md`](docs/DECA_ROI_TIERS.md) | Tiers 1–6 formulas + application + Tier-6 campaign command |
| [`docs/STATION_NETWORK_SETUP.md`](docs/STATION_NETWORK_SETUP.md) | Pi CE/PE units, IPsec, VRF, Prometheus |
| [`docs/DECA_SPECIFICITY_EXAM.md`](docs/DECA_SPECIFICITY_EXAM.md) | Deterministic calm/near-miss FP exam (playlist trust bar) |
| [`lab/`](lab/README.md) | Laptop ↔ Pi cluster ops (diagnostic, deploy, heal, traffic) |
| [`docs/what_is_this.md`](docs/what_is_this.md) | Architecture overview |
| [`docs/REPO_FILE_MANIFEST.md`](docs/REPO_FILE_MANIFEST.md) | Every file/folder in the repo, defined — for handing to a validator |
| [`docs/RISEN_FROM_THE_FALLEN.md`](docs/RISEN_FROM_THE_FALLEN.md) | The whole fault-detection story in plain language, no jargon — read this before the technical docs |
| [`docs/DECA_Full_Pipeline.md`](docs/DECA_Full_Pipeline.md) | Earlier end-to-end pipeline notes |
| [`docs/DECA SETUP.pdf`](docs/DECA%20SETUP.pdf) | Lab setup PDF |
| [`docs/[Pub] ISRO BAH 2026 _ Idea Submission Template.pdf`](docs/%5BPub%5D%20ISRO%20BAH%202026%20_%20Idea%20Submission%20Template.pdf) | BAH submission template |

## Architecture diagrams (Obsidian Preview only)

Not documentation — diagram vault at `obsidian/`. Open a note → **Obsidian Preview: Open Preview**.

| Note | Diagrams |
| --- | --- |
| [`obsidian/DECA_Model_Architectures.md`](obsidian/DECA_Model_Architectures.md) | IF · XGB · LSTM · Prophet · Topology |
| [`obsidian/DECA_Training_Architecture.md`](obsidian/DECA_Training_Architecture.md) | School-exam / orchestrator training loop |

---

## Repository layout

Shareable core (apps are local-only — see note below):

```
deca-isro/
├── README.md                      ← handover entrypoint (this file)
├── docs/                          documentation only
├── obsidian/                      architecture diagrams (Cursor Preview vault)
├── notebook/
│   └── DECA_Model_Training.ipynb  train stack + stage plots
├── scripts/                       data-gen + station deploy / heal
│   ├── _paths.py                  repo-rooted data/ + models/
│   ├── fetch_public_data.py       public orchestrator
│   ├── deca_fault_campaign.py     RPi fault campaign
│   ├── rebuild_unified.py         fuse → unified parquets
│   ├── cisco_scraper.py           optional DevNet sample
│   ├── routeviews.py / riperis.py / parse_bgp.py
│   ├── ripe_atlas.py / bgpstream.py / ioda.py
│   ├── deca_deploy_stations.sh    plug-and-play Pi restore
│   ├── deca_heal_telemetry.sh     Telegraf / ns / IPsec restart
│   └── deca_fix_prom_vpn.sh      Prom TSDB + VRF VPN routes
├── data/
│   ├── raw/public/                Atlas, labels, Cisco, MAWI, BGP rates
│   ├── rpi-net/runs/              campaign telemetry + fault log
│   └── processed/                 unified raw + feature parquets
└── models/                        one folder per family + manifest.json
    ├── isolation_forest/
    ├── fault_classifier/
    ├── prophet_*/
    ├── lstm/
    ├── topology/
    └── manifest.json
```

**Not in this share:** `deca-frontend/` and `deca-backend/` are gitignored local apps. BGP MRT `*updates*.gz/.bz2` dumps are gitignored (re-fetch via `scripts/fetch_public_data.py`); rates CSVs and processed parquets stay in-repo.

---

## Quick start (regenerate lake)

Run everything from the **repository root**:

```bash
source .venv/bin/activate

# 1. Public internet context (sequential — do not parallelize)
python scripts/fetch_public_data.py

# 2. Optional Cisco DevNet sample
python scripts/cisco_scraper.py

# 3. Lab campaign (SSH to Pis + Prometheus on localhost:9090)
python scripts/deca_fault_campaign.py
# resume: python scripts/deca_fault_campaign.py --run-id 20260713_155333

# 4. Fuse → trainable matrices (+ unified_label)
python scripts/rebuild_unified.py

# 5. Train prediction stack (plots inline)
jupyter notebook notebook/DECA_Model_Training.ipynb
# or: jupyter lab notebook/DECA_Model_Training.ipynb
```

In the notebook config cell:

- `WIPE_MODELS=True` — clear `models/` before a full retrain (default for clean runs)
- `PHASE1_ONLY=True` — IF + classifier only (skip Prophet / LSTM / topology)

Step-by-step script map: [`docs/DATA_GEN.md`](docs/DATA_GEN.md). Blueprint: [`docs/DECA_Model_Development_Blueprint.md`](docs/DECA_Model_Development_Blueprint.md).

**Manual once:** `data/raw/public/mawi_sample.csv` — browse [MAWI Samplepoint-F](https://mawi.wide.ad.jp/mawi/samplepoint-F/), copy the 15-minute total, even-split by minute. No automated pcap (robots.txt / size).

---

## Unified classification label

Network and public rows share one vocabulary in `unified_label`:

| `unified_label` | Who gets it |
| --- | --- |
| `healthy` | Network rest windows + **all** public rows today |
| `congestion_breach` / `tunnel_degradation` / `bgp_route_flap` / `vrf_leakage` | RPi fault windows only |

`fault_type` keeps the raw campaign string (`none` ↔ `healthy`). `is_anomaly` is `1` when `unified_label != healthy`.

---

## Design choices worth knowing

| Choice | Why |
| --- | --- |
| Atlas trimmed (~188k, not ~24M) | Keeps public∶lab ~**3∶1** instead of hundreds∶1 |
| Synthetic = **0** | Real Pi labels; synthetic adds noise |
| IODA/BGP outage CSVs not in feature labels | Event dates (~Jul 5) don’t overlap public telem (~Jul 8–13); kept as provenance only |
| MAWI flat even-split | Page exposes one aggregate; magnitude anchor only, not trajectory |
| No `run_traffic.sh` during campaign | Fights eth0 baseline iperf; use campaign traffic only |

---

## Lab topology (short)

- **PE1** `station1@192.168.50.10` · **PE2** `station2@192.168.50.20` · **CORE** `station3@192.168.50.30`
- FRR BGP + VRF (`vrf-mission`) · CE netns `ce-a` / `ce-b` · IPsec `deca-sdwan`
- Telemetry: Telegraf `:9273` → Prometheus → campaign export / `rebuild_unified.py`
- Full units + addressing + VRF safety-net: [`docs/STATION_NETWORK_SETUP.md`](docs/STATION_NETWORK_SETUP.md)
- Restore: `bash scripts/deca_deploy_stations.sh`

---

## Outputs to train on

```
data/processed/deca_unified_dataset.parquet   # features + unified_label / fault_type
data/processed/deca_unified_raw.parquet       # long-form telemetry
data/rpi-net/runs/20260713_155333/            # raw campaign truth
models/                                       # per-model folders + manifest.json
notebook/DECA_Model_Training.ipynb            # retrain + stage graphs
```

Rebuild data then models anytime:

```bash
python scripts/rebuild_unified.py
jupyter notebook notebook/DECA_Model_Training.ipynb
```
