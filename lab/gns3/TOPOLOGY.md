# DECA dual-fabric — Flow 1 aligned (Pi as-built + GNS3 scale)

One **SD-WAN orchestrator** (`:8000` / NOC `:3000`) and one **controller** (`:9280`)
serve **both** fabrics. Operator picks `pi` | `gns3`; **SLA budgets are aligned**
([§1c](../../docs/DECA_SDWAN_POLICY_RULES.md) · [EDGE_POLICY_LAYERS](../../docs/EDGE_POLICY_LAYERS.md)).
Chaos tools and path semantics follow the as-built Flow 1 below; full dual-fabric
mermaid (CE/PE/P + NOC) lives in **EDGE_POLICY_LAYERS**.

## End-to-end Flow 1 (traffic plane)

```text
Controller Approve / force_path ──pushes rules──► PE1 (active fabric)
                                                      │
Chaos: iperf3 (TCP/UDP ToS) · NetEM (lat/jit/loss) · CPU / BGP / util injects  
(**No TRex** — removed from DECA fabric / unified-model story)
                                                      │
        ┌───────────────── Branch site (station1) ────┴──────────────┐
        │  CE NRSC + CE Mauritius → HTB (1:10 TT&C / 1:15 Payload /  │
        │  1:20 BE) → AAR + IPsec ESP (deca-sdwan, copy_dscp=out)    │
        └───────────────────────────┬────────────────────────────────┘
                                    │ encrypted SD-WAN tunnel
                                    ▼
        ┌───────────────── Provider MPLS on GRE ─────────────────────┐
        │  PE1 ──► vrf-mission (GRE+LDP preferred) ──► P CORE        │
        │       └► vrf-admin  (eth0 underlay backup) ──► PE2         │
        │  Also: OSPF adjacency PE↔CORE and PE↔PE                    │
        │  pathd SR-TE BSID 40001 preferred / 40002 backup           │
        └───────────────────────────┬────────────────────────────────┘
                                    │ decrypt + deliver
                                    ▼
        ┌──────────── DC / Hub (station2) ───────────────────────────┐
        │  CE SAC (datacenter) · CE MCF (hub)                        │
        └────────────────────────────────────────────────────────────┘
```

**Pi as-built:** single CORE `10.1.3.1`, PE1 `10.1.1.1`, PE2 `10.1.2.1`.  
**GNS3:** same Flow 1 roles; may add PE3 / extra CEs / CORE-S for scale — mission
path remains PE → **CORE-N (primary P)** → PE; CORE-S optional dual-P.

## Rebuild GNS3 canvas

```bash
python3 lab/gns3/build_deca_topology.py --wipe
# Refresh DECA in GNS3 → Start all
```

## Nodes (GNS3 scale map)

| Role | Nodes |
| --- | --- |
| P / CORE | `CORE-N` (primary = Pi CORE) · `CORE-S` (optional dual) |
| PE | `PE1` · `PE2` · `PE3` |
| Branch CEs | `CE-NRSC` · `CE-Mauritius` · `CE-Shadnagar` |
| DC / Hub CEs | `CE-SAC` · `CE-MCF` · `CE-ISTRAC` · `CE-ISRO-HQ` · `CE-Bhopal` |
| Chaos | `IPERF-A` · `IPERF-B` (+ NetEM / CPU / BGP via NOC inject) |

## Path types

| Lane | Links | Mermaid |
| --- | --- | --- |
| **vrf-mission** | PE ↔ CORE-N/S | MPLS/LDP over GRE |
| **vrf-admin** | PE ↔ PE direct | eth0 backup / scavenger |
| **IPsec overlay** | PE1 ↔ PE2 (config) | ESP `deca-sdwan` |
| **Chaos inject** | IPERF-A→CE-NRSC LAN, IPERF-B→CE-SAC LAN; NetEM on PE1→CORE; shared fault book with Pi | Flow 1 Chaos box |

## Dual-fabric SLAs (Decide — **aligned** budgets)

| | Pi | GNS3 |
| --- | --- | --- |
| TT&C | ≤25 ms / 5 ms / 0.1% | **same** |
| Payload | ≤80 ms / 15 ms / 2% | **same** |
| Gold CE | 99.9% | **same** |
| Bronze CE | 90% | **same** |

Edge layers (CE / PE / P): [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md).  
Full GNS3 AAR + HTB: [`SLA.md`](./SLA.md) · `bash lab/gns3/apply_sla_htb.sh` · `bash lab/audit_edge_policies.sh`.

## Chaos commands

```bash
bash lab/gns3/chaos_layer.sh status
# IPERF-A (behind CE-NRSC): apk add iperf3 && iperf3 -u -b 1M --tos 0x88 -c <IPERF-B on CE-SAC>
# NOC:     Simulation source = GNS3 → Rain fade / Loss / CE SLA …
```

## Flow 2 / 3 (dual-fabric collectors)

| Fabric | Kafka topic | Bridge | Prometheus |
| --- | --- | --- | --- |
| Pi | `sdwan_telemetry_pi` | `:9274` | host `:9090` |
| GNS3 | `sdwan_telemetry_gns3` | `:9276` | compose `:9091` (+ exporter `:9275`) |

Telemetry → Kafka (per fabric) → Prom → Q1/Q2 gate → Decide → **Approve** →
controller on the **active** fabric’s PE1. See [`lab/telemetry-pipeline/README.md`](../telemetry-pipeline/README.md).
