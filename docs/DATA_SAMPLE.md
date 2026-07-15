# DECA Data Folder — Inventory & Samples

_Updated: 2026-07-14 10:00 UTC — docs in `docs/`, generators in `scripts/` (see `docs/DATA_GEN.md`)_
## Network campaign (job `20260713_155333`) — VALIDATION

**Status: COMPLETE — 21 usable runs after dropping 6 no-drift VRF stamps · PRIOR VALIDATOR PASS on full 27**

| Fault type | Runs | Target | Avg duration (start→breach) | Spread |
| --- | ---: | ---: | ---: | ---: |
| `congestion_breach` | 6 | 6 | 11.4 min | 2.5 min |
| `tunnel_degradation` | 5 | 5 | 7.6 min | 1.4 min |
| `bgp_route_flap` | 5 | 5 | 8.9 min | 1.4 min |
| `vrf_leakage` | 5 | 5 | 5.2 min | 1.4 min |

_Trimmed from fault log (kept in `fault_injection_log.csv.bak_pre_vrf_trim`): `real_vrf_leakage_005/007/012/015/017/021` — all ~1.5 min uniform (old injector, no time drift). Kept: 023–027 (~3.1–7.0 min)._

---

## Fetch status

| Dataset | Rows | Size |
| --- | ---: | ---: |
| `raw/public/bgp_routing_labels.csv` | 1,138 | 117.3 KB |
| `raw/public/ioda_outage_labels.csv` | 1,138 | 107.3 KB |
| `raw/public/mawi_sample.csv` | 15 | ~1 KB |
| `raw/public/cisco_sandbox_sample.csv` | 232 | 16 KB |
| `raw/public/*updates*.{gz,bz2}` (MRT) | — | 258.4 MB (93 files) |
| `raw/public/bgp_update_rates_full.csv` | 320 | 10.0 KB |
| `raw/public/ripe_atlas_ping_baseline.csv` | 13,902 | 1.3 MB |
| `raw/public/ripe_atlas_ping_sampled.csv` | 187,971 | 18.5 MB |
| `processed/bgp_update_rates_full.parquet` | 320 | 6.2 KB |
| `processed/deca_unified_dataset.parquet` | 17,050 | 1.1 MB |
| `processed/deca_unified_raw.parquet` | 81,592 | 681 KB |
| `processed/public_outage_labels_provenance.csv` | 2,276 | 276 KB |
| `rpi-net/runs/20260713_155333/fault_injection_log.csv` | 21 | 2.3 KB |
| `rpi-net/runs/20260713_155333/fault_injection_log.csv.bak_pre_vrf_trim` | 27 | 2.8 KB |
| `rpi-net/runs/20260713_155333/network_campaign_export.csv` | 8,734 | 1.37 MB |
| `rpi-net/runs/20260713_155333/network_campaign_export.csv.bak_empty` | 8,840 | 1.38 MB |
| `rpi-net/runs/20260713_155333/network_telemetry.csv` | 52,723 | 3.0 MB |

---

## Composition check — why Atlas had to be trimmed

Row balance matters more than disk: if public rows swamp the RPi campaign, the supervised ground-truth you collected is drowned in macro context.

| Slice | Rows | Notes |
| --- | ---: | --- |
| **Real Pi (campaign)** | **61,457** | `network_telemetry` 52,723 + `network_campaign_export` 8,734 |
| Public **excluding** giant Atlas | ~17k | labels 1,138+1,138 + BGP rates 320 + baseline 13,902 (+ small stubs) — already a sane balance vs Pi |
| Public with **unfiltered** Atlas (`*_full`, ~24.3M) | ~24.3M | public∶real ≈ **~395∶1** — campaign is noise |
| Public with **sampled** Atlas (187,971) | ~205k | public∶real ≈ **~3.3∶1** — still public-heavy (OK for a lower-weight validation / macro layer), but no longer drowning the lab labels |

Trimming Atlas was a **composition** decision first; disk (~2.4 GB → ~19 MB) was secondary.

---

## Trainable set (`rebuild_unified.py` → `deca_unified_*.parquet`)

_Snapshot from rebuild after upsample fix + public-outage provenance split. Synthetic = **0** (deliberate)._

