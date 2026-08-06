# DECA-ISRO

**Distributed Enterprise Connectivity Anomaly (DECA)** — aerospace SD-WAN lab on three Raspberry Pis + laptop/desktop orchestrator (**air-gapped**).

Aligned to [PS13](docs/PROBLEM_STATEMENT_13.md). Canonical as-built narrative: [`docs/DECA_SDWAN_PROCESS_FLOW.md`](docs/DECA_SDWAN_PROCESS_FLOW.md).

---

## What you get

| Layer | Role |
| --- | --- |
| **Pi fabric** | PE1 / PE2 / **single CORE P** — 4 CEs (NRSC, Mauritius, SAC, MCF) · VRF · GRE/MPLS-LDP · IPsec · HTB QoS · SR-TE/pathd |
| **GNS3 fabric** | Scaled sim (16+ nodes) · same Flow 1 semantics · iperf3 + NetEM · external drive |
| **SD-WAN controller** | AAR path select · human `force_path` · remediation `bgp_soft_clear` · `:9280` |
| **Orchestrator UI** | Dashboard + Decide Approve/Reject · fabric selector · Q3 NLP · topology blast-radius · `:3000` / API `:8000` |
| **Telemetry IaC** | Dual Flow 2: Pi → Kafka `sdwan_telemetry_pi` → Prom `:9090` · GNS3 → `sdwan_telemetry_gns3` → Prom `:9091` |
| **Predictive** | Shared Q1 LSTM + fabric-selected Q2 XGBoost · fabric-aware Prom · protocol campaign schema v2 |

---

## Docs

| Doc | Purpose |
| --- | --- |
| [`docs/EDGE_POLICY_LAYERS.md`](docs/EDGE_POLICY_LAYERS.md) | **Complete policy catalog** — AAR / CE / QoS / security / failover / layers |
| [`docs/DECA_SDWAN_PROCESS_FLOW.md`](docs/DECA_SDWAN_PROCESS_FLOW.md) | End-to-end architecture + PS13 scoreboard |
| [`docs/DECA_PREDICTIVE_ENGINE_PLAN.md`](docs/DECA_PREDICTIVE_ENGINE_PLAN.md) | Q1/Q2/Q3 predictive status |
| [`docs/JURY_DUAL_FABRIC_DEMO.md`](docs/JURY_DUAL_FABRIC_DEMO.md) | Jury dual-fabric demo script |
| [`docs/PROBLEM_STATEMENT_13_FINDINGS.md`](docs/PROBLEM_STATEMENT_13_FINDINGS.md) | Honest done vs remaining |
| [`docs/STATION_NETWORK_SETUP.md`](docs/STATION_NETWORK_SETUP.md) | Addressing / CE-PE-P map |
| [`lab/telemetry-pipeline/README.md`](lab/telemetry-pipeline/README.md) | Dual Flow 2 collectors |
| [`lab/gns3/TOPOLOGY.md`](lab/gns3/TOPOLOGY.md) | GNS3 Flow 1 topology |
| [`predictive/README.md`](predictive/README.md) | Protocol capture · train · live gate |
| [`lab/README.md`](lab/README.md) | Day-to-day Pi ops |
| [`DECA_ORCHESTRATOR_README.md`](DECA_ORCHESTRATOR_README.md) | FastAPI + Next.js |

---

## Quick status commands

```bash
# Campaign
cat data/deca/predictive/protocol/ACTIVE_STAMP.json
cat data/deca/predictive/protocol/20260729T202832Z/capture_health.json
systemctl --user status deca-protocol-campaign.service deca-protocol-watchdog.service

# Live cutover gate
bash predictive/launch_infer_q1_q2_cutover.sh --seconds 0

# Lab
check stations   # or: bash lab/deca_ops.sh check
bash lab/deca_te_verify.sh
```

**Active full protocol stamp:** `20260729T202832Z` (schema v2) · boot autostart enabled · ETA finish ~2026-08-03 → retrain.
