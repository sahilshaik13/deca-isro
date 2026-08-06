# DECA Q3 Knowledge Base (LNC) — Document Inventory

Local Network Context for the offline RAG copilot (ChromaDB + Ollama embeddings).  
Embeddings model: **`nomic-embed-text`** (~274 MB). Chat model: **`phi3`** (load only on Ask / after Decide wake).

**Store path:** `~/deca-copilot/chroma_lnc/` · **Corpus root:** `deca-backend/runbooks/` (+ selected docs)

**Wake rule:** Q3 stays cold until Decide (or Ask). After Approve, soft-clear + force_path stay on the fast path; Q3 narrative is async.

---

## 1. Already on disk (ingest these first)

| Doc | Path | Why the copilot needs it |
| --- | --- | --- |
| Lab topology | [`deca-backend/runbooks/topology.md`](../deca-backend/runbooks/topology.md) | Hosts, IPs, VRFs, underlay, fault origin map |
| Tunnel / IPsec degradation SOP | [`deca-backend/runbooks/tunnel_degradation.md`](../deca-backend/runbooks/tunnel_degradation.md) | Rain-fade / GRE brownout actions |
| Congestion SOP | [`deca-backend/runbooks/congestion.md`](../deca-backend/runbooks/congestion.md) | Capacity / eth0 vs GRE steer |
| BGP flap SOP | [`deca-backend/runbooks/bgp_flap.md`](../deca-backend/runbooks/bgp_flap.md) | Q2 class 3 / underlay instability |
| VRF leakage SOP | [`deca-backend/runbooks/vrf_leakage.md`](../deca-backend/runbooks/vrf_leakage.md) | Mission vs admin isolation |
| Policy drift SOP | [`deca-backend/runbooks/policy_drift.md`](../deca-backend/runbooks/policy_drift.md) | AAR / cost / force_path conflicts |
| Past incidents | [`deca-backend/runbooks/past_incidents.md`](../deca-backend/runbooks/past_incidents.md) | Prior lab outcomes for analogy |
| Rain fade SOP | [`deca-backend/runbooks/rain_fade.md`](../deca-backend/runbooks/rain_fade.md) | Q2 1A/1B/1C GRE brownout → eth0 |
| CPU exhaustion SOP | [`deca-backend/runbooks/cpu_exhaustion.md`](../deca-backend/runbooks/cpu_exhaustion.md) | Q2 2A/2B crypto/CPU stress |
| TT&C preemption SOP | [`deca-backend/runbooks/ttc_sla_preempt.md`](../deca-backend/runbooks/ttc_sla_preempt.md) | Q1 120 s Decide rail / PE1 |
| Chaos compound SOP | [`deca-backend/runbooks/chaos_compound.md`](../deca-backend/runbooks/chaos_compound.md) | Overlapping held-out faults |
| BGP instability SOP | [`deca-backend/runbooks/bgp_instability.md`](../deca-backend/runbooks/bgp_instability.md) | Q2 **3A/3B** flap rate → Decide `bgp_route_flap` |
| Prom glossary | [`deca-backend/runbooks/prom_metric_glossary.md`](../deca-backend/runbooks/prom_metric_glossary.md) | Metric names for Q3 snapshot (dual Prom) |
| Dual-fabric telemetry | [`deca-backend/runbooks/dual_fabric_telemetry.md`](../deca-backend/runbooks/dual_fabric_telemetry.md) | Pi `:9090` vs GNS3 `:9091` collectors |
| Unified dual-arch ML | [`deca-backend/runbooks/unified_dual_architecture_ml.md`](../deca-backend/runbooks/unified_dual_architecture_ml.md) | Shared LSTM · fabric-selected XGBoost |
| CE SLA conflict SOP | [`deca-backend/runbooks/ce_sla_conflict.md`](../deca-backend/runbooks/ce_sla_conflict.md) | Rogue vs victim CE / bandwidth surge |

---

## 2. Core engineering docs (add to KB — high priority)