> **Canonical feature-matrix size = 17,050** (re-verified by re-running `rebuild_unified.py`).  
> An earlier terminal paste of **~41,080** was from a **stale pre-fix rebuild** that incorrectly upsampled sparse public series (e.g. Atlas 1-min → 15s, ~4× row inflation on public features → ~39.8k `healthy`). Current `engineer_features()` only downfills when native cadence is denser than the step; minute/sparse series keep native timestamps. Raw merge stays **81,592** either way; fault-labeled counts (**430 / 306 / 300 / 210**) are unchanged. Docs and the scoreboard are tied to **17,050**, not 41,080.

### Raw merge (`deca_unified_raw.parquet` — 81,592 rows)

| Source | Rows | Share | Notes |
| --- | ---: | ---: | --- |
| `network` (RPi campaign) | 52,723 | 64.6% | Ground-truth telemetry |
| `public` | 28,869 | 35.4% | Cisco, MAWI, BGP rates, Atlas sampled (min-agg) + baseline |
| `synthetic` | 0 | 0% | Excluded — noise vs real Pi labels |

### Feature matrix (`deca_unified_dataset.parquet` — 17,050 rows)

| Source | Feature rows | Role |
| --- | ---: | --- |
| `network` | 8,772 | Supervised + baseline |
| `public` | 8,278 | Context / magnitude only (`unified_label=healthy`) |

Public long raw (28,869) → public features (8,278): shrink only (native cadence; no 15s upsample).

### Unified labels (shared classifier vocabulary)

`fault_type=none` → `unified_label=healthy`. Fault names are unchanged. `is_anomaly = (unified_label != healthy)`.

| `unified_label` | Rows |
| --- | ---: |
| `healthy` (network rest + all public) | 15,804 |
| `congestion_breach` | 430 |
| `tunnel_degradation` | 306 |
| `bgp_route_flap` | 300 |
| `vrf_leakage` | 210 |
| **Fault-labeled total** | **1,246** |

| Source × unified_label | `bgp_route_flap` | `congestion_breach` | `tunnel_degradation` | `vrf_leakage` | `healthy` |
| --- | ---: | ---: | ---: | ---: | ---: |
| `network` | 300 | 430 | 306 | 210 | 7,526 |
| `public` | 0 | 0 | 0 | 0 | 8,278 |

Training fault windows: **21** RPi-only. IODA/BGP outage CSVs → `processed/public_outage_labels_provenance.csv` (2,276 events, inventory only — Jul-5-centric, no telemet overlap).

```bash
python scripts/rebuild_unified.py
jupyter notebook notebook/DECA_Model_Training.ipynb   # IF+Platt, XGB, Prophet, LSTM, topology + plots
```

---

## `data/raw/public/bgp_routing_labels.csv`

_ASN BGP outage events (BGPStream/IODA) — **1,138 rows** (117.3 KB)_

| asn | asn_name | start_time | duration_sec | datasource | method | score | event_type | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9304 | AS9304 (HUTCHISON-AS-AP) | 2026-07-05T02:20:00+00:00 | 682800 | bgp | median | 12605.160070241795 | bgp_outage | ioda_bgp |
| 44559 | AS44559 (ITHOSTLINE) | 2026-07-05T02:45:00+00:00 | 681300 | bgp | median | 11939.402324294411 | bgp_outage | ioda_bgp |
| 206375 | AS206375 (NETSPEED) | 2026-07-05T06:30:00+00:00 | 667800 | bgp | median | 32735.294117647056 | bgp_outage | ioda_bgp |
| 29256 | AS29256 (INT-PDN-STE-AS) | 2026-07-05T09:55:00+00:00 | 655500 | bgp | median | 18620.50599201065 | bgp_outage | ioda_bgp |
| 14315 | AS14315 (1GSERVERS) | 2026-07-05T10:55:00+00:00 | 651900 | bgp | median | 169011.1111111111 | bgp_outage | ioda_bgp |
| 45839 | AS45839 (SHINJIRU-MY-AS-AP) | 2026-07-05T11:50:00+00:00 | 648600 | bgp | median | 469525.2525252526 | bgp_outage | ioda_bgp |
| 34918 | AS34918 (PISHGAMAN-DATACENTER) | 2026-07-05T15:20:00+00:00 | 636000 | bgp | median | 16307.692307692309 | bgp_outage | ioda_bgp |
| 10299 | AS10299 () | 2026-07-05T17:35:00+00:00 | 627900 | bgp | median | 49538.46153846154 | bgp_outage | ioda_bgp |
| 28656 | AS28656 () | 2026-07-05T21:30:00+00:00 | 613800 | bgp | median | 143578.94736842104 | bgp_outage | ioda_bgp |
| 29713 | AS29713 (ELIA-60) | 2026-07-05T23:00:00+00:00 | 608400 | bgp | median | 101400.0 | bgp_outage | ioda_bgp |

