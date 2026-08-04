# DECA SD-WAN — Master Policy Catalog (PS13)

Authoritative aerospace SD-WAN policies for the ISRO DECA lab simulation.
Organized by functional domain. Implementation bindings:

| Plane | Where it lives |
| --- | --- |
| AAR SLAs, hysteresis, conflict, human gate | `lab/deca_sdwan_controller.py` |
| **Edge layers (CE / PE / P)** — non-conflict ownership | [`EDGE_POLICY_LAYERS.md`](./EDGE_POLICY_LAYERS.md) · [`edge_policy_contract.json`](./edge_policy_contract.json) · `lab/audit_edge_policies.sh` |
| Classification / HTB / IPsec / VRF / OSPF-TE | `lab/deca_htb_qos.sh`, `lab/swanctl/*.conf`, FRR, expansion-boot |
| Traffic generation | **Pi:** iperf3 (`lab/deca_iperf_qos_traffic.sh`). **GNS3:** iperf3 + NetEM — [`shared_fault_book.json`](shared_fault_book.json) |
| HITL / predictive preemption / air-gap UI | `deca-backend` + dashboard Decide rail (fabric selector `pi` \| `gns3`) |
| Telemetry (Flow 2) | Dual collectors: Pi → Prom `:9090` · GNS3 → Prom `:9091` ([`lab/telemetry-pipeline/README.md`](../lab/telemetry-pipeline/README.md)) |
| Network topology & addressing | [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) · GNS3: [`lab/gns3/TOPOLOGY.md`](../lab/gns3/TOPOLOGY.md) |

Dashboard shows these as **read-only** Mission policy (no general policy editor).
Operators govern via **Approve / Reject** and manual `force_path` only.
**Same orchestrator + controller** for both fabrics; **SLA budgets aligned** (§1c).  
**Edge layers (CE / PE / P):** [`EDGE_POLICY_LAYERS.md`](./EDGE_POLICY_LAYERS.md) · [`edge_policy_contract.json`](./edge_policy_contract.json).

---

## 1. Application-Aware Routing (AAR) & SLA Policies

| Class | Match (PS13 wire) | VRF | Latency | Jitter | Loss | Primary | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **TT&C Telemetry** (critical command) | ToS **`0x88`** (136) / CS4-class | `vrf-mission` | ≤ **25 ms** | ≤ **5 ms** | ≤ **0.1%** | `gre-te-core` | `eth0` |
| **Mission Payload** (bulk / EO data) | ToS **`0x80`** (128) / AF41-class | `vrf-mission` | ≤ **80 ms** | ≤ **15 ms** | ≤ **2.0%** | `gre-te-core` | `eth0` |
| **Administrative / Default** | Untagged **BE / `0x00`** | `vrf-admin` *(PS13: vrf-default)* | — | — | — | **Pinned `eth0` only** | Never on mission MPLS core |

**iperf3 signatures (ARM-safe):**

```bash
iperf3 -u -b 1M  --tos 0x88   # TT&C
iperf3 -u -b 50M --tos 0x80   # Payload
iperf3 -b 20M                 # Admin (untagged)
```

Helper: `bash lab/deca_iperf_qos_traffic.sh start`

---

## 1b. Customer-Edge (CE) SLA tiers (ISRO mentor — Aug 2026)

Per-**CE** availability / CoS mapping used by Decide rogue/victim attribution. Class SLAs (§1) still bind the wire; CE tiers answer *which site* is Gold vs Bronze when they share a PE/WAN.

| CE netns | Site | SLA tier | Availability target | Default CoS | Role in demos |
| --- | --- | --- | --- | --- | --- |
| **`ce-a`** | NRSC Hyderabad | **Gold** | **99.9%** | TT&C `0x88` | Critical victim — never starve |
| **`ce-b`** | SAC Ahmedabad | **Silver** | **99.5%** | Payload `0x80` | DC bulk / peer |
| **`ce-mauritius`** | Mauritius (distant) | **Bronze** | **90%** | Payload `0x80` / BE | Typical **rogue** burst source |
| **`ce-mcf`** | MCF Hassan | **Bronze** | **90%** | Payload `0x80` / BE | Alternate rogue / regional |

### 1c. Dual-fabric SLA profiles (same Decide rail, **aligned budgets**)

