# Dual-fabric telemetry (Flow 2) — Pi + GNS3

Same NOC / Decide / Q1–Q2 gate; **separate collectors and Prometheus** so fabrics stay distinguished.

## Architecture

```text
Pi stations:  snmpd · syslog BGP/OSPF · softflowd IPFIX · 1Hz GRE/eth0 probes
              → Telegraf fabric=pi → Kafka sdwan_telemetry_pi → bridge :9274
              → Host Prometheus :9090  (Pi only; also scrapes controller :9280)

GNS3 fabric:  chaos/probe + gns3-exporter · (optional in-node snmpd/syslog)
              → telegraf-gns3 fabric=gns3 → Kafka sdwan_telemetry_gns3 → bridge :9276
              → Compose Prometheus :9091  (+ scrape gns3-exporter :9275)
```

Shared Kafka broker (`:9092`). ML picks Prom via `DECA_PROM_URL_PI` / `DECA_PROM_URL_GNS3`
(`predictive.prom_export.prom_url_for_fabric()`). Active fabric: `GET/POST /api/v1/fabric`.

## Ports

| Port | Role |
| --- | --- |
| 9090 | Host Prom — **Pi** |
| 9091 | Compose Prom — **GNS3** |
| 9092 | Kafka EXTERNAL |
| 9274 | Pi Kafka→Prom bridge |
| 9275 | GNS3 path exporter (1Hz) |
| 9276 | GNS3 Kafka→Prom bridge |
| 9280 | SD-WAN controller (scraped by `:9090` only) |
| 9308 | Kafka exporter |

## PromQL / jobs

| Fabric | Primary job | Host label | Prom |
| --- | --- | --- | --- |
| Pi | `deca_kafka_telemetry_bridge` | `station1` | `:9090` |
| GNS3 | `deca_gns3_fabric` | `gns3-pe1` | `:9091` |

Same metric names (`sdwan_path_latency_ms`, loss, jitter, util, CPU, `bgp_flap_count`, …).
GNS3 series also carry `fabric="gns3"`.

## Ops

```bash
cd lab/telemetry-pipeline && docker compose up -d
bash lab/telemetry-pipeline/verify_dual_prom.sh
bash lab/telemetry-pipeline/install_edge.sh station1   # Pi topic sdwan_telemetry_pi
bash lab/gns3/telemetry/install_gns3_edge.sh           # optional in-node agents
```

If host `:9090` shows out-of-bounds: `bash lab/telemetry-pipeline/fix_prom_9090.sh --yes` (sudo).
GNS3 `:9091` is unaffected.

## Docs

- [`lab/telemetry-pipeline/README.md`](../../lab/telemetry-pipeline/README.md)
- [`lab/gns3/TOPOLOGY.md`](../../lab/gns3/TOPOLOGY.md)
- [`docs/DECA_SDWAN_PROCESS_FLOW.md`](../../docs/DECA_SDWAN_PROCESS_FLOW.md) §2.1
- [`prom_metric_glossary.md`](./prom_metric_glossary.md)
- [`unified_dual_architecture_ml.md`](./unified_dual_architecture_ml.md) — shared LSTM + fabric Q2
