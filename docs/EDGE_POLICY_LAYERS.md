# DECA edge policy layers (CE / PE / P / network)

Mentor-aligned hierarchical policies so edges **do not conflict**.  
Same wire IDs and SLA budgets on **Pi and GNS3** (Aug 2026: Gold 99.9% vs Bronze 90%; CoS1 on MPLS; name rogue vs victim).

**Machine contract:** [`edge_policy_contract.json`](./edge_policy_contract.json)  
**Master catalog:** [`DECA_SDWAN_POLICY_RULES.md`](./DECA_SDWAN_POLICY_RULES.md) §1–§3  
**Audit:** `bash lab/audit_edge_policies.sh` · `FABRIC=pi|gns3|both`

**NOC (no GNS3 GUI):** Simulation source → Traffic Start → Simple fault → map/telemetry → Decide.  
APIs: `GET /api/v1/topology` · `POST /api/v1/traffic/start|stop` · fabric-aware `/fleet` + `/dashboard`.

---

## Conflict rule (top)

**More specific never overrides more critical.**

```text
TT&C / Gold  >  Payload / Silver  >  Admin / Bronze
```

Network AAR sets *path intent*; CE marks *site priority*; PE *enforces* QoS/VRF/IPsec; P *forwards without reclassifying*.

### Complete dual-fabric map (Pi + GNS3)

Same **network** policy plane and **wire contract** for both fabrics; only hardware / scale and Prom ports differ.

```mermaid
flowchart TB
  %% ========== SHARED NETWORK POLICY ==========
  subgraph NET["NETWORK POLICY — one NOC · one Decide · one controller :9280"]
    NOC["NOC UI :3000 · Orchestrator :8000"]
    DEC["Decide rail · HITL Approve/Reject"]
    AAR["AAR class SLAs · hysteresis enter_k=3 exit_k=10"]
    CTRL["Controller force_path / clear_force"]
    PRI["Priority: TT&C/Gold > Payload/Silver > Admin/Bronze"]
    NOC --> DEC --> AAR --> CTRL
    PRI -.-> AAR
  end

  CONTRACT["SHARED WIRE CONTRACT<br/>ToS 0x88→HTB 1:10 · 0x80→1:15 · 0x00→1:20<br/>vrf-mission · vrf-admin · IPsec copy_dscp<br/>TT&C≤25/5/0.1% · Gold 99.9% · Bronze 90%"]

  NET --> CONTRACT

  %% ========== PI FABRIC ==========
  subgraph PI["PI FABRIC — live stations · Prom :9090 · Kafka sdwan_telemetry_pi"]
    direction TB

    subgraph PICE["CE layer — site SLA + default CoS"]
      CEA["ce-a NRSC · Gold 99.9% · ToS 0x88"]
      CEB["ce-b SAC · Silver 99.5% · ToS 0x80"]
      CEM["ce-mauritius · Bronze 90% · rogue"]
      CEMCF["ce-mcf · Bronze 90%"]
    end

    subgraph PIPE["PE layer — HTB + VRF + IPsec + AAR actuate"]
      PE1P["station1 PE1<br/>HTB eth0 · IPsec · VRF"]
      PE2P["station2 PE2<br/>HTB eth0 · IPsec · VRF"]
    end

    subgraph PIP["P layer — transit only · no HTB · preserve DSCP"]
      COREP["station3 CORE 10.1.3.1<br/>OSPF + LDP + GRE · no reclassify"]
    end

    CEA -->|"WAN"| PE1P
    CEM -->|"WAN"| PE1P
    CEB -->|"WAN"| PE2P
    CEMCF -->|"WAN"| PE2P
    PE1P -->|"vrf-mission gre-te-core OSPF 5"| COREP
    COREP -->|"vrf-mission"| PE2P
    PE1P -.->|"vrf-admin eth0 OSPF 50 backup"| PE2P
  end

  %% ========== GNS3 FABRIC ==========
  subgraph GNS["GNS3 FABRIC — sim scale · Prom :9091 · Kafka sdwan_telemetry_gns3"]
    direction TB

    subgraph GCE["CE layer — same tiers · extra regional CEs"]
      GNRSC["CE-NRSC · Gold 99.9%"]
      GSAC["CE-SAC · Silver 99.5%"]
      GMAU["CE-Mauritius · Bronze 90% · rogue"]
      GMCF["CE-MCF · Bronze 90%"]
      GX["CE-Shadnagar · ISTRAC · ISRO-HQ · Bhopal"]
    end

    subgraph GPE["PE layer — same HTB/VRF/IPsec jobs"]
      GPE1["PE1"]
      GPE2["PE2"]
      GPE3["PE3 · stubs / scale"]
    end

    subgraph GP["P layer — preserve DSCP · may apply same HTB PHB · never remap ToS"]
      GCN["CORE-N · primary P"]
      GCS["CORE-S · optional dual-P"]
    end

    GNRSC --> GPE1
    GMAU --> GPE1
    GSAC --> GPE2
    GMCF --> GPE2
    GX --> GPE3
    GPE1 -->|"vrf-mission GRE/MPLS"| GCN
    GCN --> GPE2
    GPE1 -.->|"vrf-admin eth0 backup"| GPE2
    GCN -.-> GCS
    GPE3 -.-> GCN
  end

  CONTRACT --> PI
  CONTRACT --> GNS

  CTRL -->|"active fabric = pi"| PE1P
  CTRL -->|"active fabric = gns3"| GPE1

  %% ========== TELEMETRY + ML ==========
  subgraph TEL["FLOW 2 / 3 — shared Q1 · fabric-selected Q2"]
    PROM_PI["Prom :9090"]
    PROM_G["Prom :9091"]
    ML["Q1 LSTM · Q2 XGBoost · Decide preemption"]
  end

  PE1P & PE2P & COREP --> PROM_PI --> ML
  GPE1 & GPE2 & GCN --> PROM_G --> ML
  ML -->|"ETA / CE conflict rogue vs victim"| DEC
```