## `data/raw/public/ioda_outage_labels.csv`

_ASN-filtered IODA outage labels — **1,138 rows** (107.3 KB)_

| entity_code | entity_name | entity_type | start_time | duration_sec | datasource | method | score | outage_condition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 9304 | AS9304 (HUTCHISON-AS-AP) | asn | 2026-07-05T02:20:00+00:00 | 682800 | bgp | median | 12605.160070241795 | outage |
| 44559 | AS44559 (ITHOSTLINE) | asn | 2026-07-05T02:45:00+00:00 | 681300 | bgp | median | 11939.402324294411 | outage |
| 206375 | AS206375 (NETSPEED) | asn | 2026-07-05T06:30:00+00:00 | 667800 | bgp | median | 32735.294117647056 | outage |
| 29256 | AS29256 (INT-PDN-STE-AS) | asn | 2026-07-05T09:55:00+00:00 | 655500 | bgp | median | 18620.50599201065 | outage |
| 14315 | AS14315 (1GSERVERS) | asn | 2026-07-05T10:55:00+00:00 | 651900 | bgp | median | 169011.1111111111 | outage |
| 45839 | AS45839 (SHINJIRU-MY-AS-AP) | asn | 2026-07-05T11:50:00+00:00 | 648600 | bgp | median | 469525.2525252526 | outage |
| 34918 | AS34918 (PISHGAMAN-DATACENTER) | asn | 2026-07-05T15:20:00+00:00 | 636000 | bgp | median | 16307.692307692309 | outage |
| 10299 | AS10299 () | asn | 2026-07-05T17:35:00+00:00 | 627900 | bgp | median | 49538.46153846154 | outage |
| 28656 | AS28656 () | asn | 2026-07-05T21:30:00+00:00 | 613800 | bgp | median | 143578.94736842104 | outage |
| 29713 | AS29713 (ELIA-60) | asn | 2026-07-05T23:00:00+00:00 | 608400 | bgp | median | 101400.0 | outage |

## `data/raw/public/bgp_update_rates_full.csv`

_Global minute BGP update rates — **320 rows** (10.0 KB)_

| timestamp | bgp_update_rate |
| --- | --- |
| 2026-07-08 00:00:00+00:00 | 59319 |
| 2026-07-08 00:01:00+00:00 | 31707 |
| 2026-07-08 00:02:00+00:00 | 36210 |
| 2026-07-08 00:03:00+00:00 | 24881 |
| 2026-07-08 00:04:00+00:00 | 27455 |
| 2026-07-08 00:05:00+00:00 | 24676 |
| 2026-07-08 00:06:00+00:00 | 41740 |
| 2026-07-08 00:07:00+00:00 | 27854 |
| 2026-07-08 00:08:00+00:00 | 23223 |
| 2026-07-08 00:09:00+00:00 | 22049 |

## `data/raw/public/ripe_atlas_ping_baseline.csv`

_Latest Atlas probe RTT/loss snapshot — **13,902 rows** (1.3 MB)_

