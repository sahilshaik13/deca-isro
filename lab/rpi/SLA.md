# Pi fabric — SLA profile (as applied)

Active when NOC **Simulation source = Pi** (`POST /api/v1/fabric` → `pi`).  
Same Decide rail / ToS / HTB / **SLA budgets as GNS3** (mentor-aligned).  
Edge roles: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md).

Runtime snapshot: [`state/sla_active.json`](./state/sla_active.json)  
Canonical policy: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md)  
Contract: [`docs/edge_policy_contract.json`](../../docs/edge_policy_contract.json)

## Application-Aware Routing (AAR) — Pi

| Class | Match (PS13 wire) | VRF | Latency | Jitter | Loss | Primary | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TT&C Telemetry** (critical command) | ToS **`0x88`** (136) / CS4-class | `vrf-mission` | ≤ **25 ms** | ≤ **5 ms** | ≤ **0.1%** | `gre-te-core` | `eth0` |
| **Mission Payload** (bulk / EO data) | ToS **`0x80`** (128) / AF41-class | `vrf-mission` | ≤ **80 ms** | ≤ **15 ms** | ≤ **2.0%** | `gre-te-core` | `eth0` |
| **Administrative / Default** | Untagged **BE / `0x00`** | `vrf-admin` | — | — | — | **Pinned `eth0` only** | Never on mission MPLS core |

**iperf3 signatures (ARM-safe):**

```bash
iperf3 -u -b 1M  --tos 0x88   # TT&C
iperf3 -u -b 50M --tos 0x80   # Payload
iperf3 -b 20M                 # Admin (untagged)
```

Helper: `bash lab/deca_iperf_qos_traffic.sh start`

## Customer-Edge (CE) SLA tiers — Pi

| CE netns | Site | SLA tier | Availability target | Default CoS | Role in demos |
| --- | --- | --- | --- | --- | --- |
| **`ce-a`** | NRSC Hyderabad | **Gold** | **99.9%** | TT&C `0x88` | Critical victim — never starve |
| **`ce-b`** | SAC Ahmedabad | **Silver** | **99.5%** | Payload `0x80` | DC bulk / peer |
| **`ce-mauritius`** | Mauritius (distant) | **Bronze** | **90%** | Payload / BE | Typical **rogue** burst source |
| **`ce-mcf`** | MCF Hassan | **Bronze** | **90%** | Payload / BE | Alternate rogue / regional |

## Dual-fabric comparison (aligned budgets)

| Class / CE | **Pi** | **GNS3** |
| --- | --- | --- |
| TT&C latency / jitter / loss | ≤25 ms · ≤5 ms · ≤0.1% | **same** |
| Payload latency / jitter / loss | ≤80 ms · ≤15 ms · ≤2% | **same** |
| CE Gold (`ce-a` / NRSC) | 99.9% | **same** |
| CE Silver (`ce-b` / SAC) | 99.5% | **same** |
| CE Bronze (Mauritius / MCF) | 90% | **same** |

## Edge roles (CE / PE / P)

| Role | Nodes | Policy job |
| --- | --- | --- |
| **CE** | `ce-a`, `ce-b`, `ce-mauritius`, `ce-mcf` | Site tier + default CoS; Bronze WAN tighter |
| **PE** | station1, station2 | HTB + VRF + IPsec + AAR actuate |
| **P** | station3 (CORE) | Transit only — **no HTB**; preserve DSCP |

## HTB — fabric-wide (stations + CE WAN)

| Classid | Role | ToS filter | Notes |
| --- | --- | --- | --- |
| **`1:10`** | TT&C LLQ | `0x88` | Strict priority |
| **`1:15`** | Payload | `0x80` | ~70% assured + RED |
| **`1:20`** | BE scavenger | default | Scavenger |

| Node | Interfaces | Link rate |
| --- | --- | --- |
| **station1** (PE1) | `eth0` WAN | 40 Mbit |
| **station2** (PE2) | `eth0` WAN | 40 Mbit |
| **ce-a** (Gold) | `veth-cea-pe` | 40 Mbit |
| **ce-b** (Silver) | `veth-ceb-pe` | 40 Mbit |
| **ce-mauritius** (Bronze) | `veth-cem-pe` | 20 Mbit *(skip if NetEM owns root)* |
| **ce-mcf** (Bronze) | `veth-cemcf-pe` | 20 Mbit |
| **station3** (CORE) | — | No HTB (P-router; CoS preserved via DSCP) |

```bash
bash lab/rpi/apply_sla_htb.sh
FABRIC=pi bash lab/audit_edge_policies.sh
```

Protocol capture Prom: **`http://127.0.0.1:9090`** (never `:9091`).

## Quick one-liner

```text
Pi TT&C: lat≤25  jit≤5   loss≤0.1%   HTB 1:10   wire ToS 0x88
Pi Pay:  lat≤80  jit≤15  loss≤2%     HTB 1:15   wire ToS 0x80
Pi Admin: pinned eth0 / vrf-admin    HTB 1:20   wire ToS 0x00
CE SLA:  Gold NRSC 99.9% · Silver SAC 99.5% · Bronze Mauritius/MCF 90%
```
