# PROBLEM STATEMENT 13 — Perimeter (alignment reference)

**Role of this file:** immutable **scope perimeter** for DECA vs the official brief.  
Use it to cross-check whether work, demos, and docs stay inside (or honestly disclose gaps against) the problem statement.  
**Do not** put status or “done” claims here — those live in [`PROBLEM_STATEMENT_13_FINDINGS.md`](./PROBLEM_STATEMENT_13_FINDINGS.md).

| Companion | Purpose |
| --- | --- |
| **This file** | What the problem asks for (requirements, outcomes, phases, dataset) |
| [`PROBLEM_STATEMENT_13_FINDINGS.md`](./PROBLEM_STATEMENT_13_FINDINGS.md) | What we have / don’t have (honest scoreboard) |
| [`NETWORK_EXPANSION_FINDINGS.md`](./NETWORK_EXPANSION_FINDINGS.md) | Lab Obj-1 expansion evidence |
| [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) | Authoritative station topology restore |

**How to use for alignment checks**

1. Pick an objective / phase / dataset bullet below (stable IDs: `PS13-O*`, `PS13-P*`, `PS13-D*`, `PS13-Q*`).
2. Ask: does current code, lab, or demo satisfy it? Cite FINDINGS, not this file.
3. If we substitute (e.g. Pi lab instead of EVE-NG), the substitution must be explicit in FINDINGS — the perimeter text still stands as written.
4. Promoted classifier `models/fault_classifier/` is outside casual edits; never treat model rewrites as “closing” a perimeter item without an experiment FINDINGS trail.

---

# PROBLEM STATEMENT 13  
## Air-Gapped Predictive Copilot for Secure MPLS Operations

### Description

Modern enterprise and government networks increasingly rely on SD-WAN deployments running over MPLS underlays to deliver resilient, application-aware connectivity across distributed branches, datacenters, and cloud environments. As these networks grow in complexity, operational visibility and response speed become critical to maintaining service quality and security posture.

Conventional NOC tooling remains predominantly reactive — faults are detected only after user-visible service degradation has occurred.

Two compounding challenges define this operational gap:

1. **Reactive detection:** threshold-based alerts fire only after performance thresholds are breached, providing no time for pre-emptive intervention.
2. **Air-gap constraints:** regulated and government environments prohibit cloud-connected AI inference tools, leaving operators without intelligent guidance in the most security-sensitive deployments.

This problem statement calls for an autonomous, air-gapped offline AI NOC Copilot that predicts network failures before operational impact, explains reasoning in natural language, and operates entirely within an air-gapped network.

---

## Objectives

### Objective 1 — Simulated SD-WAN/MPLS Environment `PS13-O1`

Construct a reproducible, multi-site simulated network topology representative of real-world enterprise deployments, including:

| ID | Requirement |
| --- | --- |
| `PS13-O1.1` | Branch, hub, and datacenter sites with CE/PE/P device roles |
| `PS13-O1.2` | MPLS forwarding plane, VPN segmentation, and traffic engineering constructs |
| `PS13-O1.3` | SD-WAN IPSec overlay tunnels, dynamic routing (BGP/OSPF), and QoS policies |
| `PS13-O1.4` | Realistic application traffic flows and configurable fault injection capabilities |

### Objective 2 — Predictive Fault Analytics Engine `PS13-O2`

Develop machine learning and statistical models that detect precursor conditions rather than threshold breaches:

| ID | Requirement |
| --- | --- |
| `PS13-O2.1` | Time-series forecasting for congestion buildup, interface utilization saturation, and latency drift |
| `PS13-O2.2` | Routing instability detection — BGP/OSPF convergence stress, route flapping precursors, path asymmetry |
| `PS13-O2.3` | Tunnel health degradation scoring — packet loss progression, jitter trends, rekey anomalies |
| `PS13-O2.4` | Time-to-impact estimation providing actionable lead times before service breach |

### Objective 3 — Offline LLM NOC Copilot `PS13-O3`

Deploy a fully self-hosted, air-gapped LLM to provide natural-language decision support:

| ID | Requirement |
| --- | --- |
| `PS13-O3.1` | Local model packaging — quantized LLM bundled within the air-gapped environment |
| `PS13-O3.2` | Retrieval-Augmented Generation (RAG) over internal artifacts only — topology maps, runbooks, past incidents |
| `PS13-O3.3` | Structured copilot responses including predicted issue, confidence score, root-cause hypothesis, affected scope, and recommended actions |
| `PS13-O3.4` | Natural-language query interface for NOC operators |

