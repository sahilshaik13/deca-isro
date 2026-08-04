# SD-WAN air-gapped telemetry pipeline (IaC) — dual Flow 2

**Pi fabric:** Edge Telegraf → Kafka `sdwan_telemetry_pi` → bridge `:9274` → **host Prometheus `:9090`**

**GNS3 fabric:** telegraf-gns3 → Kafka `sdwan_telemetry_gns3` → bridge `:9276` → **compose Prometheus `:9091`**  
(+ `gns3-exporter` `:9275` scraped only by `:9091`)

Shared Kafka broker; **separate topics, bridges, and Prometheus** so fabrics stay distinguished. ML picks Prom by active fabric (`DECA_PROM_URL_PI` / `DECA_PROM_URL_GNS3`).

## One-time brain install (needs your sudo password)

```bash
bash lab/telemetry-pipeline/install_brain.sh
```

| Port | Service |
| --- | --- |
| **9090** | Host Prometheus — **Pi only** |
| **9091** | Compose Prometheus — **GNS3 only** |
| **9092** | Kafka (Pis + compose producers) |
| **9274** | Pi Kafka→Prom bridge |
| **9275** | GNS3 path exporter (1Hz PROBE) |
| **9276** | GNS3 Kafka→Prom bridge |
| **9308** | Kafka broker exporter |

## Edge (Pis) — re-run after topic rename

```bash
bash lab/telemetry-pipeline/install_edge.sh station1
bash lab/telemetry-pipeline/install_edge.sh station2
```

Raw sources (mermaid Flow 2): **snmpd**, **syslog** BGP/OSPF → `:5514`, **softflowd** IPFIX, **1Hz** GRE/eth0 probes via `sdwan_tunnel_stats.sh`.  
Tags: `fabric=pi`, topic `sdwan_telemetry_pi`.

## GNS3 collectors (before Flow 1 traffic)

```bash
cd lab/telemetry-pipeline && docker compose up -d
bash lab/gns3/telemetry/install_gns3_edge.sh   # optional in-node snmpd/syslog stubs
```

Primary path today: chaos state → `telegraf-gns3` + `gns3-exporter` → `:9091`.

## Edge continuous probing (PE-local, Pi)

1. Telegraf `inputs.exec` every **1s** runs `/usr/local/bin/sdwan_tunnel_stats.sh`
2. ICMP-probes **`gre-te-core`** and **`eth0`** toward the peer PE
3. Emits Influx `sdwan_path_latency_ms` / `sdwan_path_loss_pct` (`src=edge`)
4. `outputs.kafka` → `sdwan_telemetry_pi` → bridge → `:9090`

## Layout

| File | Role |
| --- | --- |
| `docker-compose.yml` | Kafka, dual bridges, telegraf-gns3, gns3-exporter, Prom :9091 |
| `telegraf.conf` | Pi edge → `sdwan_telemetry_pi` |
| `telegraf.gns3.conf` | GNS3 edge → `sdwan_telemetry_gns3` |
| `telegraf.bridge.conf` | Pi consumer → `:9274` |
| `telegraf.bridge.gns3.conf` | GNS3 consumer → `:9276` |
| `host-prometheus.yml` | Pi-only scrape for `:9090` |
| `prometheus.yml` | GNS3-only scrape for `:9091` |
| `setup_softflowd.sh` | Pi `eth0` + `gre-te-core` → `127.0.0.1:2055` |

## Verify

```bash
# Pi (host)
bash lab/telemetry-pipeline/apply_host_prometheus.sh   # needs sudo
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="deca_kafka_telemetry_bridge"}'
curl -s 'http://127.0.0.1:9090/api/v1/query?query=up{job="deca_sdwan_controller"}'

# GNS3 (compose)
curl -s 'http://127.0.0.1:9091/api/v1/query?query=up{job="deca_gns3_fabric"}'
curl -s 'http://127.0.0.1:9091/api/v1/query?query=up{job="deca_kafka_telemetry_bridge_gns3"}'
```

Do not scrape the SD-WAN controller from Docker — hairpin to host `:9280` fails; host Prom uses `127.0.0.1:9280`.

## Predictive / Decide consumers

| Fabric | Prometheus | Env |
| --- | --- | --- |
| Pi | `:9090` | `DECA_PROM_URL_PI` (or legacy `DECA_PROM_URL`) |
| GNS3 | `:9091` | `DECA_PROM_URL_GNS3` |

`predictive.prom_export.prom_url_for_fabric()` selects the base from active fabric. Metric glossary: [`deca-backend/runbooks/prom_metric_glossary.md`](../../deca-backend/runbooks/prom_metric_glossary.md).