One NOC · one controller push path · **same AAR + CE tier numbers** on Pi and GNS3 (mentor: Gold 99.9% vs Bronze 90%). Active fabric from `GET/POST /api/v1/fabric` still selects Prom + inject target.

| Class / CE | **Pi** (live stations) | **GNS3** (sim) |
| --- | --- | --- |
| TT&C latency / jitter / loss | ≤25 ms · ≤5 ms · ≤0.1% | **same** |
| Payload latency / jitter / loss | ≤80 ms · ≤15 ms · ≤2% | **same** |
| CE Gold (`ce-a` / NRSC) | 99.9% | **same** |
| CE Silver (`ce-b` / SAC) | 99.5% | **same** |
| CE Bronze (Mauritius / MCF) | 90% | **same** |

**Still fabric-local:** Prom port, link rates, node inventory, chaos tools.  
**Edge ownership (must not conflict):** network AAR · CE site tier · PE HTB/VRF/IPsec · P transit — see [`EDGE_POLICY_LAYERS.md`](./EDGE_POLICY_LAYERS.md).

Flow after Approve is identical: Decide → controller `:9280` → OSPF/`force_path` on the **active** fabric’s PE1.

**Pi as-applied:** [`lab/rpi/SLA.md`](../lab/rpi/SLA.md) · `lab/rpi/state/sla_active.json` · `bash lab/rpi/apply_sla_htb.sh`.  
**GNS3 as-applied:** [`lab/gns3/SLA.md`](../lab/gns3/SLA.md) · `lab/gns3/state/sla_active.json` · `bash lab/gns3/apply_sla_htb.sh`.  
**Audit both:** `bash lab/audit_edge_policies.sh`.

### CE↔CE SLA policy conflict

| Rule | Value |
| --- | --- |
| **Conflict condition** | Lower-tier CE util surge **and** higher-tier CE/path SLA at risk (latency↑, util→ceil, or `sdwan_policy_conflict=1`) |
| **Attribution** | Decide payload: `rogue_ce`, `victim_ce`, `victim_sla`, `rogue_sla` |
| **Alert class** | Prefer `policy_drift` (CE policy conflict) or `congestion_breach` with `root_cause=ce_sla_conflict` |
| **Actuation** | HITL Approve → protect victim (steer / throttle narrative); **no silent auto-remediate** |
| **Demo inject** | `bash scripts/inject_ce_sla_conflict.sh` then `bash scripts/demo_ce_sla_conflict_seed.sh` |

### CE bandwidth anomaly (NOC uptime — not a security appliance)

| Rule | Value |
| --- | --- |
| **Quiet baseline** | **2–3 Mbps** typical rural/edge CE (mentor analog) |
| **Surge fire** | Sustained **≥ 15 Mbps** (demo target **~20 Mbps**) for **N≥30** samples while peers stay near baseline |
| **Metric** | `ce_util_mbps{ce="ce-mauritius"|…}` from PE `veth-pe-*` (`lab/exporters/deca-ce-util.sh`) |
| **Detector** | `predictive/ce_surge_detect.py` → seed-preemption with rogue CE named |
| **Framing** | Network anomaly / abusive consumer / misconfig for **uptime** — not IDS/malware product |

### Multi-operator NOC

| Rule | Value |
| --- | --- |
| **Topology** | Many CEs → PEs → singular CORE → **one NOC** on brain |
| **Operators** | Multiple humans may watch the same Decide feed; Approve/Reject **audit** records operator identity when provided |
| **Priority** | Predictive ETA + SLA conflict over GUI polish |

---
## 2. Security & Overlay Data Plane Policies

| Policy | Rule |
| --- | --- |
| **Zero-Trust Encapsulation** | All WAN-bound mission traffic must be **IPsec ESP** (`deca-sdwan`). Cleartext transit across any underlay is strictly dropped. |
| **QoS preservation** | StrongSwan **`copy_dscp = out`** so outer ESP retains inner ToS (`0x88` / `0x80`) for PE HTB without decrypt. Templates: `lab/swanctl/`. |
| **Macro-Segmentation** | Strict VRF isolation: `vrf-mission` ⟂ `vrf-admin` (PS13 `vrf-default`). Zero route leakage. Check: `lab/deca_vrf_isolation_check.sh`. |
| **TT&C Fail-Closed** | If backup `eth0` path fails IPsec cryptographic negotiation, **TT&C is dropped** rather than sent unencrypted. |

