# DECA data generation — scripts for ISRO

Only the Python tools needed to **reproduce the data lake that exists today** live under [`scripts/`](../scripts/). Docs live under [`docs/`](./).

## Kept scripts (`scripts/`)

| Script | Produces |
| --- | --- |
| `deca_fault_campaign.py` | RPi CE–PE–CE fault campaign → `data/rpi-net/runs/<id>/` (`--per-type N` for exact quota; see [`DECA_ROI_TIERS.md`](DECA_ROI_TIERS.md)) |
| `routeviews.py` / `riperis.py` | BGP MRT archives (`*updates*.{bz2,gz}`) |
| `parse_bgp.py` | `bgp_update_rates_full.csv` / `.parquet` |
| `bgpstream.py` / `ioda.py` (+ `ioda_client.py`) | `bgp_routing_labels.csv`, `ioda_outage_labels.csv` |
| `ripe_atlas.py` | `ripe_atlas_ping_baseline.csv` (+ historical; then sample) |
| `cisco_scraper.py` | `cisco_sandbox_sample.csv` (Cisco DevNet Cat8000v) |
| `fetch_public_data.py` | Orchestrates the public pulls above (sequential) |
| `rebuild_unified.py` | `deca_unified_raw.parquet` + `deca_unified_dataset.parquet` (`unified_label`) |
| `deca_deploy_stations.sh` | Plug-and-play: CE-ns, IPsec/FRR ordering, watchdog, VRF CE statics, Prometheus ownership |
| `deca_heal_telemetry.sh` | Quick Telegraf/ns/IPsec restart |
| `deca_fix_prom_vpn.sh` | Wipe poisoned Prom TSDB + VRF underlay VPN routes |
| `_paths.py` | Shared repo-rooted `data/` / `models/` paths |

**Manual (no automatable script):** `mawi_sample.csv` — browse [MAWI Samplepoint-F](https://mawi.wide.ad.jp/mawi/samplepoint-F/), copy page totals, even-split 15 minutes. robots.txt disallows automated pulls; multi-GB pcaps are not part of this package.

## End-to-end recipe

Run from the **repository root** (so relative SSH/lab env stays normal; scripts resolve `data/` via `_paths.py`):

```bash
source .venv/bin/activate

# 1. Public internet context (long; sequential)
python scripts/fetch_public_data.py

# 2. Optional Cisco sandbox sample (~30–45 min scrape)
python scripts/cisco_scraper.py

# 3. Lab ground truth (needs live Pis + Prometheus)
python scripts/deca_fault_campaign.py
# resume: python scripts/deca_fault_campaign.py --run-id <id>

# 4. Build trainable matrices
python scripts/rebuild_unified.py

# 5. Train models (clears models/ first; stage graphs inline)
jupyter notebook notebook/DECA_Model_Training.ipynb
```

Training notebook: [`notebook/DECA_Model_Training.ipynb`](../notebook/DECA_Model_Training.ipynb) — IF+Platt, XGB Phase 1, Prophet, LSTM, topology, with plots per stage.

## Unified label (network + public)

| Column | Role |
| --- | --- |
| `fault_type` | Campaign raw (`none` or fault name) |
| `unified_label` | Shared classifier target: `healthy` ← `none`; faults unchanged |
| `is_anomaly` | `1` if `unified_label != healthy` |

- **Supervised fault classes:** RPi windows only.
- **Public rows:** all `healthy` today (context / magnitude; IODA/BGP outage CSVs remain provenance-only until telem overlap).
- **Synthetic:** not generated.
- **MAWI:** magnitude calibration only.

Inventory: [`DATA_SAMPLE.md`](DATA_SAMPLE.md). Architecture: [`what_is_this.md`](what_is_this.md). Station networking / plug-and-play units: [`STATION_NETWORK_SETUP.md`](STATION_NETWORK_SETUP.md).