| Doc | Path | Role in RAG |
| --- | --- | --- |
| Process flow | [`docs/DECA_SDWAN_PROCESS_FLOW.md`](./DECA_SDWAN_PROCESS_FLOW.md) | End-to-end planes + AI NOC path + dual Flow 2 |
| Policy catalog | [`docs/EDGE_POLICY_LAYERS.md`](./EDGE_POLICY_LAYERS.md) | Complete AAR / CE / QoS / security / failover catalog |
| Station network | [`docs/STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) | Addressing, interfaces, restore |
| Predictive plan | [`docs/DECA_PREDICTIVE_ENGINE_PLAN.md`](./DECA_PREDICTIVE_ENGINE_PLAN.md) | Q1/Q2/Q3 meanings, red gate, severity |
| Predictive README | [`predictive/README.md`](../predictive/README.md) | How captures / protocol / live gate work |
| Orchestrator | [`DECA_ORCHESTRATOR_README.md`](../DECA_ORCHESTRATOR_README.md) | Decide rail, Approve → `force_path` |
| Telemetry pipeline | [`lab/telemetry-pipeline/README.md`](../lab/telemetry-pipeline/README.md) | Dual Kafka topics → dual Prom |
| GNS3 topology | [`lab/gns3/TOPOLOGY.md`](../lab/gns3/TOPOLOGY.md) | Sim Flow 1 path + chaos gens |
| Jury dual-fabric | [`docs/JURY_DUAL_FABRIC_DEMO.md`](./JURY_DUAL_FABRIC_DEMO.md) | Demo script Pi↔GNS3 |

---

## 3. Recommended new SOPs (draft next — map to Q2 severity)

| Proposed file | Maps to | Contents to write |
| --- | --- | --- |
| ~~`runbooks/rain_fade.md`~~ | 1A / 1B / 1C | **Drafted** — GRE rain fade / eth0 steer |
| ~~`runbooks/cpu_exhaustion.md`~~ | 2A / 2B | **Drafted** — crypto/CPU stress signatures |
| ~~`runbooks/ttc_sla_preempt.md`~~ | Q1 red gate | **Drafted** — 120 s Decide rail / PE1 actuation |
| ~~`runbooks/chaos_compound.md`~~ | Held-out chaos | **Drafted** — overlapping faults |
| ~~`runbooks/bgp_instability.md`~~ | 3A / 3B | **Drafted** — BGP flap rate / `inject_bgp_flap.sh` / red-gate 3B |
| ~~`runbooks/prom_metric_glossary.md`~~ | Tool/RAG hybrid | **Drafted** — PromQL names for Q3 snapshot |

These **six** pinpoint SOPs (plus the original topology / tunnel / congestion / generic BGP / VRF / policy / incidents set) are the sufficient LNC core for lab demos with Phi-3.

Re-ingest after edits:

```bash
cd ~/deca-copilot && . .venv/bin/activate
# Prefer unload phi3 while embedding (nomic-embed-text)
python ingest_lnc.py --reset
python query_lnc.py --no-llm "dual fabric Prometheus 9090 9091 Kafka"
```

**Ingest SOURCES** (see `~/deca-copilot/ingest_lnc.py`): all runbooks above + process/policy/predictive/KB + telemetry README + GNS3 TOPOLOGY + jury demo + orchestrator README.

**Q3 → Decide wire:** `deca-backend/q3_lnc.py` + `POST /api/v1/simulation/seed-preemption` (async `q3_nlp` on alert) + `POST /api/v1/q3/explain`.
---

## 4. Optional / later

| Doc | Notes |
| --- | --- |
| Blind / sealed incident exports | Anonymized scorecards from past campaigns |
| FRR / swanctl snippets | Only if operators need CLI recovery steps in-chat |
| Grafana/Prom query cheatsheet | For “what is station1 CPU?” style questions |

---

## 5. What not to put in the vector DB

- Raw `series.csv` / multi-day protocol captures (too large; query Prom live instead)
- Model weights (`.keras`, `.joblib`, GGUF)
- Secrets / SSH keys / `.env`
- Full Kafka logs

---

## 6. Ingest / query

```bash
export PATH="$HOME/.local/bin:$PATH"
# ollama serve  # if needed
# ollama pull nomic-embed-text

cd ~/deca-copilot && . .venv/bin/activate
python ingest_lnc.py          # build Chroma from runbooks + core docs
python query_lnc.py "rain fade GRE latency TT&C steer"
```
