flowchart TD
    %% ==========================================
    %% PROBLEM STATEMENT 13: AIR-GAPPED SD-WAN
    %% AI PREDICTIVE COPILOT ARCHITECTURE
    %% ==========================================

    %% ==========================================
    %% FLOW 1: THE NETWORK TRAFFIC PLANE
    %% ==========================================
    subgraph Flow1 [Flow 1: Network & Simulation Overlay/Underlay]
        direction TB

        %% Synthetic Traffic & Chaos Injection
        subgraph Chaos [Synthetic Traffic & Chaos Injection]
            direction LR
            TG1(iPerf3: Multi-class UDP/TCP with --tos QoS marks)
            TG2(Admin untagged BE on vrf-admin)
            FI(NetEm: Latency, Jitter, Packet Loss Faults)
        end

        %% Customer Edge (CE) - Branch
        subgraph BranchSite [Branch Site - Customer Edge]
            BR_CE[Branch SD-WAN Router CE]
            AAR{Application-Aware Routing QoS}
            IPSEC_BR((IPsec Encryption Engine))
            
            BR_CE --> AAR
            AAR --> IPSEC_BR
        end

        %% Provider Network (MPLS Underlay)
        subgraph MPLS_Underlay [Air-Gapped Provider MPLS Cloud]
            direction LR
            PE_INGRESS[PE: Provider Edge Ingress]
            PE_EGRESS[PE: Provider Edge Egress]
            P_CORE1[P: Provider Core Router 1]
            P_CORE2[P: Provider Core Router 2]
            
            subgraph VRF_Lanes [VPN Segmentation / VRFs]
                VRF_CRIT[(VRF 1: Mission Critical)]
                VRF_GEN[(VRF 2: General Traffic)]
            end

            PE_INGRESS --> VRF_CRIT & VRF_GEN
            VRF_CRIT --> P_CORE1
            VRF_GEN --> P_CORE2
            P_CORE1 & P_CORE2 --> PE_EGRESS
        end

        %% Customer Edge (CE) - Datacenter & Hub
        subgraph DCSite [Datacenter & Hub Sites - Customer Edge]
            direction LR
            DC_CE[Datacenter SD-WAN Router CE]
            HUB_CE[Hub SD-WAN Router CE]
        end

        %% Flow 1 Connections
        TG1 & TG2 -->|Generates Application Traffic| BR_CE
        FI -.->|Injects Simulated Brownouts| MPLS_Underlay
        IPSEC_BR ===|Encrypted SD-WAN Tunnels| PE_INGRESS
        PE_EGRESS ===|Delivers Decrypted Payload| DC_CE
        PE_EGRESS ===|Delivers Decrypted Payload| HUB_CE
    end

    %% ==========================================
    %% FLOW 2: THE TELEMETRY PIPELINE
    %% ==========================================
    subgraph Flow2 [Flow 2: Sub-Second Telemetry Pipeline]
        direction TB

        %% Raw Data Sources
        subgraph RawData [Raw Telemetry Sources]
            SNMP[SNMP: Interface Utilisation]
            BGP_LOG[Syslog: BGP/OSPF Adjacency Events]
            NETFLOW[NetFlow/IPFIX: Tunnel Statistics]
        end

        %% Data Extraction
        subgraph Collectors [Data Ingestion]
            TELEGRAF{Telegraf Metrics Collector}
        end

        %% Time-Series Storage
        subgraph Storage [Air-Gapped Database]
            PROM[(Prometheus: Time-Series Database)]
            KAFKA[(Kafka: Event Streaming)]
        end

        %% Flow 2 Connections
        BR_CE & PE_INGRESS & P_CORE1 & DC_CE -.->|Continuous Probing| RawData
        SNMP & BGP_LOG & NETFLOW -->|Pulled periodically| TELEGRAF
        TELEGRAF -->|Normalizes & Streams| KAFKA
        KAFKA -->|Ingests into| PROM
    end

    %% ==========================================
    %% FLOW 3: AI PREDICTIVE COPILOT & ACTION
    %% ==========================================
    subgraph Flow3 [Flow 3: AI NOC Copilot & Control Plane]
        direction TB

        %% Machine Learning Layer
        subgraph ML_Layer [Predictive Analytics Layer]
            LSTM[Multi-head Q1 LSTM]
            XGB[Q2 XGBoost severity]
            TOPO[Topology blast-radius correlation]
        end

        %% GenAI Copilot Layer
        subgraph GenAI [Offline Natural Language Copilot]
            LLM((Ollama Phi-3))
            VECTOR[(Chroma LNC / RAG)]
        end

        %% Network Control Plane
        subgraph ControlPlane [SD-WAN Management Plane]
            ORCHESTRATOR{SD-WAN Orchestrator Dashboard}
            CONTROLLER[SD-WAN Controller]
        end

        %% Flow 3 Connections
        PROM -->|Feeds Historic & Live Telemetry| LSTM
        PROM -->|Feeds Features| XGB
        LSTM & XGB -->|Q1 ETA + Q2 severity| ORCHESTRATOR
        TOPO -->|correlated_alert_ids| ORCHESTRATOR
        LLM <-->|Retrieves Local Network Context| VECTOR
        LLM -->|Q3 English NLP (async wake)| ORCHESTRATOR
        
        %% The Closed Loop Execution
        ORCHESTRATOR -->|Operator Approves Pre-emptive Fix| CONTROLLER
        CONTROLLER -->|Pushes Dynamic Routing Rule| BR_CE
    end

    %% ==========================================
    %% GLOBAL STYLING & CLASSES
    %% ==========================================
    classDef traffic fill:#ffecb3,stroke:#f57f17,stroke-width:2px,color:#000
    classDef edgeRouter fill:#bbdefb,stroke:#0d47a1,stroke-width:3px,color:#000
    classDef coreRouter fill:#c8e6c9,stroke:#1b5e20,stroke-width:2px,color:#000
    classDef vrf fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,stroke-dasharray: 5 5,color:#000
    classDef rawData fill:#f3e5f5,stroke:#4a148c,stroke-width:1px,color:#000
    classDef db fill:#e1bee7,stroke:#6a1b9a,stroke-width:2px,color:#000
    classDef aiModel fill:#ffe0b2,stroke:#e65100,stroke-width:2px,color:#000
    classDef copilot fill:#ffccbc,stroke:#bf360c,stroke-width:3px,color:#000
    classDef management fill:#cfd8dc,stroke:#263238,stroke-width:3px,color:#000

    %% Applying Classes
    class TG1,TG2,FI traffic
    class BR_CE,DC_CE,HUB_CE,IPSEC_BR edgeRouter
    class PE_INGRESS,PE_EGRESS,P_CORE1,P_CORE2 coreRouter
    class VRF_CRIT,VRF_GEN vrf
    class SNMP,BGP_LOG,NETFLOW rawData
    class TELEGRAF,PROM,KAFKA,VECTOR db
    class LSTM,ANOMALY aiModel
    class LLM copilot
    class ORCHESTRATOR,CONTROLLER management