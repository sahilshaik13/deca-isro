# DECA-ISRO Technical Architecture & ML Blueprint
**Project:** Distributed Enterprise Connectivity Anomaly (DECA) Framework  
**Domain:** Network Intelligence, Edge Hardware Simulation, and Machine Learning  

---

## 1. Project Overview & Objectives
The DECA framework is an enterprise-grade machine learning pipeline engineered to detect, classify, and predict complex network infrastructure failures. Traditional network monitoring relies on rigid, threshold-based rules (e.g., triggering an alert when CPU hits 90%), which inherently generate high false-positive rates and fail to detect sophisticated, slow-degrading anomalies. 

DECA solves this by fusing physical hardware network simulations with macroscopic internet datasets. This unified telemetry plane trains an AI model to understand the nuanced mathematical velocity and acceleration of a network failure *before* a catastrophic outage fully materializes.

---

## 2. Physical Hardware Architecture & Topology

### The Edge Lab (Raspberry Pi Data Plane)
The foundation of the DECA data generation process is a physical cluster of Raspberry Pi microcomputers. Unlike software simulators (such as GNS3 or Mininet), physical hardware introduces genuine real-world constraints—CPU interrupts, actual interface queuing, and hardware-level packet processing delays. This ensures the model learns from a high-fidelity "ground truth" environment rather than mathematically perfect (and therefore unrealistic) software simulations.

### The CE-PE-CE Backbone Simulation
The laboratory network is configured using a standard telecommunications **CE-PE-CE (Customer Edge — Provider Edge — Customer Edge)** topology, powered by the FRRouting (FRR) protocol suite.
*   **Establishment:** This topology perfectly mirrors a Carrier Ethernet or MPLS VPN transit backbone. The Provider Edge (PE) routers establish BGP peering sessions to dynamically exchange routing tables.
*   **VRF Segmentation:** We utilize Virtual Routing and Forwarding (VRFs), specifically isolating traffic within an `ADMIN` VRF. This mimics the logical segmentation ISPs use to separate enterprise customer traffic over a shared physical medium.
*   **Fault Injection Capabilities:** This architecture allows us to target specific protocol layers. We can inject carrier-grade faults—such as BGP route flaps, tunnel degradation (packet loss/delay via `netem`), volumetric congestion breaches, or malicious VRF route-target leakages—directly into a live routing daemon.

### The Orchestrator (Control & Intelligence Plane)
While the RPis handle the data plane, a central laptop environment acts as the Command Orchestrator and ML Compute Hub.
*   **Command & Control:** Automated scripts execute SSH commands across the RPis to generate randomized background traffic (15–85 Mbps) and trigger network faults on a dynamic, deadline-driven schedule.
*   **Telemetry Scraping:** The orchestrator queries the Prometheus API to pull high-resolution time-series metrics (`ifInOctets`, `packet_loss_pct`, `jitter_ms`) from the edge hardware.
*   **Heavy Compute:** Model training (specifically Deep Learning Autoencoders and XGBoost trees) requires significant memory bandwidth. By isolating the ML processing loop to a dedicated local environment, we ensure the heavy data fusion logic does not artificially bottleneck the physical network hardware during data collection.

---

## 3. Data Strategy & Feature Engineering

An anomaly detection model's intelligence is strictly limited by the diversity and **context** of its training matrix. The data lake is tiered for the Nvidia Digital Fingerprinting blueprint:

1. **Lab Telemetry (Tier 3 — Ground Truth):** RPi campaign logs under `data/rpi-net/` with real `netem`, FRR BGP, and VRF faults. This is the only supervised label source for `bgp_route_flap`, `vrf_leakage`, `tunnel_degradation`, and `congestion_breach`. Synthetic fault generators are **intentionally excluded** from `rebuild_unified.py` — they add noise once real Pi labels exist.
2. **RouteViews + RIPE RIS (Tier 1 — Structural BGP Context):** Compressed MRT update files (`*_updates.*.bz2` / `.gz`) aligned to the Jul 8–12 2026 window. These feed BGP update-rate and path-change features — not flat `timestamp,value` stubs.
3. **RIPE Atlas (Tier 1 — Macro Latency Baseline):** `ripe_atlas.py` → baseline snapshot + **`ripe_atlas_ping_sampled.csv`** (~188k rows). The full history (~24M rows) is deliberately not kept: unfiltered it would make public∶lab ≈ **660∶1** and drown the RPi ground truth; sampled drops that to ≈ **5.6∶1** — still public-heavy as a lower-weight validation layer, without erasing the campaign.
4. **BGP Routing Labels (Tier 1 — ASN-Keyed Events):** `bgp_routing_labels.csv` / `ioda_outage_labels.csv` — genuine macro outage inventory. **Not applied as feature labels today:** event starts cluster ~Jul 5 while Atlas/BGP-rate telemetry used in unify is ~Jul 8–13 (no time overlap). Held as `processed/public_outage_labels_provenance.csv` until overlapping telemetry exists.
5. ~~AS Organization Map~~ — removed; not used in the trainable set (`as_org.py` deleted).
6. **MAWI Samplepoint-F (magnitude calibration only):** hand-made `mawi_sample.csv` (no automated downloader; robots.txt / “authentic not huge”). Flat even-split → slopes/std ~0; Pi + Atlas + Cisco carry variance.