| timestamp | probe_id | rtt_ms | rtt_min_ms | rtt_max_ms | packet_loss_pct | dst_addr | metric | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-13T14:21:02+00:00 | 1 | 16.794883666666667 | 15.765508 | 17.71546 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:24:11+00:00 | 1000 | 10.375170666666667 | 7.33517 | 12.254979 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:24:19+00:00 | 1000000 | 14.852964666666665 | 14.633265 | 15.159344 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:24:15+00:00 | 1000003 | 3.7347776666666666 | 3.710074 | 3.769148 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:22:10+00:00 | 1000004 | 3.6831946666666666 | 3.654619 | 3.705369 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:21:12+00:00 | 1000006 | 16.72730766666667 | 16.665675 | 16.761744 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:21:38+00:00 | 1000010 | 7.792085 | 7.767338 | 7.828939 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:21:29+00:00 | 1000011 | 87.761677 | 87.713366 | 87.857471 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:20:33+00:00 | 1000013 | 0.9483666666666667 | 0.867453 | 1.061769 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-13T14:22:26+00:00 | 1000017 | 12.342716333333334 | 12.014236 | 12.947118 | 0.0 | 193.0.14.129 | ping | ripe_atlas |

## `data/raw/public/ripe_atlas_ping_sampled.csv`

_Probe×1-min aggregated then stratified sample (~1/129) of Jul 8–13 Atlas history — **187,971 rows** (18.5 MB)_

| timestamp | probe_id | rtt_ms | rtt_min_ms | rtt_max_ms | packet_loss_pct | dst_addr | metric | source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-08T00:00:07+00:00 | 1000 | 12.419842666666668 | 10.989314 | 14.757891 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:17+00:00 | 1000000 | 14.857218666666668 | 14.839055 | 14.891533 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:13+00:00 | 1000003 | 3.730155 | 3.664723 | 3.857556 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:34+00:00 | 1000013 | 1.2649236666666666 | 1.181892 | 1.3247 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:32+00:00 | 1000032 | 8.090313333333333 | 7.592485 | 8.362181 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:21+00:00 | 1000033 | 17.245176333333333 | 16.18716 | 19.012652 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:09+00:00 | 1000063 | 16.6066575 | 14.178169 | 19.035146 | 33.333333333333336 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:30+00:00 | 1000073 | 212.26970400000002 | 211.960008 | 212.587576 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:15+00:00 | 1000093 | 9.227376666666666 | 7.717619 | 10.243316 | 0.0 | 193.0.14.129 | ping | ripe_atlas |
| 2026-07-08T00:00:57+00:00 | 10001 | 15.351444 | 14.646312 | 16.722154 | 0.0 | 193.0.14.129 | ping | ripe_atlas |

## `data/processed/bgp_update_rates_full.parquet`

_Global minute BGP rates (parquet) — **320 × 2** (6.2 KB)_

| timestamp | bgp_update_rate |
| --- | --- |
| 2026-07-08 00:00:00+00:00 | 59319 |
| 2026-07-08 00:01:00+00:00 | 31707 |
| 2026-07-08 00:02:00+00:00 | 36210 |
| 2026-07-08 00:03:00+00:00 | 24881 |
| 2026-07-08 00:04:00+00:00 | 27455 |
| 2026-07-08 00:05:00+00:00 | 24676 |
| 2026-07-08 00:06:00+00:00 | 41740 |
| 2026-07-08 00:07:00+00:00 | 27854 |
| 2026-07-08 00:08:00+00:00 | 23223 |
| 2026-07-08 00:09:00+00:00 | 22049 |

## `data/processed/deca_unified_dataset.parquet`

_ML feature matrix — **17,050 × 24** (~1.1 MB). Rebuilt via `rebuild_unified.py` (no synthetic; no public-outage labeling)._  
_Public feature rows shrink vs long raw (28,869 → 8,278) after fixing accidental 15s upsample of Atlas minute series. All **1,246** fault-labeled rows are RPi-only; IODA/BGP outage CSVs kept as `public_outage_labels_provenance.csv` (Jul-5-centric events have no overlapping public telemetry)._


## `data/processed/deca_unified_raw.parquet`

_Long-form unified raw metrics — **81,592 × 5** (681 KB). Network 52,723 + public 28,869 (Cisco, MAWI, BGP rates, Atlas minute-agg + baseline)._  
_Prior stale snapshot: `deca_unified_raw.parquet.bak_pre_rebuild` (241,677 rows — mostly old synthetic)._

| timestamp | metric | value | run_id | source |
| --- | --- | ---: | --- | --- |
| 2026-07-13 10:23:44+00:00 | ifInOctets | 559018.87 | rpi_station1 | network |
| 2026-07-13 10:23:59+00:00 | ifInOctets | 489043.16 | rpi_station1 | network |
| 2026-07-13 10:24:14+00:00 | ifInOctets | 355148.07 | rpi_station1 | network |

