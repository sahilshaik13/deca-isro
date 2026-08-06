# GNS3 fabric — SLA profile (as applied)

Active when NOC **Simulation source = GNS3** (`POST /api/v1/fabric` → `gns3`).  
Same Decide rail / ToS / HTB / **SLA budgets as Pi** (mentor-aligned).  
Edge roles: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md).

Runtime snapshot: [`state/sla_active.json`](./state/sla_active.json)  
Canonical policy: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md)  
Contract: [`docs/edge_policy_contract.json`](../../docs/edge_policy_contract.json)

## Application-Aware Routing (AAR) — GNS3

| Class | Match (PS13 wire) | VRF | Latency | Jitter | Loss | Primary | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TT&C Telemetry** (critical command) | ToS **`0x88`** (136) / CS4-class | `vrf-mission` | ≤ **25 ms** | ≤ **5 ms** | ≤ **0.1%** | `gre-te-core` | `eth0` |
| **Mission Payload** (bulk / EO data) | ToS **`0x80`** (128) / AF41-class | `vrf-mission` | ≤ **80 ms** | ≤ **15 ms** | ≤ **2.0%** | `gre-te-core` | `eth0` |
| **Administrative / Default** | Untagged **BE / `0x00`** | `vrf-admin` | — | — | — | **Pinned `eth0` only** | Never on mission MPLS core |

**iperf3 signatures (GNS3 IPERF-A → IPERF-B):**

```bash
iperf3 -u -b 1M  --tos 0x88   # TT&C
iperf3 -u -b 50M --tos 0x80   # Payload
iperf3 -b 20M                 # Admin (untagged)
```

## Customer-Edge (CE) SLA tiers — GNS3

| CE | Site | SLA tier | Availability target | Default CoS | Role in demos |
| --- | --- | --- | --- | --- | --- |
| **`ce-a` / CE-NRSC** | NRSC Hyderabad | **Gold** | **99.9%** | TT&C `0x88` | Critical victim — never starve |
| **`ce-b` / CE-SAC** | SAC Ahmedabad | **Silver** | **99.5%** | Payload `0x80` | DC bulk / peer |
| **`ce-mauritius`** | Mauritius (distant) | **Bronze** | **90%** | Payload / BE | Typical **rogue** burst source |
| **`ce-mcf` / CE-MCF** | MCF Hassan | **Bronze** | **90%** | Payload / BE | Alternate rogue / regional |

## Dual-fabric comparison (aligned budgets)

| Class / CE | **Pi** | **GNS3** |
| --- | --- | --- |
| TT&C latency / jitter / loss | ≤25 ms · ≤5 ms · ≤0.1% | **same** |
| Payload latency / jitter / loss | ≤80 ms · ≤15 ms · ≤2% | **same** |
| CE Gold (`ce-a` / NRSC) | 99.9% | **same** |
| CE Silver (`ce-b` / SAC) | 99.5% | **same** |
| CE Bronze (Mauritius / MCF) | 90% | **same** |

What still differs: link rates, node count, chaos tools, Prom port (`:9091`).

## Edge roles (CE / PE / P)

| Role | Nodes | Policy job |
| --- | --- | --- |
| **CE** | CE-NRSC, CE-SAC, CE-Mauritius, CE-MCF, … | Site tier + default CoS; Bronze WAN tighter |
| **PE** | PE1, PE2, PE3 | HTB + VRF + IPsec + AAR actuate |
| **P** | CORE-N, CORE-S | Transit; may enforce same HTB PHB; **never re-mark ToS** |

## HTB — fabric-wide (all PE / CE / CORE)

| Classid | Role | ToS filter | Notes |
| --- | --- | --- | --- |
| **`1:10`** | TT&C LLQ | `0x88` | Strict priority |
| **`1:15`** | Payload | `0x80` | ~70% assured |
| **`1:20`** | BE scavenger | `0x00` | Default |

| Node role | Interfaces | Link rate |
| --- | --- | --- |
| **PE1 / PE2** | CORE + CE WAN (`eth0`, `eth4`) | 100 Mbit |
| **PE3** | CORE / admin / CE stubs | 100 Mbit |
| **CORE-N / CORE-S** | PE-facing (`eth0`, `eth1`) | 100 Mbit |
| **Gold CE** (NRSC) | WAN `eth0` | 100 Mbit |
| **Silver CE** (SAC) | WAN `eth0` | 100 Mbit |
| **Bronze CEs** (Mauritius, MCF, Shadnagar, Bhopal) | WAN `eth0` | **40 Mbit** (rogue bursts hit scavenger first) |
| **Regional CEs** (ISTRAC, ISRO-HQ) | WAN `eth0` | 60 Mbit |

```bash
bash lab/gns3/apply_sla_htb.sh
FABRIC=gns3 bash lab/audit_edge_policies.sh
```

## Quick one-liner

```text
GNS3 TT&C: lat≤25  jit≤5   loss≤0.1%   HTB 1:10   wire ToS 0x88
GNS3 Pay:  lat≤80  jit≤15  loss≤2%     HTB 1:15   wire ToS 0x80
GNS3 Admin: pinned eth0 / vrf-admin    HTB 1:20   wire ToS 0x00
CE SLA:    Gold NRSC 99.9% · Silver SAC 99.5% · Bronze Mauritius/MCF 90%
```