**Strategic Data Pruning (removed as ML noise):**
- Flat sample CSVs (`caida_sample.csv`, `ripe_ris_sample.csv`) and CAIDA volumetric / telescope dumps.
- Synthetic telemetry — obsolete once RPi hardware generates ground truth (`rebuild_unified.py` never regenerates it).
- Generic IODA rows with `entity_code=Unknown` — replaced by ASN-filtered BGP outage queries.

**Data-generation scripts (kept):** see [`DATA_GEN.md`](DATA_GEN.md) — all under `scripts/` (`deca_fault_campaign.py`, `fetch_public_data.py`, `routeviews` / `riperis` / `parse_bgp` / `bgpstream` / `ioda` / `ripe_atlas`, `cisco_scraper.py`, `rebuild_unified.py`).
### Time-Series Feature Engineering
Raw interface counters are insufficient for predictive analytics. The pipeline calculates a 40-column rolling feature matrix per host, engineering metrics such as:
*   **Slopes:** Tracking the immediate rate of change.
*   **Rolling Standard Deviations:** Measuring localized volatility.
*   **Accelerations:** Second-derivative metrics (`ifInOctets_accel`) designed to flag the sudden velocity changes of a failure state.

---

## 4. Machine Learning Blueprint: Nvidia Digital Fingerprinting

The training architecture strictly follows Nvidia's **Digital Fingerprinting Blueprint**, a two-stage ensemble model optimized for complex cybersecurity and network intelligence telemetry.

### Stage 1: Deep Learning Autoencoder (Unsupervised)
*   **Mechanism:** A neural network trained *exclusively* on healthy, normal baseline traffic (collected during the 15–25 minute rest periods between campaign injections). 
*   **The Bottleneck:** The architecture forces the 40 engineered features through a highly compressed inner layer (e.g., 8 nodes). To successfully reconstruct the output, the network must learn the fundamental mathematical correlations of a healthy network state.
*   **The Tripwire:** When a network fault is introduced, the telemetry deviates from the learned baseline. The Autoencoder fails to reconstruct the data accurately, generating a massive spike in Mean Squared Error (MSE):
    $$MSE = \frac{1}{n} \sum_{i=1}^{n} (Y_i - \hat{Y}_i)^2$$

### Stage 2: Multiclass XGBoost Classifier (Supervised)
*   **The Classification:** The XGBoost model ingests the original 40 structural features *plus* the new MSE reconstruction error calculated by the Autoencoder. 
*   **The Logic:** While the Autoencoder detects that *something* is wrong, the XGBoost layer maps the specific characteristics of the error to our hardware labels, easily distinguishing between a `vrf_leakage` and a `bgp_route_flap` across varying traffic loads.

---

## 5. Performance Expectations

Because the engineered feature plane isolates the *velocity* and *acceleration* of metrics rather than relying on static integers, the ensemble model generalizes exceptionally well.
*   **Expected Accuracy Target:** **92% to 96%** (F1-Score / Macro Average).
*   **Justification:** The two-stage ensemble practically eliminates false positives. The Autoencoder establishes an incredibly rigid mathematical boundary for "normal" operations, shielding the XGBoost tree-logic from classifying standard heavy traffic loads as congestion breaches.

---

## 6. Project Deliverables

The culmination of the DECA framework will yield a deployable, enterprise-ready software asset package for ISRO:

1.  **The DECA Intelligence Engine:** Compiled, production-ready model weights (`.pth` PyTorch binaries and `.json` XGBoost trees) capable of executing live inference against streaming network telemetry.
2.  **Automated Hardware Campaign Architecture:** The complete Python orchestration suite used to generate dynamic loads, trigger carrier-grade faults via SSH, and collect metrics via Prometheus.
3.  **Unified Feature Matrix:** Processed `.parquet` datasets providing a high-fidelity benchmark for future predictive network research.
4.  **Developer Boilerplate Repository:** A cleanly documented, containerized codebase designed with a "build in public" philosophy. This boilerplate repository will allow ISRO engineers to instantly deploy the CE-PE-CE telemetry scraper and ML fusion pipeline into their own environments, drastically reducing the trial-and-error typically associated with hardware data alignment and dependency management.