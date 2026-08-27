# DECA Predictive SD-WAN: Presentation Deck

Simple answers to the main questions about this project — from the problem to what we deliver.

---

## Slide 1: The Problem Statement
**What problem did we get?**
* Today’s SD-WAN usually waits for a link to get bad, then switches to a backup. That is **reactive**.
* For ISRO TT&C (Telemetry, Tracking, and Command), waiting until after failure is too late. Even a few seconds of loss can hurt the mission.

---

## Slide 2: Our Understanding of the Problem
**What did we understand?**
* Soft / fake data is not enough. Real hardware under stress behaves differently (CPU load, buffers, short bursts).
* The network must **predict** trouble early and act **before** the service limit is broken.
* Operators will not trust an AI that changes routes on its own with no clear reason.

---

## Slide 3: The Solution We Are Providing
**What are we building?**
* A **predictive SD-WAN**: normal controller + AI that looks ahead.
* Training on **real Pi hardware** metrics, not only simulation.
* A **NOC dashboard** with a Copilot that explains problems in plain English and tells the operator what to do next.

---

## Slide 4: Why This Solution?
**Why this approach?**
* We split the AI into clear jobs: **when** will it fail (Q1) and **why** (Q2). That is easier to check than one big black box.
* **Human in the loop:** AI advises; the operator clicks **Approve** before traffic moves.
* Copilot only uses our runbooks (RAG) and live metrics — it does not invent facts.

---

## Slide 5: System Architecture
**How does the system work?**
* **Step 1 — Telemetry:** Prometheus reads live metrics from the Pi cluster, often many times per second.
* **Step 2 — AI:** Models read a short window of those metrics and score risk.
* **Step 3 — Orchestrator:** FastAPI connects models, controller, and the UI.
* **Step 4 — Explain & act:** Copilot writes a short brief; the Decide card lets the operator Approve a backup path.

---

## Slide 6: Complete Network Topology
**How is the lab network wired?**

One laptop (brain) plus three Raspberry Pis. Five sites sit on those Pis as customer edges. Traffic prefers the GRE path through CORE; eth0 is backup; mission traffic is encrypted with IPsec between PE1 and PE2.

```mermaid
flowchart TB
  brain["brain laptop<br/>192.168.50.1<br/>Prom · Kafka · Orchestrator · Controller · NOC UI"]

  subgraph s1 ["station1 · PE1 · 192.168.50.10"]
    PE1["PE1 edge router"]
    NRSC["NRSC Hyderabad<br/>Gold / TT&C site"]
    MAU["Mauritius<br/>Bronze distant site"]
    NRSC --> PE1
    MAU --> PE1
  end

  subgraph s3 ["station3 · CORE · 192.168.50.30"]
    CORE["CORE hub<br/>routes between edges"]
  end

  subgraph s2 ["station2 · PE2 · 192.168.50.20"]
    PE2["PE2 edge router"]
    SAC["SAC Ahmedabad<br/>Silver / Payload site"]
    MCF["MCF Hassan<br/>regional site"]
    SAC --> PE2
    MCF --> PE2
  end

  brain --- PE1
  brain --- CORE
  brain --- PE2

  PE1 -->|"preferred path<br/>GRE through CORE"| CORE
  CORE -->|"preferred path<br/>GRE through CORE"| PE2
  PE1 -.->|"backup path · eth0"| PE2
  PE1 <-->|"encrypted tunnel · IPsec"| PE2

  classDef brain fill:#020617,stroke:#60a5fa,color:#e2e8f0
  classDef pe fill:#0c1929,stroke:#38bdf8,color:#e0f2fe
  classDef core fill:#042f2e,stroke:#2dd4bf,color:#ccfbf1
  classDef gold fill:#1c1408,stroke:#eab308,color:#fde68a
  classDef silver fill:#111827,stroke:#9ca3af,color:#e5e7eb
  classDef bronze fill:#1a0f0a,stroke:#f97316,color:#fdba74
  class brain brain
  class PE1,PE2 pe
  class CORE core
  class NRSC gold
  class SAC silver
  class MAU,MCF bronze
  style s1 fill:#020617,stroke:#3b82f6,color:#93c5fd
  style s2 fill:#052e16,stroke:#22c55e,color:#86efac
  style s3 fill:#042f2e,stroke:#14b8a6,color:#5eead4
```