## `data/rpi-net/runs/20260713_155333/fault_injection_log.csv`

_Ground-truth fault labels — **21 rows** (after VRF trim). Prior 27-run validator: **PASS**; backup `fault_injection_log.csv.bak_pre_vrf_trim`._

| fault_type | fault_start | breach_time | run_id |
| --- | --- | --- | --- |
| congestion_breach | 2026-07-13T10:48:17.820456+00:00 | 2026-07-13T10:57:30.237215+00:00 | real_congestion_breach_001 |
| bgp_route_flap | 2026-07-13T11:22:24.818818+00:00 | 2026-07-13T11:32:15.136668+00:00 | real_bgp_route_flap_002 |
| tunnel_degradation | 2026-07-13T11:55:47.504033+00:00 | 2026-07-13T12:05:03.681269+00:00 | real_tunnel_degradation_003 |
| bgp_route_flap | 2026-07-13T13:01:17.626503+00:00 | 2026-07-13T13:08:31.722485+00:00 | real_bgp_route_flap_004 |
| congestion_breach | 2026-07-13T14:04:03.231354+00:00 | 2026-07-13T14:18:07.613181+00:00 | real_congestion_breach_006 |
| tunnel_degradation | 2026-07-13T16:21:51.074438+00:00 | 2026-07-13T16:29:36.842002+00:00 | real_tunnel_degradation_008 |
| tunnel_degradation | 2026-07-13T16:54:50.325919+00:00 | 2026-07-13T17:01:50.478006+00:00 | real_tunnel_degradation_009 |
| bgp_route_flap | 2026-07-13T17:26:44.684768+00:00 | 2026-07-13T17:36:47.398045+00:00 | real_bgp_route_flap_010 |
| congestion_breach | 2026-07-13T18:00:00.685984+00:00 | 2026-07-13T18:11:09.549106+00:00 | real_congestion_breach_011 |
| bgp_route_flap | 2026-07-13T19:03:04.435143+00:00 | 2026-07-13T19:10:27.101767+00:00 | real_bgp_route_flap_013 |

## `data/rpi-net/runs/20260713_155333/network_campaign_export.csv`

_Labeled telemetry export for ML — **8,734 rows** (1.37 MB). Final Prometheus re-export after 27/27; **106** empty-metric rows dropped._  
_Pre-clean backup: `network_campaign_export.csv.bak_empty` (8,840 rows / 1.38 MB) — full re-export before empty-row cleanup. Covers 10:23 UTC Jul 13 → 07:27 UTC Jul 14 (incl. VRF 023–027)._  
_After VRF trim: rows formerly tagged `real_vrf_leakage_005/007/012/015/017/021` relabeled to `fault_type=none` (~1,076 rows)._

