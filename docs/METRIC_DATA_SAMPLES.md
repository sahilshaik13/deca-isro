# Metric data samples (10 rows each)

Real rows from Pi CAPTURE_CONTRACT campaign `full_variants_pi_contract_20260805T042130Z` (**raw** `series.csv`, not `align_1hz`).  
Companion columns are context only — each section is named for the metric being illustrated.

TT&C reference SLAs: latency ≤25 ms · jitter ≤5 ms · loss ≤0.1% · util soft ceiling ~40 Mbit (HTB payload ceil ~34 Mbit).

**Stamp notes (2026-08-05):** sealed 46/46 · asymmetry exact `|gre−eth0|` on every row · L5 live `util_ceil_schedule.jsonl` + plateau ≥40s · Q1 floors pass (loss/jitter soft-headroom only). Prior stamp `full_variants_pi_20260803T175816Z` samples retired here.

---

## 1. Latency — `latency_gre_ms` / `latency_eth0_ms`

**Inject:** L1 rain fade (`L1_rain_fade/iter_03`) — GRE crosses 25 ms SLA; eth0 stays clean. Gap `6253→6255` is a dropped capture second (see § gaps).

| ts_unix | latency_gre_ms | latency_eth0_ms | path_asymmetry |
| ---: | ---: | ---: | ---: |
| 1785916249 | 17.874 | 0.258 | 17.616 |
| 1785916250 | 17.874 | 0.258 | 17.616 |
| 1785916251 | 25.439 | 0.262 | 25.177 |
| 1785916252 | 25.439 | 0.262 | 25.177 |
| 1785916253 | 25.439 | 0.262 | 25.177 |
| 1785916255 | 26.287 | 0.244 | 26.043 |
| 1785916256 | 26.287 | 0.244 | 26.043 |
| 1785916257 | 24.553 | 0.257 | 24.296 |
| 1785916258 | 22.041 | 0.267 | 21.774 |
| 1785916259 | 22.041 | 0.267 | 21.774 |

---

## 2. Jitter — `jitter_gre_ms`

**Inject:** L1 rain fade (`L1_rain_fade/iter_02`) — crosses TT&C jitter SLA (5 ms).

| ts_unix | jitter_gre_ms | latency_gre_ms |
| ---: | ---: | ---: |
| 1785914970 | 4.684 | 2.794 |
| 1785914971 | 4.684 | 4.319 |
| 1785914972 | 5.220 | 2.674 |
| 1785914973 | 5.220 | 2.674 |
| 1785914974 | 5.220 | 3.643 |
| 1785914975 | 5.220 | 3.643 |
| 1785914976 | 4.075 | 4.992 |
| 1785914977 | 4.075 | 4.992 |
| 1785914978 | 4.075 | 5.420 |
| 1785914979 | 4.075 | 5.420 |

---

## 3. Loss — `loss_gre_pct`

**Inject:** L4 loss progression (`L4_loss_progression/iter_01`) — stepped NetEM loss (probe shows 0 ↔ 4%; series max on this iter 16%).

| ts_unix | loss_gre_pct | latency_gre_ms |
| ---: | ---: | ---: |
| 1785923389 | 0.000 | 0.287 |
| 1785923390 | 0.000 | 0.287 |
| 1785923391 | 4.000 | 0.257 |
| 1785923392 | 4.000 | 0.257 |
| 1785923393 | 4.000 | 0.257 |
| 1785923394 | 0.000 | 0.277 |
| 1785923395 | 0.000 | 0.277 |
| 1785923396 | 0.000 | 0.280 |
| 1785923397 | 0.000 | 0.280 |
| 1785923398 | 0.000 | 0.280 |

---

## 4. Util — `util_gre_mbps`

**Inject:** L5 util congestion (`L5_util_congestion/iter_07`) — recipe `8→32 Mbit` with **tc-ramp + plateau ≥40s**; live sidecar `util_ceil_schedule.jsonl` (`ramp` + `plateau` phases). Peak in slice ≈ **34.5 Mbps** (payload-ceil residency, not uncapped interface spikes).

**Contract:** Q1 util labels are **schedule-gated** (breach = first `htb_payload_ceil_mbps ≥ end_mbit`), not “eth0 looked busy while ceil was still low.”

| ts_unix | util_gre_mbps | latency_gre_ms |
| ---: | ---: | ---: |
| 1785929001 | 22.9054 | 0.681 |
| 1785929002 | 22.9054 | 0.681 |
| 1785929003 | 22.9054 | 0.681 |
| 1785929004 | 17.0842 | 0.533 |
| 1785929005 | 17.0842 | 0.533 |
| 1785929006 | 34.5069 | 0.499 |
| 1785929007 | 34.5069 | 0.499 |
| 1785929008 | 24.3030 | 0.560 |
| 1785929009 | 24.3030 | 0.560 |
| 1785929010 | 23.4795 | 0.497 |

---