**Simple view of the layers**

```mermaid
flowchart LR
  subgraph sites ["Sites"]
    nrsc[NRSC]
    mau[Mauritius]
    sac[SAC]
    mcf[MCF]
  end

  subgraph underlay ["Paths under the tunnel"]
    pe1u[PE1]
    coreu[CORE]
    pe2u[PE2]
    pe1u -->|"preferred"| coreu
    coreu -->|"preferred"| pe2u
    pe1u -.->|"backup"| pe2u
  end

  subgraph overlay ["Safe tunnel"]
    ipsec["IPsec between PE1 and PE2"]
  end

  nrsc --> pe1u
  mau --> pe1u
  sac --> pe2u
  mcf --> pe2u
  ipsec --- pe1u
  ipsec --- pe2u

  classDef gold fill:#1c1408,stroke:#eab308,color:#fde68a
  classDef silver fill:#111827,stroke:#9ca3af,color:#e5e7eb
  classDef bronze fill:#1a0f0a,stroke:#f97316,color:#fdba74
  classDef pe fill:#0c1929,stroke:#38bdf8,color:#e0f2fe
  classDef core fill:#042f2e,stroke:#2dd4bf,color:#ccfbf1
  classDef tun fill:#1a0a2e,stroke:#c084fc,color:#e9d5ff
  class nrsc gold
  class sac silver
  class mau,mcf bronze
  class pe1u,pe2u pe
  class coreu core
  class ipsec tun
  style sites fill:#020617,stroke:#64748b,color:#cbd5e1
  style underlay fill:#022c22,stroke:#10b981,color:#6ee7b7
  style overlay fill:#1a0a2e,stroke:#a855f7,color:#d8b4fe
```

| Role | Host | Lab IP | Sites attached |
| --- | --- | --- | --- |
| PE1 | station1 | 192.168.50.10 | NRSC, Mauritius |
| PE2 | station2 | 192.168.50.20 | SAC, MCF |
| CORE | station3 | 192.168.50.30 | — |
| Brain | laptop | 192.168.50.1 | Runs Prom, Kafka, NOC, controller |

---

## Slide 7: Models & Benchmarks
**What models do we use, and how good are they?**
* **Q1 — time left:** LSTM estimates how many minutes until the service limit (e.g. 25 ms).
* **Q2 — what kind of problem:** XGBoost names the pattern (rain fade, route flap, CPU stress, and so on).
* **Extra rules:** Simple specialists catch hard edge cases the trees miss.
* **Results:**
  * **88.4%** on clean, unseen hardware tests.
  * **81.5%** even with extra chaos and background noise.

---

## Slide 8: The Output
**What does the operator see?**
* A live **NOC dashboard** where a person stays in control.
* A **Decide** card: severity, time left, and **Approve backup**.
* An **Explain** Copilot: short story, what to check, and what to click next.

---

## Slide 9: Organizational Impact
**How does this help an organization?**
* Fix problems **before** packets are dropped — less firefighting.
* Less mental load: the system does the heavy reading; the operator decides.
* New staff can act faster because Copilot explains in plain English.

---

## Slide 10: Target Audience
**Who is this for?**
* **NOC operators** — need clear alerts and a simple Approve step.
* **Network engineers** — need traces, metrics, and rules they can audit.
* **Mission leads (e.g. ISRO)** — need uptime, human approval, and no silent auto-steer.

---

## Slide 11: Deliverability
**What exactly are we delivering?**
* A clear **end-to-end design** (how pieces fit), not only one script.
* A **working pipeline:** live metrics → AI → orchestrator → NOC dashboard.
* An **air-gapped Copilot** pattern grounded in local runbooks.
* A **testbed method** (Pi + GNS3) others can copy to train on their own network.

---

## Slide 12: Scope of Expansion
**How can this grow later?**
* Train the same models on **ISRO’s own** history and hardware.
* Scale Prom / orchestrator to **many** earth stations.
* Later add RF SNR, weather, and orbit data to warn even earlier — before the terrestrial path looks bad.