| timestamp | host | drop_out_rate | jitter_ms | latency_ms | packet_loss_pct | throughput_in_bps | throughput_out_bps | throughput_in_mbps | throughput_out_mbps | fault_type | run_id |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-13T10:23:44+00:00 | station1 | 0.0 | 2542.938 | 3031.894 | 100.0 | 559018.8727272727 | 11168619.109090907 | 4.4721509818181815 | 89.34895287272727 | none |  |
| 2026-07-13T10:23:44+00:00 | ubuntu | 0.0 | 0.2645 | 1.1685 | 0.0 | 13101911.527272727 | 658358.5818181818 | 104.81529221818182 | 5.266868654545454 | none |  |
| 2026-07-13T10:23:59+00:00 | station1 | 0.0 | 3.967 | 3.781 | 0.0 | 489043.16363636364 | 11386653.654545454 | 3.912345309090909 | 91.09322923636364 | none |  |
| 2026-07-13T10:23:59+00:00 | ubuntu | 0.0 | 2.459 | 1.9865 | 0.0 | 9473699.545454545 | 435383.6363636363 | 75.78959636363636 | 3.4830690909090904 | none |  |
| 2026-07-13T10:24:14+00:00 | station1 | 0.0 | 836.095 | 1125.503 | 0.0 | 355148.06734300574 | 8774775.662703175 | 2.841184538744046 | 70.1982053016254 | none |  |
| 2026-07-13T10:24:14+00:00 | ubuntu | 0.0 | 416.5365 | 566.9615 | 0.0 | 11006480.563636363 | 466772.0909090909 | 88.0518445090909 | 3.734176727272727 | none |  |
| 2026-07-13T10:24:29+00:00 | station1 | 0.0 | 0.0 | 4183.683 | 90.0 | 457179.7818181818 | 11007803.563636363 | 3.6574382545454545 | 88.0624285090909 | none |  |
| 2026-07-13T10:24:29+00:00 | ubuntu | 0.0 | 416.457 | 566.8725000000001 | 0.0 | 8772019.654545454 | 350121.72727272724 | 70.17615723636364 | 2.800973818181818 | none |  |
| 2026-07-13T10:24:44+00:00 | station1 | 0.0 | 0.0 | 4183.683 | 90.0 | 411009.2727272727 | 10190046.127272727 | 3.288074181818182 | 81.52036901818181 | none |  |
| 2026-07-13T10:24:44+00:00 | ubuntu | 0.0 | 0.081 | 1.2934999999999999 | 45.0 | 11306810.654545454 | 467172.27272727276 | 90.45448523636364 | 3.737378181818182 | none |  |

## `data/rpi-net/runs/20260713_155333/network_telemetry.csv`

_Raw Prometheus scrape time series — **52,723 rows** (3.0 MB)_

| timestamp | host | metric | value |
| --- | --- | --- | --- |
| 2026-07-13T10:23:44+00:00 | station1 | throughput_in_bps | 559018.8727272727 |
| 2026-07-13T10:23:59+00:00 | station1 | throughput_in_bps | 489043.16363636364 |
| 2026-07-13T10:24:14+00:00 | station1 | throughput_in_bps | 355148.06734300574 |
| 2026-07-13T10:24:29+00:00 | station1 | throughput_in_bps | 457179.7818181818 |
| 2026-07-13T10:24:44+00:00 | station1 | throughput_in_bps | 411009.2727272727 |
| 2026-07-13T10:24:59+00:00 | station1 | throughput_in_bps | 625016.709090909 |
| 2026-07-13T10:25:14+00:00 | station1 | throughput_in_bps | 447373.8363636363 |
| 2026-07-13T10:25:29+00:00 | station1 | throughput_in_bps | 431078.7454545454 |
| 2026-07-13T10:25:44+00:00 | station1 | throughput_in_bps | 328398.4727272727 |
| 2026-07-13T10:25:59+00:00 | station1 | throughput_in_bps | 444738.3818181818 |

## Full fault log (all 21 usable runs)

