# DECA data generation — scripts for ISRO

Only the Python tools needed to **reproduce the data lake that exists today** live under [`scripts/`](../scripts/). Docs live under [`docs/`](./).

## Kept scripts (`scripts/`)

| Script | Produces |
| --- | --- |
| `deca_fault_campaign.py` | RPi CE–PE–CE fault campaign → `data/rpi-net/runs/<id>/` |
| `routeviews.py` / `riperis.py` | BGP MRT archives (`*updates*.{bz2,gz}`) |
| `parse_bgp.py` | `bgp_update_rates_full.csv` / `.parquet` |
| `bgpstream.py` / `ioda.py` (+ `ioda_client.py`) | `bgp_routing_labels.csv`, `ioda_outage_labels.csv` |
| `ripe_atlas.py` | `ripe_atlas_ping_baseline.csv` (+ historical; then sample) |
| `cisco_scraper.py` | `cisco_sandbox_sample.csv` (Cisco DevNet Cat8000v) |
| `fetch_public_data.py` | Orchestrates the public pulls above (sequential) |
| `rebuild_unified.py` | `deca_unified_raw.parquet` + `deca_unified_dataset.parquet` |
| `_paths.py` | Shared repo-rooted `data/` paths |

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
```

## What training uses

- **Supervised labels:** RPi fault windows only (`rebuild_unified.py`).
- **Public rows:** context / magnitude (`fault_type=none`).
- **IODA/BGP outage CSVs:** provenance inventory only until telemet overlap exists — see `data/processed/public_outage_labels_provenance.csv`.
- **Synthetic:** not generated (noise vs real Pi data).
- **MAWI:** magnitude calibration only (flat even-split).

Inventory + samples: [`DATA_SAMPLE.md`](DATA_SAMPLE.md). Architecture: [`what_is_this.md`](what_is_this.md).
