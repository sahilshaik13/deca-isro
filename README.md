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

Current campaign job: `20260713_155333` — **21 usable fault runs** (validation PASS). Trainable snapshot: **17,050** feature rows · **1,246** fault-labeled (network only).

Full inventory: [`docs/DATA_SAMPLE.md`](docs/DATA_SAMPLE.md) · Architecture: [`docs/what_is_this.md`](docs/what_is_this.md) · Station networking (systemd / CE / VPN): [`docs/STATION_NETWORK_SETUP.md`](docs/STATION_NETWORK_SETUP.md)

---

## Repository layout

```
deca-isro/
├── README.md                 ← you are here
├── docs/                     documentation
│   ├── DATA_GEN.md           reproduce the data lake
│   ├── DATA_SAMPLE.md        inventory, trainable-set tables, samples
│   ├── what_is_this.md       architecture & ML blueprint
│   └── DECA_Full_Pipeline.md earlier pipeline notes
├── scripts/                  data-generation only
│   ├── _paths.py             repo-rooted data/ paths
│   ├── fetch_public_data.py  public orchestrator
│   ├── deca_fault_campaign.py
│   ├── rebuild_unified.py
│   └── …                     routeviews, riperis, parse_bgp, atlas, ioda, cisco
├── data/
│   ├── raw/public/           Atlas, labels, Cisco, MAWI, BGP rates
│   ├── rpi-net/runs/         campaign telemetry + fault log
│   └── processed/            unified raw + feature parquets
└── models/                   trained artifacts (one folder per model + manifest.json)
```

BGP MRT `*updates*.gz/.bz2` dumps are gitignored (re-fetch via `scripts/fetch_public_data.py`). Rates CSVs and processed parquets are in-repo. Frontend/backend live locally only — not published with this share.

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

# 5. Train prediction stack (wipes models/, rebuilds per blueprint)
python scripts/train_models.py
```

Step-by-step and script map: [`docs/DATA_GEN.md`](docs/DATA_GEN.md). Blueprint: [`docs/DECA_Model_Development_Blueprint.md`](docs/DECA_Model_Development_Blueprint.md).

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
- Full units + addressing + VRF safety-net code: [`docs/STATION_NETWORK_SETUP.md`](docs/STATION_NETWORK_SETUP.md)
- Restore: `bash scripts/deca_deploy_stations.sh`

---

## Outputs to train on

```
data/processed/deca_unified_dataset.parquet   # features + unified_label / fault_type
data/processed/deca_unified_raw.parquet       # long-form telemetry
data/rpi-net/runs/20260713_155333/            # raw campaign truth
models/                                       # per-model folders + manifest.json
```

Rebuild data then models anytime:

```bash
python scripts/rebuild_unified.py
python scripts/train_models.py
```