| fault_type | fault_start | breach_time | run_id |
| --- | --- | --- | --- |
| congestion_breach | 2026-07-13T10:48:17.820456+00:00 | 2026-07-13T10:57:30.237215+00:00 | real_congestion_breach_001 |
| bgp_route_flap | 2026-07-13T11:22:24.818818+00:00 | 2026-07-13T11:32:15.136668+00:00 | real_bgp_route_flap_002 |
| tunnel_degradation | 2026-07-13T11:55:47.504033+00:00 | 2026-07-13T12:05:03.681269+00:00 | real_tunnel_degradation_003 |
| bgp_route_flap | 2026-07-13T13:01:17.626503+00:00 | 2026-07-13T13:08:31.722485+00:00 | real_bgp_route_flap_004 |
| congestion_breach | 2026-07-13T14:04:03.231354+00:00 | 2026-07-13T14:18:07.613181+00:00 | real_congestion_breach_006 |
| tunnel_degradation | 2026-07-13T16:21:51.074438+00:00 | 2026-07-13T16:29:36.842002+00:00 | real_tunnel_degradation_008 |
| tunnel_degradation | 2026-07-13T16:54:50.325919+00:00 | 2026-07-13T17:01:50.478006+00:00 | real_tunnel_degradation_009 |
| bgp_route_flap | 2026-07-13T17:26:44.684768+00:00 | 2026-07-13T17:36:47.398045+00:00 | real_bgp_route_flap_010 |
| congestion_breach | 2026-07-13T18:00:00.685984+00:00 | 2026-07-13T18:11:09.549106+00:00 | real_congestion_breach_011 |
| bgp_route_flap | 2026-07-13T19:03:04.435143+00:00 | 2026-07-13T19:10:27.101767+00:00 | real_bgp_route_flap_013 |
| tunnel_degradation | 2026-07-13T19:28:39.725091+00:00 | 2026-07-13T19:34:18.752743+00:00 | real_tunnel_degradation_014 |
| congestion_breach | 2026-07-13T20:34:04.921413+00:00 | 2026-07-13T20:41:55.876330+00:00 | real_congestion_breach_016 |
| congestion_breach | 2026-07-13T21:35:30.822436+00:00 | 2026-07-13T21:47:11.002077+00:00 | real_congestion_breach_018 |
| bgp_route_flap | 2026-07-13T22:08:56.200502+00:00 | 2026-07-13T22:18:45.649906+00:00 | real_bgp_route_flap_019 |
| tunnel_degradation | 2026-07-13T22:40:57.859958+00:00 | 2026-07-13T22:49:26.035300+00:00 | real_tunnel_degradation_020 |
| congestion_breach | 2026-07-13T23:42:36.252589+00:00 | 2026-07-13T23:56:46.907947+00:00 | real_congestion_breach_022 |
| vrf_leakage | 2026-07-14T04:01:11.227653+00:00 | 2026-07-14T04:06:37.157734+00:00 | real_vrf_leakage_023 |
| vrf_leakage | 2026-07-14T04:37:13.810953+00:00 | 2026-07-14T04:42:26.377503+00:00 | real_vrf_leakage_024 |
| vrf_leakage | 2026-07-14T05:06:52.618680+00:00 | 2026-07-14T05:12:13.411710+00:00 | real_vrf_leakage_025 |
| vrf_leakage | 2026-07-14T06:43:35.518968+00:00 | 2026-07-14T06:50:32.327039+00:00 | real_vrf_leakage_026 |
| vrf_leakage | 2026-07-14T07:20:23.163374+00:00 | 2026-07-14T07:23:31.308722+00:00 | real_vrf_leakage_027 |

## BGP MRT archives (binary) — `data/raw/public/*updates*.{gz,bz2}`

**93 compressed RouteViews / RIPE RIS update dumps — 258.4 MB total.**  
Fetched by `routeviews.py` / `riperis.py`; parsed by `parse_bgp.py` → `bgp_update_rates_full.csv` / `.parquet` (**320** minute buckets).

| Collector | Files | Size | Format | Example names |
| --- | ---: | ---: | --- | --- |
| `route-views.linx` | 20 | 123.0 MB | `.bz2` | `route-views.linx_updates.20260708.0000.bz2` |
| `rrc00` (RIPE RIS) | 20 | 85.8 MB | `.gz` | `rrc00_updates.20260708.0000.gz` |
| `route-views2` | 20 | 23.9 MB | `.bz2` | `route-views2_updates.20260708.0000.bz2` |
| unprefixed `updates.*` | 13 | 15.6 MB | `.bz2` | `updates.20260710.0000.bz2` |
| `rrc11` (RIPE RIS) | 20 | 10.1 MB | `.gz` | `rrc11_updates.20260708.0000.gz` … `rrc11_updates.20260711.1200.gz` |

**Time window:** `20260708.0000` → `20260712.1800` (6-hour slots × 5 days; 20 unique stamps).

**What training uses today:** only the derived rates file (`bgp_update_rates_full.*`). These archives are **raw source** — keep them if you may re-parse richer BGP features (AS-path / peer diversity); safe to delete for disk if rates-only is locked (re-fetch via the download scripts).

**Validate:**

```bash
ls data/raw/public/*updates*.{gz,bz2} | wc -l   # expect 93
du -ch data/raw/public/*updates*.{gz,bz2} | tail -1
wc -l data/raw/public/bgp_update_rates_full.csv  # expect 321 (header + 320)
```

## `data/raw/public/mawi_sample.csv`