## 5. Path asymmetry — `path_asymmetry`

**Inject:** L1 rain fade (`L1_rain_fade/iter_03`).

**This stamp:** `path_asymmetry` is derived at capture as **exact** `|latency_gre_ms − latency_eth0_ms|` (max abs err ~1e−14 across all 46 iters). The old controller@5s lag caveat applied to `full_variants_pi_20260803T175816Z` only — do not cite that mismatch for this campaign.

| ts_unix | path_asymmetry | \|gre−eth0\| (instant) | latency_gre_ms | latency_eth0_ms |
| ---: | ---: | ---: | ---: | ---: |
| 1785916249 | 17.616 | 17.616 | 17.874 | 0.258 |
| 1785916250 | 17.616 | 17.616 | 17.874 | 0.258 |
| 1785916251 | 25.177 | 25.177 | 25.439 | 0.262 |
| 1785916252 | 25.177 | 25.177 | 25.439 | 0.262 |
| 1785916253 | 25.177 | 25.177 | 25.439 | 0.262 |
| 1785916255 | 26.043 | 26.043 | 26.287 | 0.244 |
| 1785916256 | 26.043 | 26.043 | 26.287 | 0.244 |
| 1785916257 | 24.296 | 24.296 | 24.553 | 0.257 |
| 1785916258 | 21.774 | 21.774 | 22.041 | 0.267 |
| 1785916259 | 21.774 | 21.774 | 22.041 | 0.267 |

---

## 6. BGP flaps — `bgp_flap_count`

**Inject:** L3 BGP flap (`L3_bgp_flap/iter_01`) — cumulative counter; model uses rolling Δ, not the absolute level.

| ts_unix | bgp_flap_count | latency_gre_ms |
| ---: | ---: | ---: |
| 1785921480 | 0 | 0.302 |
| 1785921481 | 0 | 0.302 |
| 1785921482 | 8 | 0.250 |
| 1785921483 | 8 | 0.250 |
| 1785921484 | 8 | 0.299 |
| 1785921485 | 8 | 0.299 |
| 1785921486 | 8 | 0.299 |
| 1785921487 | 12 | 0.272 |
| 1785921488 | 12 | 0.272 |
| 1785921489 | 12 | 0.278 |

---

## 7. CPU / memory — `cpu_usage_user` / `cpu_usage_system` / `mem_used_percent`

**Inject:** L2 CPU stress (`L2_cpu_stress/iter_07`).

| ts_unix | cpu_usage_user | cpu_usage_system | mem_used_percent |
| ---: | ---: | ---: | ---: |
| 1785920871 | 14.50 | 16.03 | 8.56 |
| 1785920872 | 32.23 | 47.21 | 8.80 |
| 1785920873 | 72.36 | 10.30 | 8.85 |
| 1785920874 | 77.75 | 4.75 | 8.87 |
| 1785920875 | 77.53 | 7.07 | 8.87 |
| 1785920876 | 77.81 | 5.74 | 8.75 |
| 1785920877 | 78.36 | 18.41 | 9.06 |
| 1785920878 | 75.94 | 6.02 | 9.03 |
| 1785920880 | 76.83 | 9.32 | 9.01 |
| 1785920881 | 79.25 | 9.50 | 8.92 |

---

## 8. IPsec rekey — `ipsec_rekey_events_1h` / `ipsec_rekey_anomaly`

**Ambient** on L1 series (`L1_rain_fade/iter_01`) — threshold feature, not a dedicated rekey-storm inject (still on the post-campaign priority list).

| ts_unix | ipsec_rekey_events_1h | ipsec_rekey_anomaly |
| ---: | ---: | ---: |
| 1785914342 | 8 | 1 |
| 1785914343 | 8 | 1 |
| 1785914344 | 8 | 1 |
| 1785914345 | 8 | 1 |
| 1785914346 | 8 | 1 |
| 1785914347 | 8 | 1 |
| 1785914348 | 8 | 1 |
| 1785914349 | 8 | 1 |
| 1785914350 | 8 | 1 |
| 1785914351 | 8 | 1 |

---

## Timestamp gaps (all sections)

Raw captures often skip a single unix second (`…253 → …255`). Train/eval go through `align_1hz` (fill + interpolate) so windows are true 1 Hz; these sample tables intentionally show the raw gaps. Index-based ETA without align treats N rows as N seconds even when wall time is N+k.

---

## Full row shape (all columns on one series)

Every capture CSV shares this schema (example header):

```text
ts_unix,latency_gre_ms,latency_eth0_ms,jitter_gre_ms,loss_gre_pct,util_gre_mbps,
net_bytes_recv_eth0,net_bytes_sent_eth0,cpu_usage_system,cpu_usage_user,mem_used_percent,
bgp_flap_count,netflow_bulk_bytes,netflow_voice_bytes,ipsec_rekey_events_1h,
ipsec_rekey_anomaly,path_asymmetry
```