### Objective 4 — Integrated NOC Workflow Automation `PS13-O4`

Minimize manual troubleshooting effort by automating key NOC workflows:

| ID | Requirement |
| --- | --- |
| `PS13-O4.1` | Continuous topology awareness and dynamic graph-based event correlation |
| `PS13-O4.2` | Confidence-scored alert prioritization to reduce alert fatigue |
| `PS13-O4.3` | Automated playbook suggestion and action sequencing |
| `PS13-O4.4` | Operator-ready incident summaries with estimated impact and urgency classification |

---

## Expected Outcomes

The platform must enable NOC operators to answer three operational questions in real time:

| ID | Question |
| --- | --- |
| `PS13-Q1` | What is likely to fail next — and when? |
| `PS13-Q2` | Why is risk assessed as elevated — which signals contributed? |
| `PS13-Q3` | What corrective action should be taken before SLA or security impact occurs? |

**Success criterion:** not whether the system can detect a failure that has already occurred, but whether it can **forecast degradation with sufficient lead time** for the NOC to intervene preventively, and whether the LLM copilot can communicate that forecast in **operator-ready language** without any dependency on external networks or cloud APIs.  
(`PS13-SUCCESS`)

---

## Dataset Required `PS13-D`

All data is generated within the simulated environment and must remain within the air-gapped boundary:

| ID | Signal family |
| --- | --- |
| `PS13-D1` | SNMP interface utilisation, latency, jitter, and error counters |
| `PS13-D2` | Syslog and routing protocol events (BGP/OSPF adjacency changes, route advertisements) |
| `PS13-D3` | NetFlow/IPFIX flow records and tunnel statistics |
| `PS13-D4` | Streaming telemetry from SD-WAN controllers |
| `PS13-D5` | Injected fault and adversarial scenario ground-truth labels for model training and validation |

---

## Suggested Tools / Technologies (but not limited to)

| Area | Suggestions |
| --- | --- |
| Network simulation | EVE-NG, GNS3, or Containerlab |
| Telemetry pipeline | Telegraf, Prometheus, Elasticsearch, or Kafka |
| Predictive models | LSTM, Prophet, graph-based anomaly detection, ensemble classifiers |
| Offline LLM | Mistral 7B, LLaMA 3 8B, or Phi-3 (quantized for on-premises deployment) |
| RAG / vector database | local deployment (no cloud dependency) |
| Traffic / faults | Traffic generation and fault injection tooling |

*Suggested ≠ required.* Physical lab, alternate LLM sizes, or Telegraf→Prometheus without Kafka may still satisfy the perimeter if FINDINGS record the substitution honestly.

---

## Expected Solution / Steps to Achieve the Objectives

### Phase 1 — Network Simulation `PS13-P1`

Build the simulated SD-WAN over MPLS topology. Configure multi-site topology with branch, hub, and datacenter nodes; establish MPLS forwarding, VPN segmentation, dynamic routing protocols, and overlay tunnels. Deploy traffic generation tools and implement fault injection capabilities for scenario validation.

### Phase 2 — Telemetry Pipeline `PS13-P2`

Deploy a local telemetry collection stack to ingest and normalise signals from all simulated devices. Align interface utilisation, latency, jitter, BGP/OSPF events, tunnel statistics, syslog events, controller changes, and flow records into a time-series dataset. All data remains within the air-gapped boundary.

### Phase 3 — Predictive Modelling `PS13-P3`

Train and validate predictive models against historical telemetry using injected fault scenarios as ground truth. Evaluate model candidates on precision, recall, false-positive rate, and prediction lead time. Select or ensemble the best-performing combination for production inference.

### Phase 4 — Offline LLM Deployment `PS13-P4`

Select and quantize a compact open-source LLM for on-premises deployment. Package the model with all runtime dependencies into a portable bundle with all outbound network access disabled. Implement a RAG pipeline connecting the LLM to a local vector database populated with topology metadata, alert context, runbooks, and past incident records.

### Phase 5 — Copilot Integration & Decision Support `PS13-P5`

Wire predictive model outputs and network telemetry into the LLM context window via the RAG pipeline. Configure the copilot to produce structured responses for every alert, including: predicted issue type, confidence score, probable root cause, affected sites and services, and estimated time-to-impact.