---

## 3. Quality of Service (QoS) & Congestion Policies

| Policy | Lab binding | Behavior |
| --- | --- | --- |
| **Strict Priority (LLQ)** | HTB **`1:10`**, filter ToS **`0x88`** | TT&C bypasses standard congestion buffers. |
| **Bandwidth Policing** | HTB **`1:15`**, filter ToS **`0x80`**, **~70%** of link rate | Payload assured; policed if it starves TT&C. |
| **WRED / early drop** | RED qdisc on `1:15`; ceil ≈ **85%** of link | Proactive Payload drop under pressure. |
| **Scavenger** | HTB **`1:20`** default | Admin / untagged. |

Canonical installer: `FORCE=1 IF=eth0 bash lab/deca_htb_qos.sh` (also embedded in `deca-expansion-boot.sh`).

---

## 4. Failover & Controller State Machine Policies

| Policy | Value | Meaning |
| --- | --- | --- |
| **Degradation trigger (`enter_k`)** | **3** | Primary must violate class SLA for 3 consecutive polls. |
| **Stability recovery (`exit_k`)** | **10** | 10 consecutive clean polls before fail-back. |
| **Conflict preemption** | TT&C wins | Evicts Payload preference when TT&C needs backup; `sdwan_policy_conflict=1`. |
| **CE↔CE conflict** | Gold wins narrative | Bronze/Silver surge that endangers Gold → Decide `ce_sla_conflict` (see §1b). |
| **Poll interval** | **5 s** | Controller probe / decision loop. |

Human / AI gate (`POST /action`, localhost): `force_path` | `clear_force` | `reset_autonomy`.

---

## 5. Control Plane & Dynamic Routing Policies

| Policy | Rule |
| --- | --- |
| **Preferred / backup underlay** | `gre-te-core` OSPF **5**; `eth0` OSPF **50**. |
| **Route flap dampening** | >3 adjacency bounces / 60 s → suppress **15 min**. |
| **Geographic locality** | Higher local-pref for nearer ground station. |
| **TE** | OSPF-TE + pathd SR-TE BSID **40001** / **40002**. |
| **P role** | Singular CORE on station3 (`10.1.3.1`). Dual-P netns = design-only, not applied. |

---

## 6. AI Copilot & Operations Governance Policies

| Policy | Rule |
| --- | --- |
| **Q1 TTI** | Multi-head LSTM (latency / loss / jitter / util); Decide when **$T_{breach}$ &lt; 120 s** (warn band &lt; 180 s). |
| **Q2 Root cause** | XGBoost severity classifier (Prom → features → declare); path asymmetry + rekey in schema v2. |
| **Q3 Preemption** | HITL Approve → budgeted `bgp_soft_clear` (when applicable) then `force_path` (no silent auto-remediate). |
| **HITL timeout** | Sim wait **90 s** for Approve. |
| **Air-gap** | Local Ollama Phi-3 + ChromaDB runbooks; **no** outbound cloud / temporary WAN on brain. |

---

## Quick reference (live constants)

```
# Both fabrics (pi | gns3) — mentor-aligned (docs/edge_policy_contract.json)
TT&C:     lat≤25  jit≤5   loss≤0.1%   HTB 1:10   wire ToS 0x88 (136)
Payload:  lat≤80  jit≤15  loss≤2.0%   HTB 1:15   wire ToS 0x80 (128)  70%/WRED@85%
Admin:    BE/0x00  vrf-admin → eth0 only         HTB 1:20
CE SLA:   Gold ce-a 99.9% · Silver ce-b 99.5% · Bronze ce-mauritius/ce-mcf 90%
Layers:   network AAR · CE site tier · PE QoS/VRF/IPsec · P transit (EDGE_POLICY_LAYERS.md)
Chaos:    Pi iperf3+NetEM · GNS3 iperf3+NetEM · shared_fault_book.json (no TRex)

Surge:    baseline 2–3 Mbps → fire ≥15 Mbps (~20 demo) per CE
Hysteresis: enter_k=3  exit_k=10  poll=5s
IPsec: copy_dscp=out
Governance: T_breach=120s red / 180s warn  HITL=90s  air-gap=on
```