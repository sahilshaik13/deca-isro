# Prometheus Metric Glossary (DECA Lab → Q1 / Q2 / Q3)

**Dual Flow 2** — fabrics do not share a TSDB:

| Fabric | Prometheus | Kafka topic | Bridge | Primary scrape job |
| --- | --- | --- | --- | --- |
| **Pi** | host **`:9090`** | `sdwan_telemetry_pi` | `:9274` | `deca_kafka_telemetry_bridge` |
| **GNS3** | compose **`:9091`** | `sdwan_telemetry_gns3` | `:9276` | `deca_gns3_fabric` (+ `deca_kafka_telemetry_bridge_gns3`) |

Pi `:9090` also scrapes legacy Telegraf `:9273`, controller `:9280`, kafka-exporter `:9308`.  
GNS3 `:9091` scrapes bridge `:9276`, gns3-exporter `:9275`, kafka-exporter.  
ML / capture use `prom_url_for_fabric()` (`DECA_PROM_URL_PI` / `DECA_PROM_URL_GNS3`).

Predictive capture and Q3 snapshots prefer **bridge / fabric exporter** series (not legacy direct scrape alone).

## Path / SLA (Q1 golden signals)

| Metric | Meaning | Typical labels |
| --- | --- | --- |
| `sdwan_path_latency_ms` | PE probe RTT/latency (ms) | `host`, `path`=`gre`\|`eth0`, `src`=`edge` |
| `sdwan_path_jitter_ms` | Path jitter (ms) | `host`, `path` |
| `sdwan_path_loss_pct` | Path loss percent | `host`, `path`, `src` |
| `sdwan_path_util_mbps` | Through-path util (Mbps) — congestion/HTB signal | `host`, `path`=`gre`\|`eth0` |

**Pi SLAs:** TT&C GRE ≤ **25 ms** · jitter ≤ **5 ms** · Payload loss **2%**. Util near-ceil ~**38 Mbps**.  
**Aligned SLAs (Pi = GNS3):** TT&C ≤ **25 ms** · jitter ≤ **5 ms** · Payload loss **2%** · Gold **99.9%** (see policy §1c · [`EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md)).  
Red gate uses multi-head LSTM ETAs to those breaches on the **active** fabric.

Host labels: Pi `station1` · GNS3 `gns3-pe1` (+ `fabric="gns3"`).

## Asymmetry / rekey (PS13 Obj2)

| Metric | Meaning | Job |
| --- | --- | --- |
| `path_asymmetry` | \|GRE−eth0\| latency differential (ms) | `deca_sdwan_controller` on `:9090` (also derived in preprocess) |
| `ipsec_rekey_events_1h` | Rekey event count in rolling 1 h | bridge / edge exporter |
| `ipsec_rekey_anomaly` | Threshold anomaly flag (0/1) | bridge / edge exporter |
| `ipsec_sa_age_s` | SA age (when exported) | edge |

## Per-CE util / SLA conflict (mentor NOC)

| Metric | Meaning | Job |
| --- | --- | --- |
| `ce_util_mbps` | Per-CE attachment util (Mbps) from PE `veth-pe-*` | edge Telegraf (`deca-ce-util.sh`) / GNS3 exporter |

Decide fields (seed body, not Prom): `rogue_ce`, `victim_ce`, `rogue_sla`, `victim_sla`. Detector: `predictive/ce_surge_detect.py`.

## Interface / volume

| Metric | Meaning |
| --- | --- |
| `interface_net_bytes_recv` / `_sent` | Counters (often `ifName="eth0"`) — use rates/deltas in windows |
| `netflow_bulk_bytes` / `netflow_voice_bytes` | Softflow/IPFIX class volumes when exported |

## Node health (Q2)

| Metric | Meaning |
| --- | --- |
| `cpu_usage_system` / `cpu_usage_user` | PE CPU fractions (stress / crypto signature) |
| `mem_used_percent` | Memory pressure |
| `bgp_flap_count` | Cumulative flap/route-refresh counter; Q2 **3A/3B** use 1 Hz **rate** (Δ). See `bgp_instability.md` |

## Controller / mission

| Metric / API | Meaning |
| --- | --- |
| Controller `:9280/metrics` | Autonomy, force_path, conflict, path_asymmetry gauges (Pi Prom only) |
| `POST /action` ops | `force_path`, `bgp_soft_clear` (remediation one-shot), `reset_autonomy` |
| Mission JSON via orchestrator `/fleet` | `active_path`, `human_override`, path latency snapshot |
| `GET /api/v1/fabric` | Active fabric + per-fabric Prometheus URLs + SLA profile |

## Jobs

| Job | Target | Fabric |
| --- | --- | --- |
| `deca_kafka_telemetry_bridge` | `127.0.0.1:9274` | Pi (`:9090`) |
| `deca_kafka_telemetry_bridge_gns3` | compose `telemetry-bridge-gns3:9276` | GNS3 (`:9091`) |
| `deca_gns3_fabric` | `gns3-exporter:9275` | GNS3 (`:9091`) |
| `deca_edge_nodes` | `192.168.50.10/20:9273` | Pi |
| `deca_core_router` | `192.168.50.30:9273` | Pi |
| `deca_sdwan_controller` | `127.0.0.1:9280` | Pi |

## Ops tips for Q3 / RAG
- If Prom UI shows **No data points** with `out of bounds` logs on **`:9090`** → `bash lab/telemetry-pipeline/fix_prom_9090.sh --yes` (does not touch GNS3 `:9091`).
- Dual-stack verify: `bash lab/telemetry-pipeline/verify_dual_prom.sh`.
- Instant queries for Q3 snapshot should match `predictive/prom_export.py` PromQL so math and English share the same numbers.
- Campaign health: `data/deca/predictive/protocol/<stamp>/capture_health.json`.
- Runbook: [`dual_fabric_telemetry.md`](./dual_fabric_telemetry.md).