_MAWI Samplepoint-F backbone byte volume — **15 rows** (manual from [202607131400](https://mawi.wide.ad.jp/mawi/samplepoint-F/2026/202607131400.html); even split of 404,835,663,805 bytes over 14:00–14:15 JST)._

| timestamp | value |
| --- | ---: |
| 2026-07-13T14:00:00+09:00 | 26989044254 |
| 2026-07-13T14:01:00+09:00 | 26989044254 |
| 2026-07-13T14:02:00+09:00 | 26989044254 |
| 2026-07-13T14:03:00+09:00 | 26989044254 |
| 2026-07-13T14:04:00+09:00 | 26989044254 |
| 2026-07-13T14:05:00+09:00 | 26989044254 |
| 2026-07-13T14:06:00+09:00 | 26989044254 |
| 2026-07-13T14:07:00+09:00 | 26989044254 |
| 2026-07-13T14:08:00+09:00 | 26989044254 |
| 2026-07-13T14:09:00+09:00 | 26989044254 |
| … | … |

_Page: 373,429,974 packets · AvgRate 3020.41 Mbps · TotalTime 900.03 s. Value = bytes/minute (sum matches page total). No pcap (robots.txt)._

**Role — magnitude calibration only, not trajectory features** (public data granularity limits). The info page publishes one aggregate for the full 15-minute window, so all 15 CSV rows are an honest even-split of that total: real Tokyo↔US backbone **scale**, zero real per-minute variation. Rolling std / slope on MAWI rows will legitimately compute to ~0; feature selection will naturally deprioritize those channels — no code fix needed. Variance already comes from RPi telemetry, sampled RIPE Atlas, and the Cisco sandbox. A multi-GB `.pcap` + `tshark` rebuild could add true minute dynamics, but that fights the “authentic, not huge” rule and isn’t worth the cost for one validation anchor.

## `data/raw/public/cisco_sandbox_sample.csv`

_Cisco DevNet Cat8000v sandbox (`GigabitEthernet1`) — **232 rows** (16 KB); `cisco_scraper.py` / Netmiko, ~15 s interval, ~31 min window 05:31–06:02 UTC 2026-07-14. 116 scrapes × `ifInOctets` + `ifOutOctets`._

| timestamp | metric | value |
| --- | --- | ---: |
| 2026-07-14T05:31:12.049352+00:00 | ifInOctets | 455913 |
| 2026-07-14T05:31:12.049352+00:00 | ifOutOctets | 782461 |
| 2026-07-14T05:31:28.093325+00:00 | ifInOctets | 472644 |
| 2026-07-14T05:31:28.093325+00:00 | ifOutOctets | 823931 |
| 2026-07-14T05:31:44.370545+00:00 | ifInOctets | 482680 |
| 2026-07-14T05:31:44.370545+00:00 | ifOutOctets | 851729 |
| 2026-07-14T05:32:00.596766+00:00 | ifInOctets | 489562 |
| 2026-07-14T05:32:00.596766+00:00 | ifOutOctets | 877086 |
| 2026-07-14T05:32:16.733516+00:00 | ifInOctets | 498245 |
| 2026-07-14T05:32:16.733516+00:00 | ifOutOctets | 904130 |

_Ended on Netmiko prompt timeout after the sample window; CSV left intact._

## Removed (not required for training)

- `raw/public/ripe_atlas_ping_full.csv` (24.3M / ~2.4 GB) — replaced by `ripe_atlas_ping_sampled.csv` (probe×1-min means, then keep every 129th row → 187,971 / 18.5 MB)

- `processed/bgp_update_rates_by_file.parquet` — redundant; use `bgp_update_rates_full.*`
- `processed/deca_unified_fault_log.csv` — stale legacy synthetic log (notebook regenerates)
- `raw/public/asn_organization_map.csv` — optional PeeringDB context, unused by feature eng
- Stub campaign `20260713_184356` → `data/rpi-net/archive/`
- Stale unify snapshots → `*.parquet.bak_pre_rebuild` (replaced by `python scripts/rebuild_unified.py`)
- Public IODA/BGP outage events → `processed/public_outage_labels_provenance.csv` (inventory only; not training labels — no telemetry overlap with Jul 8–13 public series)
- Synthetic telemetry — deliberately excluded from `scripts/rebuild_unified.py` (noise vs real Pi ground truth)
