import re

def fill_scaffold(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Authors and Institutions
    content = content.replace('**[FILL: Author 1], [FILL: Author 2], [FILL: Author 3]**', '**Mohammed Shaik Sahil, Shaik Farhana, Hina Mehjabeen, Ummul Faiz Zainab Bibi**')
    content = content.replace('**[FILL: Institution / Department]**', '**Nawab Shah Alam Khan College of Engineering and Technology / National Remote Sensing Centre / Indian Space Research Organisation**')
    content = content.replace('**[FILL: Conference / Journal Name]**', '**ISRO BAH 2026**')

    # 2. Abstract
    abstract = """Modern enterprise and government SD-WAN networks suffer from purely reactive NOC tooling — faults are detected only after SLA breaches occur, leaving operators with no lead time for pre-emptive intervention. DECA (Distributed Edge Copilot Architecture) addresses this gap by deploying a fully air-gapped, multi-model predictive analytics system over a physical multi-site SD-WAN/MPLS laboratory. We constructed a five-site topology on three Raspberry Pi nodes running Free Range Routing (FRR) and generated ground-truth telemetry through six controlled fault injection protocols (L0–L6). DECA features a dual-model stack: multi-head LSTM networks for Time-to-Impact estimation (Q1) and an XGBoost severity classifier (Q2), alongside a locally-hosted Phi-3 LLM with Retrieval-Augmented Generation (RAG) that provides operator-ready natural-language decision support (Q3), entirely without external network dependency. Our Q2 classifier achieved a 0.884 macro-F1 score on a physical holdout and 0.815 on a 12-hour sealed chaos run, identifying the root-cause fault family with 0.992 accuracy. The Q1 loss Time-To-Impact head demonstrated a 7.1-second validation MAE, enabling a 120-second red-gate for NOC preemption before SLA breaches occur."""
    
    content = re.sub(r'<!-- FILL: 200–250 word paragraph.*?-->', abstract, content, flags=re.DOTALL)

    # 3. Introduction
    intro_1_1 = """Modern enterprise and government networks rely heavily on SD-WAN deployments over MPLS underlays to provide resilient connectivity. However, as these networks scale, operational visibility and response speed become critical bottlenecks. Conventional Network Operations Center (NOC) tooling remains predominantly reactive; threshold-based alerts fire only after an SLA breach has impacted users. This reactive posture leaves operators with no lead time for pre-emptive intervention. 

Compounding this issue is the strict air-gap constraint present in regulated government, defense, and space agency environments, such as those operated by the Indian Space Research Organisation (ISRO). These high-security networks prohibit the use of cloud-connected AI inference tools, thereby excluding operators from the benefits of modern intelligent AIOps platforms.

To address this, ISRO BAH 2026 Problem Statement 13 calls for an autonomous, air-gapped offline AI NOC Copilot capable of forecasting network failures before operational impact. DECA satisfies this requirement by providing real-time answers to three core operator questions: what fails next (Q1), why is risk elevated (Q2), and what action should be taken (Q3) — all while remaining fully offline."""
    
    content = re.sub(r'<!-- FILL: 2–3 paragraphs\. Cover:.*?-->', intro_1_1, content, flags=re.DOTALL)

    intro_1_2 = """1. A physical five-site MPLS/SD-WAN testbed on commodity hardware with controlled fault injection across six fault families (L0–L6).
2. A multi-head LSTM architecture providing per-SLA-dimension time-to-impact (TTI) estimates at 1 Hz.
3. An XGBoost severity classifier with 13 severity classes and a BGP sub-specialist, evaluated on a sealed 12-hour chaos holdout.
4. A fully air-gapped LLM NOC copilot (Phi-3 + ChromaDB RAG) that never calls external APIs, designed specifically for secure environments.
5. An honest evaluation discipline demonstrated through six NO_PROMOTE attempts and fully documented pipeline bugs."""
    
    content = re.sub(r'<!-- FILL: Bulleted list of novel contributions.*?-->', intro_1_2, content, flags=re.DOTALL)

    intro_1_3 = """Section 2 reviews related work in network anomaly detection and AIOps. Section 3 outlines the DECA system architecture and dual-fabric design. Section 4 details the physical network simulation and lab setup, including the MPLS forwarding plane and application-aware QoS. Section 5 describes the dual-fabric telemetry ingest pipeline. Section 6 presents the fault taxonomy and the dataset generation process via controlled lab campaigns. Section 7 details the predictive modeling methodology, feature engineering, and the Q1/Q2 machine learning models. Section 8 explains the offline LLM and RAG NOC copilot for automated natural-language operator guidance. Section 9 outlines the integrated HITL workflow automation and Decide UI. Section 10 discusses our experimental results, the canonical scoreboard, and the chaos holdout evaluation. Section 11 honestly discloses system limitations and the GNS3 hardware physics transfer gap. Section 12 explains the portability of the system to ISRO production networks. Finally, Section 13 concludes the paper."""
    
    content = re.sub(r'<!-- FILL: One sentence per section pointing to where things are -->', intro_1_3, content, flags=re.DOTALL)

    # 4. Related Work
    related_work = """Network anomaly detection has traditionally relied on static threshold-based rules and SNMP polling, which often suffer from high false-positive rates and only alert operators after service degradation has occurred. More recent AIOps platforms (such as Cisco Crosswork or proprietary NetAI solutions) employ machine learning for predictive insights. However, the vast majority of these commercial solutions require telemetry to be streamed to a centralized cloud analytics engine for inference, rendering them fundamentally incompatible with the strict air-gap requirements of defense and space agency networks like ISRO's.

In the realm of time-series network forecasting, Recurrent Neural Networks (RNNs) and Long Short-Term Memory (LSTM) architectures have shown promise for predicting traffic volumes and congestion [Hochreiter & Schmidhuber, 1997]. Most existing literature focuses on predicting broad traffic classes on simulated datasets. In contrast, DECA applies a multi-head LSTM directly to 1 Hz telemetry captured from a physical testbed to predict explicit Time-to-Impact (TTI) in seconds across four distinct Service Level Agreement (SLA) dimensions simultaneously.

For fault severity classification, gradient boosted trees such as XGBoost [Chen & Guestrin, 2016] are frequently utilized due to their robustness to unscaled features and tabular time-series data. While prior work often targets binary anomaly classification (healthy vs. anomalous), DECA extends this with a 13-class severity taxonomy across six fault families (L1–L6), incorporating a BGP sub-specialist classifier to refine control-plane instability severities. Furthermore, rather than relying on synthetic datasets, DECA generates its ground truth via physical protocol-level fault injection (e.g., `tc netem`, `stress-ng`, and BGP soft clears) directly on Raspberry Pi hardware.

Finally, the application of Large Language Models (LLMs) to IT operations (AIOps) is an emerging field. Current implementations typically leverage API-connected frontier models (e.g., OpenAI's GPT-4) combined with Retrieval-Augmented Generation (RAG) [Lewis et al., 2020]. DECA differentiates itself by demonstrating that a quantized, small-parameter local model (Ollama Phi-3 3B) [Abdin et al., 2024] coupled with a local vector store (ChromaDB) can generate highly accurate, operator-ready diagnostic narratives without any external network dependencies."""
    
    content = re.sub(r'<!-- FILL: 1–2 pages covering:.*?-->', related_work, content, flags=re.DOTALL)

    # 5. GNS3 Virtual Twin
    gns3 = """To validate model transferability across varying underlying hardware, DECA employs a 16-node GNS3 virtual twin alongside the primary Raspberry Pi physical lab. The GNS3 topology extends the physical setup by introducing a dual-P CORE architecture (CORE-N and CORE-S) and additional Customer Edge (CE) nodes representing Shadnagar, ISTRAC, and Bhopal. Because physical hardware (dedicated ARM cores) and virtual instances (cgroups sharing a single host CPU) exhibit profoundly different telemetry signatures under stress, the GNS3 fabric acts as a transfer-evaluation twin to prove that DECA's predictive pipeline methodology — specifically the baseline-relative z-score feature engineering — can adapt to different network physics."""
    
    content = re.sub(r'<!-- FILL: Brief paragraph describing dual-P CORE topology.*?-->', gns3, content, flags=re.DOTALL)

    # 6. Util Physics
    util_physics = """During early L5 congestion campaigns, a critical hardware-software mismatch in the QoS pipeline was identified: payload CE traffic, post-IPsec encryption, bypassed the intended HTB `1:15` queue and landed in the default `1:20` best-effort queue on the PE's `eth0` interface because the original outer DSCP was obscured. The fix required two changes: shaping traffic on the `veth-cea-pe` interface *before* ESP encryption (where DSCP tags remain visible), and leveraging `copy_dscp=out` in `swanctl` to preserve ToS across the IPsec tunnel. Additionally, the baseline BE `1:20` nominal ceiling was lifted to 40 Mbit to prevent hard capping during injection. These fixes restored monotone separability — confirming a stable `util/ceil` ratio of ≈ 1.07 across the 12–34 Mbit range — providing the physical prerequisite for the LSTM regressor to learn a meaningful deterioration curve."""
    
    content = re.sub(r'<!-- FILL: 1 paragraph explaining the IPsec DSCP bug.*?-->', util_physics, content, flags=re.DOTALL)

    # 7. CE SLA
    ce_sla = """To address L6 (CE SLA Policy Conflict) scenarios — where a low-priority site overwhelms a high-priority site on a shared underlay — DECA employs `ce_surge_detect.py`. This script continuously monitors `ce_util_mbps` per CE, triggering when a quiet edge (e.g., a 2–3 Mbps baseline) unexpectedly surges past a 15 Mbps threshold. The system accurately identifies the rogue source (e.g., Bronze-tier Mauritius) and the victim destination (e.g., Gold-tier NRSC). When an L6 alert is generated, the Decide AlertRail dynamically surfaces both `rogue_ce` and `victim_ce`, providing the operator with the immediate contextual evidence needed to confidently apply shaping policies or migrate the victim to the backup `eth0` path."""
    
    content = re.sub(r'<!-- FILL: Brief paragraph on ce_surge_detect.*?-->', ce_sla, content, flags=re.DOTALL)

    # 8. Conclusion
    conclusion = """DECA successfully demonstrates that a fully air-gapped, multi-model predictive AI NOC Copilot is achievable on commodity hardware without cloud dependencies, directly fulfilling ISRO BAH 2026 Problem Statement 13. By building a physical multi-site SD-WAN/MPLS testbed on Raspberry Pi hardware running FRR and strongSwan, we successfully generated, captured, and labeled ground-truth telemetry under six distinct controlled fault families. Our multi-head LSTM pipeline provided a 7.1-second validation MAE for payload loss Time-to-Impact, enabling a 120-second NOC preemption window before hard SLA breaches occur. Concurrently, the XGBoost severity classifier achieved a 0.884 macro-F1 score on the Pi holdout and maintained an 0.815 macro-F1 on a rigorous, sealed 12-hour chaos run.

Crucially, DECA maintains strict adherence to the security constraints of government and space agency deployments by ensuring the entire intelligence stack operates locally. The integration of a quantized Phi-3 LLM with ChromaDB RAG proved highly effective in converting raw predictive mathematical outputs (such as ETA and severity codes) into actionable, natural-language runbook recommendations, significantly reducing the cognitive load on human NOC operators. The architecture's use of baseline-relative z-score feature engineering allows the methodology to transfer across networks with different traffic volumes, provided a short calibration campaign is executed to fit the target network's unique physics.

Future work includes wiring the validated multi-label compound fault presence layer directly into the Decide UI to better highlight quieter secondary faults during simultaneous events. Furthermore, we intend to implement a dedicated IPsec rekey-storm injector to transition the current ambient IPsec threshold rules into fully trained ML features. Finally, deploying DECA onto a staging subset of ISRO's operational backbone will empirically validate the calibration methodology and confirm the system's cross-hardware portability at a massive scale."""
    
    content = re.sub(r'<!-- FILL: 2–3 paragraphs wrapping up:.*?-->', conclusion, content, flags=re.DOTALL)

    # 9. References
    references = """[1] ISRO BAH 2026 Problem Statement 13, "AI-Driven Autonomous NOC Copilot for Air-Gapped Networks."  
[2] Free Range Routing (FRR) Community. *FRRouting 10.6.1 Documentation*. [Online]. Available: https://frrouting.org/  
[3] T. Chen and C. Guestrin, "XGBoost: A Scalable Tree Boosting System," in *Proceedings of the 22nd ACM SIGKDD International Conference on Knowledge Discovery and Data Mining*, 2016, pp. 785–794.  
[4] S. Hochreiter and J. Schmidhuber, "Long Short-Term Memory," *Neural Computation*, vol. 9, no. 8, pp. 1735–1780, 1997.  
[5] P. Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks," in *Advances in Neural Information Processing Systems*, 2020.  
[6] M. Abdin et al., "Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Device," Microsoft, 2024.  
[7] E. Rosen and Y. Rekhter, "BGP/MPLS IP Virtual Private Networks (VPNs)," *RFC 4364*, 2006.  
[8] L. Andersson, I. Minei, and B. Thomas, "LDP Specification," *RFC 5036*, 2007.  
[9] K. Nichols, S. Blake, F. Baker, and D. Black, "Definition of the Differentiated Services Field (DS Field) in the IPv4 and IPv6 Headers," *RFC 2474*, 1998.  
[10] B. Claise, B. Trammell, and P. Aitken, "Specification of the IP Flow Information Export (IPFIX) Protocol for the Exchange of Flow Information," *RFC 7011*, 2013."""
    
    content = re.sub(r'<!-- FILL: Standard IEEE/ACM references.*?-->', references, content, flags=re.DOTALL)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

fill_scaffold(r'e:\deca-isro\RESEARCH_PAPER_SCAFFOLD.md')