### Layer ownership (same jobs on both sides of the diagram)

| Layer | Owns | Must NOT do |
| --- | --- | --- |
| **Network** | Class SLAs, hysteresis (`enter_k=3` / `exit_k=10`), conflict / HITL, `force_path` | Per-packet QoS |
| **CE** | Site tier (Gold / Silver / Bronze), default CoS, “don’t starve Gold” | Choose CORE vs eth0 |
| **PE** | Mark→HTB (`1:10` / `1:15` / `1:20`), VRF (`vrf-mission` / `vrf-admin`), IPsec `copy_dscp`, AAR steer | Invent new classes |
| **P (CORE)** | Forward mission underlay, keep DSCP, TE costs | Re-mark ToS / run CE SLA logic |

**P nuance:** Pi CORE has no HTB (pure transit). GNS3 CORE may apply the **same** HTB PHB for demo realism — still **no remapping** of ToS.

---

## Shared wire + SLA (both fabrics)

| Class | ToS | HTB | VRF | Latency | Jitter | Loss | Primary | Backup |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **TT&C** | `0x88` | `1:10` | `vrf-mission` | ≤25 ms | ≤5 ms | ≤0.1% | `gre-te-core` | `eth0` |
| **Payload** | `0x80` | `1:15` | `vrf-mission` | ≤80 ms | ≤15 ms | ≤2% | `gre-te-core` | `eth0` |
| **Admin** | `0x00` | `1:20` | `vrf-admin` | — | — | — | `eth0` only | — |

| CE | Site | Tier | Availability | Default CoS | Demo role |
| --- | --- | --- | --- | --- | --- |
| `ce-a` / CE-NRSC | NRSC | **Gold** | **99.9%** | `0x88` | Critical victim |
| `ce-b` / CE-SAC | SAC | **Silver** | **99.5%** | `0x80` | DC bulk |
| `ce-mauritius` | Mauritius | **Bronze** | **90%** | `0x80` / BE | Typical rogue |
| `ce-mcf` | MCF | **Bronze** | **90%** | `0x80` / BE | Alternate rogue |

---

## Non-conflict matrix

| If this happens… | Winner | Mechanism |
| --- | --- | --- |
| TT&C and Payload both want backup | **TT&C** | `sdwan_policy_conflict` preemption |
| Bronze CE surges vs Gold CE | **Gold** | Decide `rogue_ce` / `victim_ce` · CE↔CE conflict |
| Admin / BE vs mission congestion | **Mission** | Admin pinned `vrf-admin`; scavenger `1:20` |
| CE default CoS vs network class SLA | **Network class** | CE suggests mark; PE enforces AAR table |
| P sees congestion | **Don’t reclassify** | Queue/drop under existing PHB only |

---

## Apply + audit (both fabrics)

| Fabric | Apply HTB | Snapshot | Prom |
| --- | --- | --- | --- |
| **Pi** | `bash lab/rpi/apply_sla_htb.sh` | `lab/rpi/state/sla_active.json` | `:9090` |
| **GNS3** | `bash lab/gns3/apply_sla_htb.sh` | `lab/gns3/state/sla_active.json` | `:9091` |

```bash
# After Start-all / stations up:
bash lab/rpi/apply_sla_htb.sh
bash lab/gns3/apply_sla_htb.sh
bash lab/audit_edge_policies.sh          # both if reachable
FABRIC=gns3 bash lab/audit_edge_policies.sh
```

Backend loads the same budgets via `deca-backend/fabric.py` → `GET /api/v1/fabric` (from `edge_policy_contract.json`).

---

## Mentor one-liner

> Policies are hierarchical: network AAR, CE site SLA, PE QoS/VRF/IPsec, P transit-only — **identical roles and numbers on Pi and GNS3** so Gold/TT&C always wins and the NOC can name the rogue vs victim.