### Phase 6 — Scenario Validation `PS13-P6`

Inject a set of realistic fault and adversarial scenarios and measure platform response. For each scenario, record prediction lead time, copilot explanation quality, and accuracy of recommended remediation:

| ID | Scenario |
| --- | --- |
| `PS13-P6.1` | Progressive congestion buildup on a hub-spoke link |
| `PS13-P6.2` | BGP route flap with downstream path reroute cascade |
| `PS13-P6.3` | Intermittent MPLS underlay failure with tunnel degradation |
| `PS13-P6.4` | Controller misconfiguration leading to policy drift |

---

## Alignment checklist (quick)

When finishing a task, confirm against FINDINGS using these IDs:

```
[ ] PS13-O1.*   lab / topology / SD-WAN / faults
[ ] PS13-O2.*   predictive ML (precursor, not post-breach only)
[ ] PS13-O3.*   offline LLM + RAG + structured NL
[ ] PS13-O4.*   NOC workflow automation
[ ] PS13-Q1..Q3 operator questions answerable in real time
[ ] PS13-D1..D5 dataset families inside air-gap
[ ] PS13-P1..P6 phase coverage (esp. P4–P6 remaining gap)
[ ] PS13-SUCCESS lead-time forecast + air-gapped NL (not cloud)
```

**Status answers belong only in** [`PROBLEM_STATEMENT_13_FINDINGS.md`](./PROBLEM_STATEMENT_13_FINDINGS.md).

---

## Lab process mapping (requirements → decided stack)

This perimeter does **not** claim completion. It maps each PS13 ask to the **decided lab process** documented in the Flow 1–3 mermaid of [`DECA_SDWAN_PROCESS_FLOW.md`](./DECA_SDWAN_PROCESS_FLOW.md).

| PS13 ID | Operator / model ask | Decided lab binding (mermaid) |
| --- | --- | --- |
| `PS13-O1.*` | Simulated SD-WAN/MPLS | **Flow 1a** Pi live + **Flow 1b** GNS3 twin (no TRex) |
| `PS13-O2.1` | Congestion / util / latency drift | **Q1** LSTM heads: latency · util (HTB 1:15) · + loss/jitter |
| `PS13-O2.2` | Routing instability / asymmetry | **Q2** flap **severity** (`bgp_flap_count`) + `path_asymmetry` — not flap-precursor ML |
| `PS13-O2.3` | Tunnel loss / jitter / rekey | **Q1** loss/jitter LSTMs; rekey = **rules/ambient** (no storm inject in campaign) |
| `PS13-O2.4` | Time-to-impact | **Q1** ETA → red gate any ETA ≤ 120 s |
| `PS13-O3.*` | Offline LLM + RAG + structured NL | **Q3** Phi-3 + Chroma `deca_lnc` (async; never blocks gate) |
| `PS13-O4.*` | NOC workflow | Decide rail + blast-radius corr + budgeted Approve sequence |
| `PS13-Q1` | What fails / when? | Multi-head LSTM ETAs on fabric Prom (`:9090` / `:9091`) |
| `PS13-Q2` | Why elevated? | Fabric-selected XGBoost severity `1A–5B` (+ CE rogue/victim) |
| `PS13-Q3` | What action? | Ranked playbooks + Phi-3 `q3_nlp` on Decide |
| `PS13-D5` | Fault GT labels | Protocol L0–L5 + **variant recipes** + compound + held-out chaos |
| `PS13-P6.1` | Congestion buildup | L5 util congestion (iperf ToS `0x80` through HTB) |
| `PS13-P6.2` | BGP flap cascade | L3 multi-cycle flap inducer (≠ Approve soft-clear) |
| `PS13-P6.3` | Underlay / tunnel degradation | L1 rain-fade + L4 loss progression |
| `PS13-P6.4` | Controller policy drift | CE SLA conflict / policy inject (separate demo path) |
| `PS13-SUCCESS` | Lead-time + air-gapped NL | Math gate (Q1/Q2) ∥ Q3 NLP · no cloud |

**Train discipline (decided):** prefer **Pi-labeled variants + compound** for primary train; GNS3 is a **transfer twin** — do not mash unlabeled Pi+GNS3. Gate L2 on **`cpu_usage_user`** (stress-ng burns user time). Chaos holdout never trains.
