# DECA — Mermaid Maps

Five maps (+ util capture subsection 4.1). Paste into [mermaid.live](https://mermaid.live) if a viewer truncates a large graph.

Sources: [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) · [`lab/gns3/TOPOLOGY.md`](../lab/gns3/TOPOLOGY.md) · [`EDGE_POLICY_LAYERS.md`](./EDGE_POLICY_LAYERS.md) · [`DECA_SDWAN_PROCESS_FLOW.md`](./DECA_SDWAN_PROCESS_FLOW.md) · [`scripts/inject_util_congestion.sh`](../scripts/inject_util_congestion.sh)

---

## 1. Complete network map

One NOC · one Decide · one controller · shared wire contract · two isolated fabrics · dual Prom · dual Kafka topics. Do not mash scrapes or unlabeled train data.

```mermaid
flowchart TB
  subgraph MGMT["MANAGEMENT — laptop brain 192.168.50.1"]
    NOC["NOC UI :3000 · fabric selector pi|gns3"]
    ORCH["Orchestrator FastAPI :8000"]
    DEC["Decide rail · HITL Approve/Reject"]
    AAR["AAR class SLAs · enter_k=3 · exit_k=10<br/>TT&C≤25ms/5ms/0.1% · Payload≤80/15/2%"]
    CTRL["Controller :9280 · force_path / clear_force / bgp_soft_clear"]
    PRI["Priority: TT&C/Gold > Payload/Silver > Admin/Bronze"]
    NOC --> DEC --> AAR --> CTRL
    ORCH --> NOC
    PRI -.-> AAR
  end

  CONTRACT["SHARED WIRE CONTRACT<br/>ToS 0x88→HTB 1:10 · 0x80→1:15+RED · 0x00→1:20<br/>vrf-mission · vrf-admin · IPsec ESP deca-sdwan copy_dscp=out<br/>Gold 99.9% · Silver 99.5% · Bronze 90%"]

  MGMT --> CONTRACT

  subgraph TELE["TELEMETRY — shared Kafka · isolated Prometheus"]
    KAFKA[("Kafka :9092")]
    BR_PI["bridge :9274"]
    BR_GNS["bridge :9276"]
    EXP["gns3_path_exporter :9275"]
    PROM_PI[("Prom :9090 Pi only · also scrapes :9280")]
    PROM_GNS[("Prom :9091 GNS3 only")]
    KAFKA -->|"sdwan_telemetry_pi"| BR_PI --> PROM_PI
    KAFKA -->|"sdwan_telemetry_gns3"| BR_GNS --> PROM_GNS
    EXP --> PROM_GNS
  end

  subgraph PI["PI FABRIC — live · Prom :9090"]
    direction TB
    subgraph PICE["CE"]
      CEA["ce-a NRSC Gold 10.101.1.0/29"]
      CEM["ce-mauritius Bronze 10.101.3.0/29 ~200ms"]
      CEB["ce-b SAC Silver 10.101.2.0/29"]
      CEMCF["ce-mcf MCF Bronze 10.101.4.0/29"]
    end
    subgraph PIPE["PE — HTB + IPsec + VRF + AAR actuate"]
      PE1P["station1 PE1 192.168.50.10 · lo 10.1.1.1"]
      PE2P["station2 PE2 192.168.50.20 · lo 10.1.2.1"]
    end
    subgraph PIP["P — transit only · no HTB · preserve DSCP"]
      COREP["station3 CORE 192.168.50.30 · lo 10.1.3.1<br/>OSPF + LDP + BGP-RR · pathd SR-TE BSID 40001/40002"]
    end
    CEA & CEM -->|"WAN + HTB"| PE1P
    CEB & CEMCF -->|"WAN + HTB"| PE2P
    PE1P -->|"vrf-mission gre-te OSPF 5 · MPLS/LDP"| COREP
    COREP -->|"vrf-mission gre-te OSPF 5"| PE2P
    PE1P -.->|"vrf-admin eth0 OSPF 50 backup"| PE2P
    PE1P <-->|"IPsec ESP overlay"| PE2P
  end

  subgraph GNS["GNS3 FABRIC — 16-node twin · Prom :9091"]
    direction TB
    subgraph GCE["CE"]
      GNRSC["CE-NRSC Gold"]
      GMAU["CE-Mauritius Bronze"]
      GSHAD["CE-Shadnagar"]
      GSAC["CE-SAC Silver"]
      GMCF["CE-MCF"]
      GISTR["CE-ISTRAC"]
      GHQ["CE-ISRO-HQ"]
      GBHO["CE-Bhopal"]
      IPA["IPERF-A chaos"]
      IPB["IPERF-B chaos"]
    end
    subgraph GPE["PE — same HTB/VRF/IPsec jobs"]
      GPE1["PE1"]
      GPE2["PE2"]
      GPE3["PE3"]
    end
    subgraph GP["P — CORE-N primary · CORE-S optional"]
      GCN["CORE-N"]
      GCS["CORE-S"]
    end
    IPA --> GNRSC
    IPB --> GSAC
    GNRSC & GMAU & GSHAD --> GPE1
    GSAC & GMCF & GISTR --> GPE2
    GHQ & GBHO --> GPE3
    GPE1 -->|"mission N/S"| GCN & GCS
    GPE2 -->|"mission N/S"| GCN & GCS
    GPE3 -->|"mission N/S"| GCN & GCS
    GCN <--> GCS
    GPE1 -.->|"admin"| GPE2 & GPE3
    GPE2 -.->|"admin"| GPE3
    GPE1 <-->|"IPsec ESP"| GPE2
  end

  CONTRACT --> PI & GNS
  CTRL -->|"active=pi"| PE1P
  CTRL -->|"active=gns3"| GPE1
  PE1P & PE2P & COREP -.->|"Telegraf fabric=pi"| KAFKA
  GPE1 & GCN & GPE2 -.->|"telegraf-gns3"| KAFKA
  PROM_PI & PROM_GNS -->|"fabric-selected"| ML["Q1 LSTM · Q2 XGB · Decide seed"]
  ML --> DEC
```

---

## 2. Pi network map

Three Raspberry Pis · four sites · namespaces · GRE/VRF/IPsec · HTB · planes · boot order — as-built single CORE (dual-core netns not applied).

```mermaid
flowchart TB
  LAP["brain 192.168.50.1<br/>NOC :3000 · Orch :8000 · Ctrl :9280 · Prom :9090 · Kafka :9092"]

  subgraph ST1["station1 PE1 — 192.168.50.10 · lo 10.1.1.1"]
    direction TB
    subgraph NRSC["NRSC Hyderabad — Branch · Gold"]
      CEA["netns ce-a"]
      NWS["nrsc-ws 10.101.1.2"]
      NSRV["nrsc-srv 10.101.1.3"]
      NWS & NSRV --> CEA
    end
    subgraph MAU["Mauritius — Distant branch · Bronze"]
      CEM["netns ce-mauritius"]
      MWS["mau-ws 10.101.3.2"]
      MSRV["mau-srv 10.101.3.3"]
      NETEM["netem 100ms/dir → ~200ms RTT"]
      MWS & MSRV --> CEM
      NETEM -.-> CEM
    end
    PE1["PE1 FRR + strongSwan<br/>HTB 40mbit eth0: 1:10 TT&C 0x88 · 1:15 Payload 0x80+RED · 1:20 BE<br/>vrf-mission · IPsec terminate · AAR actuate"]
    GRE1["gre-te-core 10.50.1.1/30"]
    ETH1["eth0 underlay / backup"]
    CEA & CEM -->|"site LAN → CE WAN"| PE1
    PE1 --- GRE1
    PE1 --- ETH1
  end

  subgraph ST3["station3 CORE Hub/P — 192.168.50.30 · lo 10.1.3.1"]
    CORE["CORE FRR — single P as-built<br/>OSPF + LDP + BGP RR · OSPF-TE TED · pathd SR-TE<br/>BSID 40001 preferred · 40002 backup<br/>NO HTB · preserve DSCP · transit only"]
    GRE_PE1["gre-te-pe1 10.50.1.2/30"]
    GRE_PE2["gre-te-pe2 10.50.2.2/30"]
    CORE --- GRE_PE1 & GRE_PE2
  end

  subgraph ST2["station2 PE2 — 192.168.50.20 · lo 10.1.2.1"]
    direction TB
    subgraph SAC["SAC Ahmedabad — Datacenter · Silver"]
      CEB["netns ce-b"]
      SWS["sac-ws 10.101.2.2"]
      SSRV["sac-srv 10.101.2.3"]
      SWS & SSRV --> CEB
    end
    subgraph MCF["MCF Hassan — Regional · Bronze"]
      CEMCF["netns ce-mcf"]
      MCWS["mcf-ws 10.101.4.2"]
      MCSRV["mcf-srv 10.101.4.3"]
      MCWS & MCSRV --> CEMCF
    end
    PE2["PE2 FRR + strongSwan<br/>HTB + VRF + IPsec decrypt"]
    GRE2["gre-te-core 10.50.2.1/30"]
    ETH2["eth0 underlay / backup"]
    CEB & CEMCF --> PE2
    PE2 --- GRE2 & ETH2
  end

  LAP --- ST1 & ST3 & ST2

  GRE1 <-->|"GRE + MPLS/LDP · OSPF cost 5<br/>vrf-mission preferred"| GRE_PE1
  GRE_PE2 <-->|"GRE + MPLS/LDP · OSPF cost 5<br/>vrf-mission"| GRE2
  ETH1 -.->|"eth0 OSPF cost 50 · vrf-admin backup<br/>never mission MPLS"| ETH2
  PE1 <-->|"IPsec ESP deca-sdwan overlay<br/>selectors: CE attach · loopbacks · site LANs"| PE2

  subgraph PLANES["Planes stacked on the same boxes"]
    U["Underlay: MPLS on GRE preferred · eth0 backup"]
    TE["TE: OSPF-TE → pathd SR-TE · not RSVP"]
    O["Overlay: IPsec + AAR + controller force_path OSPF cost+/32"]
    Q["QoS: HTB on PE+CE only · CORE never reclassifies"]
  end

  subgraph BOOT["Boot order per station"]
    B1["deca-ns"] --> B2["deca-ns-mauritius|mcf"] --> B3["deca-expansion-boot VRF/GRE/HTB/MPLS/SR-TE"] --> B4["FRR + IPsec"] --> B5["deca-watchdog +60s"]
  end

  subgraph CHAOS_PI["Chaos on Pi — same fault book as GNS3 · no TRex"]
    IP["iperf3: TT&C UDP ToS 0x88 → PE 1:10 · Admin TCP → PE 1:20<br/>Util bulk: CE→IPsec→eth0 misses PE 1:15 filters → lands in BE 1:20"]
    INJ["Injects on PE1/NRSC–SAC: rain · loss · stress-ng · BGP flap · util · CE SLA conflict<br/>Mauritius/MCF = baselines only — not inject targets"]
    UTIL_CAP["Util CAPTURE_CONTRACT: shape on ce-a veth-cea-pe pre-IPsec · offer≥2×end<br/>lift PE BE 1:20 ceil→40 during window · mirror 1:15 audit-only · restore on exit<br/>chaos util phase end_mbit=24 off-nominal vs idle payload ceil 34"]
  end

  PE1 -.-> CHAOS_PI
  CEA -.->|"util inject shape"| UTIL_CAP
  ST1 & ST2 & ST3 -.->|"Telegraf SNMP · probes · FRR · softflowd · htb_payload_ceil → Kafka"| LAP
```

---

## 3. GNS3 network map

Same Flow-1 roles as Pi; scale adds PE3, CORE-S, extra CEs, IPERF chaos. Dual-P exists here only.

```mermaid
flowchart TB
  subgraph CTRL_G["Shared control — same brain as Pi"]
    NOC2["NOC :3000 fabric=gns3"]
    ORCH2["Orch :8000"]
    CTRL2["Controller Approve → mission_state.json / PE1 twin"]
    NOC2 --> ORCH2 --> CTRL2
  end

  subgraph WEST["West / Branch — behind PE1"]
    NRSC["CE-NRSC · Gold 99.9%"]
    MAUG["CE-Mauritius · Bronze 90% · rogue risk"]
    SHAD["CE-Shadnagar"]
    IPA["IPERF-A chaos source"]
    IPA -->|"LAN"| NRSC
  end

  subgraph EAST["East / Hub — behind PE2"]
    SACG["CE-SAC · Silver 99.5%"]
    MCFG["CE-MCF"]
    ISTRAC["CE-ISTRAC"]
    IPB["IPERF-B chaos sink"]
    IPB -->|"LAN"| SACG
  end

  subgraph SOUTH["Regional — behind PE3"]
    HQ["CE-ISRO-HQ"]
    BHO["CE-Bhopal"]
  end

  subgraph PROVIDER["Provider MPLS on GRE — Docker GNS3"]
    PE1G["PE1 · HTB + IPsec + VRF + AAR"]
    PE2G["PE2 · HTB + IPsec + VRF"]
    PE3G["PE3 · HTB stubs/scale"]
    COREN["CORE-N primary P = Pi CORE role<br/>preserve DSCP · no HTB remap"]
    CORES["CORE-S optional dual-P"]
    HTB_NOTE["HTB 40mbit on PE1–3 + all CEs · CORE stripped for NetEM"]
  end

  NRSC & MAUG & SHAD -->|"WAN"| PE1G
  SACG & MCFG & ISTRAC -->|"WAN"| PE2G
  HQ & BHO -->|"WAN"| PE3G

  PE1G -->|"vrf-mission N"| COREN
  PE1G -->|"vrf-mission S"| CORES
  PE2G -->|"vrf-mission N"| COREN
  PE2G -->|"vrf-mission S"| CORES
  PE3G -->|"vrf-mission N"| COREN
  PE3G -->|"vrf-mission S"| CORES
  COREN <-->|"inter-core backbone"| CORES

  PE1G -.->|"vrf-admin"| PE2G
  PE1G -.->|"vrf-admin"| PE3G
  PE2G -.->|"vrf-admin"| PE3G
  PE1G <-->|"IPsec ESP deca-sdwan copy_dscp"| PE2G

  CTRL2 -->|"force_path / soft-clear"| PE1G
  HTB_NOTE -.-> PE1G & PE2G & PE3G

  subgraph CHAOS_G["Chaos — NetEM on CORE underlay · never wipe PE HTB"]
    FI["rain/netem · loss · stress-ng PE1 · BGP · util ramp · CE surge<br/>util: offer≥2×end · schedule sidecar · chaos end_mbit=24"]
    FI -.-> COREN
  end

  subgraph TELE_G["GNS3 telemetry"]
    EXP2["path exporter :9275 ← chaos_state.json 1Hz"]
    KAF2["Kafka topic sdwan_telemetry_gns3"]
    PROMG[("Prom :9091")]
    EXP2 --> PROMG
    PE1G & COREN & PE2G -.-> KAF2 --> PROMG
  end

  subgraph MAP["Role map vs Pi"]
    M1["Pi PE1 → GNS3 PE1"]
    M2["Pi CORE → GNS3 CORE-N · CORE-S = scale only"]
    M3["Pi PE2 → GNS3 PE2 · PE3 = extra"]
    M4["Pi NRSC/MAU/SAC/MCF → same-name CEs · extras = Shadnagar/ISTRAC/HQ/Bhopal"]
  end
```

---

## 4. Metrics → collection → dataset → training → model building

End-to-end: live gauges → Kafka/Prom → labeled campaigns → windows → Q1/Q2 train → chaos_final once → promote bar. Pi primary; GNS3 transfer only.

```mermaid
flowchart TB
  subgraph METRICS["1. LIVE METRICS on fabric"]
    LAT["latency_gre_ms · latency_eth0_ms"]
    JIT["jitter_gre_ms"]
    LOSS["loss_gre_pct"]
    UTIL["util_gre_mbps · eth0 util"]
    CEIL["htb_payload_ceil_mbps — live configured payload ceil"]
    CPU["cpu_usage_user"]
    BGP["bgp_flap_count → 10s rolling rate"]
    ASYM["path_asymmetry = GRE − eth0"]
    REKEY["ipsec_rekey_events_1h · ipsec_rekey_anomaly"]
    CE_G["CE LAN gauges · rogue/victim surge"]
  end

  subgraph COLLECT["2. COLLECTION"]
    TEL["Telegraf: SNMP · PE probes 1Hz · FRR · softflowd IPFIX · syslog · htb ceil gauge"]
    K["Kafka :9092 — sdwan_telemetry_pi | sdwan_telemetry_gns3"]
    BR["Bridges :9274 Pi · :9276 GNS3 · exporter :9275"]
    PROM["Prometheus :9090 Pi · :9091 GNS3 — never cross-scrape"]
    CAP["capture_live.py → 1Hz series.csv per stamp"]
    SCHED["util_ceil_schedule.jsonl sidecar — configured ceil vs end_mbit"]
    WS["Optional Wireshark: NOC capture API → GNS3 link tap / Pi tcpdump"]
    TEL --> K --> BR --> PROM --> CAP
    SCHED -.-> CAP
    WS -.-> CAP
  end

  subgraph INJECT["3. LABELED INJECT CAMPAIGNS"]
    L0["L0 normal"]
    L1["L1 rain_fade → 1A/1B/1C"]
    L2["L2 cpu_stress → 2A/2B on cpu_usage_user"]
    L3["L3 bgp_flap mild/storm → 3A/3B"]
    L4["L4 loss_progression → 4A/4B"]
    L5["L5 util_congestion ends 12…34 · CE-veth shape + BE lift → 5A/5B"]
    L6["L6 CE SLA conflict → 6A/6B outside Q1"]
    COMP["COMPOUND overlapping pairs"]
    CHAOS["chaos_holdout train=false · chaos_dev select · chaos_final one-shot<br/>util phase end=24 off-nominal vs idle ceil 34"]
  end

  subgraph PREP["4. DATASET BUILD"]
    ALIGN["align_1Hz + EMA span=5 + path_asymmetry + ceil feature"]
    SEV["severity_label · util 5A/5B from schedule ceil vs end_mbit<br/>5A ∈ [0.5·end, end) · 5B ≥ end · not Mbps-band guesses"]
    Q2W["q2_windows FEATURE_COLS includes htb_payload_ceil_mbps"]
    Q1W["q1_windows TTI sequences + ETA labels<br/>lat→25ms · loss→2% · jitter→5ms · util→scheduled HTB ceil"]
    BAL["balance_windows · group holdout L4+COMPOUND"]
    ALIGN --> SEV --> Q2W & Q1W --> BAL
  end

  subgraph TRAIN["5. TRAINING"]
    T_Q2["train_q2_xgb severity + root"]
    T_Q1["train_q1_lstm ×4 heads: latency · loss · jitter · util"]
    SEL["Select on chaos_dev only — never on chaos_final"]
    SCORE["Score chaos_final once · GNS3 transfer once"]
    T_Q2 & T_Q1 --> SEL --> SCORE
  end

  subgraph MODELS["6. PROMOTED ARTIFACTS"]
    M_Q2S["xgb_q2_sev_unified"]
    M_Q2R["xgb_q2_root_unified"]
    M_L["lstm_q1_unified latency"]
    M_Loss["lstm_q1_loss"]
    M_J["lstm_q1_jitter"]
    M_U["lstm_q1_util"]
  end

  subgraph DISCIPLINE["TRAIN / HOLDOUT / TRANSFER / PROMOTE"]
    FV["Pi train: full_variants_pi_* + eff_pack merge → NEW dataset path"]
    XFER["GNS3 twin windows = transfer only · no mash"]
    BAR{"PROMOTE_BAR<br/>BGP exact≥0.70 · family≥0.84<br/>holdout≥0.870 · chaos_final≥0.800<br/>loss&util phase≥0.950 · GNS3 xfer≥0.620<br/>Q1 loss MAE≤9.0 if retrained"}
    YES["Backup old → protocol_models cutover"]
    NO["Keep d2_e100_l6_mcw3 · NO_PROMOTE"]
  end

  METRICS --> COLLECT
  INJECT --> CAP
  CAP --> PREP --> TRAIN
  SCORE --> M_Q2S & M_Q2R & M_L & M_Loss & M_J & M_U
  FV --> PREP
  XFER --> SCORE
  SCORE --> BAR
  BAR -->|all floors pass| YES
  BAR -->|any fail / borderline| NO

  subgraph HEADS["Signal → label → head"]
    S1["latency → rain 1* → Q1 lat LSTM + Q2"]
    S2["cpu_usage_user → 2* → Q2"]
    S3["BGP rate → 3* → Q2"]
    S4["loss% → 4* → Q1 loss LSTM + Q2"]
    S5["util Mbps + ceil feature → 5* → Q1 util LSTM + Q2 · soft_ceiling"]
    S6["CE rogue → 6* → Q2 only"]
  end
```

### 4.1 Util capture contract — why PE `1:15` alone failed

Encapped CE→PE flows miss PE ToS/dport filters and land in BE `1:20` (nominal ceil **24**). Changing PE `1:15` was a no-op for measured eth0 util. Fix order: CE pre-IPsec shape → offer≥2×end → lift BE ceil→40 during inject → schedule-sourced 5A/5B → live `htb_payload_ceil_mbps`. Do not retrain until util separates across L5 ends.

```mermaid
flowchart LR
  subgraph FAIL["Broken assumption"]
    A1["Change PE eth0 class 1:15 ceil"]
    A2["Expect eth0 util ≈ ceil"]
    A1 --> A2
    A2 -.->|"actual: traffic in 1:20"| HARD["Hard plateau ~24 Mbps"]
  end

  subgraph PATH["Real util packet path"]
    CE["ce-a iperf offer ≥2×end"] --> VETH["veth-cea-pe HTB shape<br/>class 1:15 = configured ceil"]
    VETH --> ENC["PE IPsec/MPLS encap"]
    ENC --> ETH["eth0 · default BE 1:20"]
    ETH --> MEAS["Prom util_gre / eth0 util<br/>tracks CE ceil only if BE not capping"]
  end

  subgraph FIX["CAPTURE_CONTRACT inject"]
    F1["Shape on CE veth pre-IPsec"]
    F2["Lift PE 1:20 ceil → 40 for window"]
    F3["Mirror PE 1:15 audit-only · restore both on EXIT"]
    F4["util_ceil_schedule.jsonl + live ceil gauge"]
    F5["5A/5B = schedule ceil vs end_mbit"]
    F1 --> F2 --> F3 --> F4 --> F5
  end

  HARD -.->|"diagnosis"| FIX
  PATH --> MEAS
  FIX --> MEAS
```

---

## 5. AI NOC Copilot map

Math gate never waits on LLM. Q1 = what/when · Q2 = why · Q3 = English narrative. Approve → soft-clear then force_path.

```mermaid
flowchart TB
  subgraph LIVE["LIVE — fabric-selected Prom"]
    PROM["Prom :9090 Pi or :9091 GNS3"]
  end

  subgraph GATE["MATH GATE — Q1 multi-head + Q2"]
    PREP2["1Hz align + EMA + path_asymmetry + rekey features"]
    Q1A["Q1 latency TTI → 25 ms SLA · hard_sla"]
    Q1B["Q1 loss TTI → 2% SLA · hard_sla"]
    Q1C["Q1 jitter TTI → 5 ms · hard_sla"]
    Q1D["Q1 util TTI → scheduled HTB ceil · soft_ceiling wording"]
    Q2A["Q2 XGBoost severity 1A–5B · 6A/6B<br/>confidence = predict_proba · root head"]
    FUSE["alert_fusion: OR-red · Q2 = primary issue · urgency = min ETA<br/>Red: any ETA≤120s + red severity 1B/1C/2B/3B/4B/5B"]
    CORR["topology blast_radius + correlated_alert_ids + ranked playbook"]
    PREP2 --> Q1A & Q1B & Q1C & Q1D & Q2A --> FUSE --> CORR
  end

  subgraph SEED["ORCHESTRATOR SEED → Decide card"]
    TITLE["Predicted issue + confidence"]
    ETA["ETA · urgency_clock_kind hard_sla|soft_ceiling"]
    SCOPE["blast_radius · concerns[] honest wording"]
    PB["Ranked playbook · budgeted steps"]
  end

  subgraph Q3["Q3 OFFLINE NLP — async · never blocks Approve"]
    CHROMA[("Chroma deca_lnc")]
    EMB["nomic-embed-text"]
    PHI["Ollama Phi-3"]
    NARR["q3_nlp English narrative on Decide"]
    EMB --> CHROMA --> PHI --> NARR
  end

  subgraph HITL["HUMAN IN THE LOOP"]
    NOC3["NOC Decide rail :3000"]
    APPR{"Approve / Reject"}
    ACT["Controller :9280<br/>1. bgp_soft_clear ~8s one-shot<br/>2. force_path ~15s always follows<br/>wall-clock ≪ 120s red gate"]
    PE["Active fabric PE1 — OSPF cost + /32 steer"]
    CLR["Recovery: clear_force / exit_k / reset_autonomy"]
  end

  subgraph PS13["PS13 questions"]
    QQ1["Q1 What fails next / when? → 4× LSTM TTI"]
    QQ2["Q2 Why? → XGBoost severity + root"]
    QQ3["Q3 What should I do? → Phi-3 + RAG + playbook"]
  end

  LIVE --> GATE --> SEED --> NOC3
  FUSE -.->|"async Prom snapshot"| Q3
  NARR --> NOC3
  NOC3 --> APPR
  APPR -->|Approve| ACT --> PE
  APPR -->|Reject| CLR
  PE -.->|"metrics change"| LIVE
  PS13 -.-> GATE & Q3
```

### 5.1 Multi-fault — same path (compound) + other paths/sites

First-class: COMPOUND train + live arbitration. Not a separate model; not multi-label Q2 (Phase-2).

```mermaid
flowchart TB
  subgraph SAME["Same path / overlapping time — COMPOUND"]
    F1["Fault A e.g. rain / loss"]
    F2["Fault B e.g. BGP / util"]
    Q1H["Q1 heads may both fire"]
    Q2P["Q2 picks ONE primary class"]
    ORG["Gate RED = OR of heads"]
    MIN["Urgency = min ETA"]
    SHOW["Decide: firing_tti_heads + compound_suspected"]
    F1 & F2 --> Q1H & Q2P
    Q1H --> ORG & MIN --> SHOW
    Q2P --> SHOW
  end

  subgraph OTHER["Other paths / sites — static topology"]
    BR["blast_radius from adjacency"]
    COR["correlated_alert_ids clique"]
    UB["urgency_boost if overlap"]
    BR --> COR --> UB
  end

  SHOW --> CARD["Decide card · playbook on primary · chaos_compound SOP"]
  UB --> CARD

  LIMIT["Honest limits: no multi-label Q2 · quieter leg can drown · not learned graph ML"]
  CARD -.-> LIMIT
```

Train: `full_variants` COMPOUND ×8 · eff_pack ×4 (`bgp+loss`, `rain+bgp`, `loss+util`, `bgp+util`) both fabrics. See [`MULTI_FAULT.md`](../data/deca/predictive/MULTI_FAULT.md).

```mermaid
sequenceDiagram
  participant Op as Operator NOC
  participant Orch as Orchestrator :8000
  participant Gate as Q1/Q2 infer
  participant Dec as Decide card
  participant Q3 as Phi-3 RAG
  participant Ctrl as Controller :9280
  participant PE as Active PE1

  Op->>Orch: fabric=pi|gns3
  Orch->>Gate: scrape Prom for fabric
  Gate->>Orch: fused seed ETA severity blast-radius playbook
  Orch->>Dec: Decide card
  Orch->>Q3: async narrative
  Q3-->>Dec: q3_nlp
  Op->>Dec: Approve
  Dec->>Orch: POST approve
  Orch->>Ctrl: bgp_soft_clear then force_path
  Ctrl->>PE: apply path / BGP action
  PE-->>Gate: metrics change
  Gate-->>Dec: updated ETA / clear
```
