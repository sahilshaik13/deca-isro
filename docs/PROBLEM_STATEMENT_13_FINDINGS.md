# PROBLEM STATEMENT 13 — Findings (done vs remaining)

**Written:** 2026-07-22 (audit, read-only); status rows updated as work lands  
**Last refresh:** **2026-08-03** — perimeter honesty (D1 · O2.2/O2.3 · P6.4 · **O4.1/O4.3 partial** · **multi-head arbitration**) · variant smoke in flight  
**Perimeter (requirements only):** [`PROBLEM_STATEMENT_13.md`](./PROBLEM_STATEMENT_13.md) — use stable IDs `PS13-*` when claiming alignment  
**Promoted classifier (untouched by casual edits):** `models/fault_classifier/` sha16 `5165d46d87ee135b`  
**Style:** same honesty bar as experiment `FINDINGS.md` files — what exists, what does not, no soft-sell.

---

## 2026-08-03 — Perimeter honesty (explicit substitutions & claim scope)

Do **not** silently imply these are closed. Judges / mentors should hear this wording.

| ID | Perimeter wording | Lab reality | Decision |
| --- | --- | --- | --- |
| **`PS13-D1`** | **SNMP** interface util / latency / jitter / errors | **Substitution:** Prometheus exporters → Kafka bridge → Prom (`:9090` Pi / `:9091` GNS3). Same signal *family* (util, RTT, jitter, loss/errors), **not** SNMP polling. | **Disclose** — claim “Prom/Telegraf path metrics (SNMP substitute)” |
| **`PS13-O2.2`** | Routing instability — **route flapping precursors** | Campaign L3 drives / labels on **`bgp_flap_count`** (counter moves **when flaps are already happening**). That is **flap severity / in-event classification** (`3A`/`3B`), **not** prediction *before* the first flap. Path **asymmetry** (GRE−eth0 / `path_asymmetry`) is a separate live signal for path stress, not a BGP precursor model. | **Downgrade claim** — say “BGP flap severity classification + path asymmetry”; **do not** say “flap precursor detection” until a leading signal (keepalive/adj timer degradation) exists |
| **`PS13-O2.3`** | Tunnel health — loss / jitter / **rekey anomalies** | Loss + jitter: **Q1 LSTMs + L4/L1 injects** — demo-ready. **Rekey:** `ipsec_rekey_*` + `rekey_anomaly.py` are **threshold rules / ambient features** in `seq_json`. **No dedicated rekey-storm injector** in the variant campaign → cannot force a demo “watch it fire.” | **Keep out of live demo path** for now (show as feature/rules if asked). Optional later: minimal rekey-storm injector — **not** blocking full variant corpus |
| **`PS13-P6.4`** | Controller misconfig / policy drift | **Separate scenario path:** CE SLA conflict (**L6** + Decide rogue/victim) and/or promoted `policy_drift` class — **not** covered by Q1 multi-head LSTM or Q2 `1A–5B` rain/CPU/BGP/loss/util families. | **Do not lump** into “Q1/Q2 protocol covers P6.4” |
| **`PS13-O4.1`** | Continuous topology awareness / **graph-based** event correlation | **Live partial:** static lab adjacency → `blast_radius` + overlapping-alert `correlated_alert_ids` / `urgency_boost` on seed (`topology.py`). **Not** a learned graph model, streaming multi-source correlation engine, or dynamic discovery. | **Downgrade claim** — say “static blast-radius + clique correlation on Decide”; **do not** say full O4.1 graph correlation |
| **`PS13-O4.3`** | Automated **playbook** suggestion / multi-candidate engine | **Live partial:** severity/class → one ranked step list + budgeted `bgp_soft_clear`→`force_path` (`playbooks.py`). **Not** a multi-candidate ranking engine that scores alternate books against impact/risk. Compound uses `chaos_compound` as honesty SOP. | **Downgrade claim** — say “ranked single-path playbook + budgeted Approve sequence”; Phase-2 = multi-candidate engine |

**Net for judging:** D1/D3/D4/D5 and O2.1 / O2.4 (util/latency TTI) are demo-ready as designed. **O2.2 precursor**, **O2.3 rekey injectability**, and **O4.1/O4.3 full-spec** are the places lab work is real but **not** perimeter-complete — claims above are the official downgrade until closed.

### Multi-head arbitration (compound) — deliberate policy

When congestion + flap (etc.) light **several Q1 TTI heads + Q2** at once, the copilot is **not** left undefined:

| Layer | Rule | Owner |
| --- | --- | --- |
| **Gate red** | **OR** of hot TTI heads with ETA ≤ `red_sec` (+ red-severity gate) | `infer_q1_q2_live.classify_gate` + parallel loss/jitter/util |
| **Primary issue reported** | **Q2 severity argmax** (`root_cause` / title class) — owns the *why* | XGBoost severity bundle |
| **Urgency clock** | **min** ETA among firing TTI heads | `predictive/alert_fusion.py` |
| **Clock language (display)** | Leading head **util** → “approaching HTB ceiling”; lat/loss/jitter → “SLA breach” — Decide title/summary/concerns + fleet tooltip | `urgency_clock_kind` on seed payload · AlertRail / FleetStrip |
| **Transparency** | Seed payload includes `arbitration.firing_tti_heads` + `compound_suspected` | Decide card / audit |
| **Playbook** | Still keyed off **primary** Q2 class; compound → treat as hypothesis (`chaos_compound` runbook) | `playbooks.py` |

**L6 (CE SLA):** outside **Q1** (no dedicated head; shares util LSTM ceiling clock with L5) — **inside Q2** as `6A`/`6B` side-track + Decide rogue/victim. Util Q1 cannot distinguish organic congestion vs rogue CE; that distinction is Q2/Decide, not a forgotten model home.

**Not claimed:** multi-label Q2, learned fusion, or “highest severity wins” overriding argmax. Worst-of-family severity is a **train/label** helper (`window_severity`); live primary remains Q2 argmax. Code: [`predictive/alert_fusion.py`](../predictive/alert_fusion.py).

---

## 2026-08-01 amendment — Decide-rail predictive path (parallel to promoted 5-class)

The tables below still document the **promoted `models/fault_classifier/`** live-operator stack. Separately, the **NOC Decide rail** now runs:

| Capability | Status | Evidence |
| --- | --- | --- |
| Q1 multi-head LSTM (latency / loss / jitter / util TTI) | **Live (cutover)** | `data/deca/predictive/protocol_models/lstm_q1*` · [`predictive/launch_infer_q1_q2_cutover.sh`](../predictive/launch_infer_q1_q2_cutover.sh) |
| Q2 XGBoost severity + path-asymmetry features | **Live** | `protocol_models/xgb_q2_sev` · severity `1A–5B` |
| Path asymmetry named detector | **Live** | GRE−eth0 + Prom `path_asymmetry` |
| Loss progression TTI (real netem GT) | **Live model** · full corpus still capturing | L4 inject + `lstm_q1_loss` |
| IPsec rekey anomaly | **Rules only — not live-demo injectable** | `ipsec_rekey_*` Prom + `rekey_anomaly.py`; **no campaign inject** — out of forced demo path |
| Topology blast-radius / correlated alerts | **Live (partial O4.1)** | Static adjacency blast-radius + clique ids — **not** full graph-correlation engine |
| Ranked playbooks + budgeted soft-clear→force_path | **Live (partial O4.3)** | Single ranked path + Approve sequence — **not** multi-candidate playbook engine |
| Multi-head arbitration (compound) | **Live (explicit)** | OR-red · Q2 primary · min-ETA urgency · `firing_tti_heads` |
| Q3 Phi-3 + Chroma on Decide | **Live (async)** | Orchestrator `:8000` · does not block Approve |
| Protocol `--full` schema v2 | **Baseline captured** | Stamp `20260729T202832Z` — clone-recipe iters; **retrain on variants** |
| Variant + compound train path | **Hardened** | Unique recipes · traffic×fault matrix · CE SLA L6 · chaos holdout · `accuracy_contract` in plan |
| L2 CPU metric | **Fixed** | Gate on `cpu_usage_user` (not system) |
| Prophet / dual-P netns | **Not claimed** | Suggested Tools / scripts only |

Canonical narrative: [`DECA_SDWAN_PROCESS_FLOW.md`](./DECA_SDWAN_PROCESS_FLOW.md) · [`DECA_PREDICTIVE_ENGINE_PLAN.md`](./DECA_PREDICTIVE_ENGINE_PLAN.md).

---

## 2026-08-03 — Pi 10m coverage (inject textures)

Stamp `pi_coverage_10m_20260803T130315Z` · `coverage_report.json` **ok=true**.

| Phase | Primary gate | Result |
| --- | --- | --- |
| L1 rain | lat max ≥ 25 ms | PASS |
| L2 CPU | **user** CPU ≥ 50% | PASS |
| L3 BGP | flap Δ ≥ 5 | PASS |
| L4 loss | loss max ≥ 1% | PASS |
| L5 util | util max ≥ 12 Mbps | PASS |
| Compound | rain + CPU overlap | PASS |

`PS13-P6.4` (controller policy drift / CE SLA) is a **separate demo/train track** (L6 CE SLA conflict + Decide rogue/victim; promoted `policy_drift` where used) — **not** part of Q1 LSTM heads or Q2 `1A–5B` protocol families. Do not cite L1–L5 smoke as P6.4 coverage.
---

## One-line verdict

| Layer | Status |
| --- | --- |
| Lab + telemetry + predictive ML (Objectives 1–2, Phases 1–3) | **Largely built** on 3-Pi multi-site SD-WAN/MPLS + **dual-fabric GNS3** collectors (Prom `:9090` Pi / `:9091` GNS3) — [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) · [`lab/gns3/TOPOLOGY.md`](../lab/gns3/TOPOLOGY.md) |
| Offline LLM + RAG scaffolding (Objective 3, Phase 4) | **Done (local)** — GGUFs + Chroma; HF cold-start disabled; corpus includes topology + incidents |
| Copilot wired to real predictions + NOC workflow (Objectives 3–4, Phases 5–6) | **Obj3 Yes / Obj4 minimal** — bridge + Phase-6; corr groups + ordered runbooks — [`OBJ4_MINIMAL_FINDINGS.md`](./OBJ4_MINIMAL_FINDINGS.md) |
| Air-gap of **live ML inference** | **Mostly clean** (lab Prom scrape only); **no compliance demo harness** |

**Bottom line for planning:** Phases 1–3 are the project’s real strength. Phases 4–6 are the remaining gap — and the demo backend is **not** a finished Phase 5; it must be integrated (or rebuilt) against the promoted **5-class** stack.

---

## Scoreboard vs the three operator questions

| Question | ID | Today | Gap |
| --- | --- | --- | --- |
| **Q1** What fails next — and when? | `PS13-Q1` | Live operator: confirmed/advisory class + optional LSTM `eta_minutes` (`scripts/deca_live_operator.py` declare ~403–423) | Not always precursor-first; some classes detect in-window. Copilot does not narrate Q1 from the promoted model. |
| **Q2** Why elevated — which signals? | `PS13-Q2` | Partial: confidence + circumstance + (backend) z-score `contributing_signals`; docs describe SHAP | No SHAP-in-prod path; live stack does not emit NL “why” tied to top features. |
| **Q3** What action before impact? | `PS13-Q3` | Ordered runbook steps on structured alerts (`deca_copilot_bridge`); 5 SOPs in Chroma | No playbook *executor*; sequencing is runbook order, not dynamic branching |

---

## Objective-by-objective

### Objective 1 — Simulated SD-WAN/MPLS environment `PS13-O1`

| Requirement | ID | Status | Evidence |
| --- | --- | --- | --- |
| Multi-site CE/PE/P roles | `PS13-O1.1` | **Done (lab-scale)** | 3 Pis host five sites (CORE/SAC/NRSC/Mauritius/MCF); mermaid + addressing in [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) |
| Role-differentiated expansion (Hub / Datacenter / Branch / Distant) | `PS13-O1.1` | **Done (lab)** | Mauritius distant branch + netem, SAC bulk vs NRSC light — see [`NETWORK_EXPANSION_FINDINGS.md`](./NETWORK_EXPANSION_FINDINGS.md) |
| MPLS / VPN segmentation / TE | `PS13-O1.2` | **Done (lab)** | Native BGP VPNv4 + LDP over GRE; **OSPF-TE TED + pathd SR-TE** preferred/backup policies (BSID 40001/40002) — [`NETWORK_EXPANSION_FINDINGS.md`](./NETWORK_EXPANSION_FINDINGS.md) Phase TE. **Not RSVP-TE** (unavailable in FRR 10.6). HTB is QoS, not TE. |
| SD-WAN IPSec + BGP/OSPF + QoS | `PS13-O1.3` | **Done (lab)** | IPsec + BGP/OSPF + multi-class QoS; **voice+video** dynamic path controller with voice-wins conflict — `lab/deca_sdwan_controller.py` |
| Traffic + fault injection | `PS13-O1.4` | **Done** | `scripts/deca_fault_campaign.py`, compound campaigns, blind chaos / sealed truth |
| Suggested EVE-NG/GNS3/Containerlab | *(suggested)* | **GNS3 dual-fabric live** (Pi remains primary capture) | `lab/gns3/` · same NOC; separate Prom `:9091` |

**Remaining:** None material for lab-scale Obj1; pitch as physical multi-site Pi lab with OSPF-TE/SR-TE + application-aware SD-WAN path selection (not EVE-NG, not RSVP).

---

### Objective 2 — Predictive fault analytics engine

Target stack for the **Decide rail** is multi-head LSTM + XGBoost severity (not Prophet/graph-ML) — [`DECA_PREDICTIVE_ENGINE_PLAN.md`](./DECA_PREDICTIVE_ENGINE_PLAN.md). Promoted 5-class stack remains as documented in rows below.

| Requirement | Status | Evidence |
| --- | --- | --- |
| Precursor / not only threshold breach | **Mostly done** | XGBoost gate + multiclass head, temporal loom, advisory tier, baseline-relative `_z_*` features; Decide rail adds **120 s ETA** gate |
| Congestion / util / latency | **Done** | Class `congestion_breach`; Decide util-TTI LSTM through HTB |
| Routing instability (BGP; OSPF) | **Partial — claim downgraded** | Decide/Q2: **BGP flap severity** (`bgp_flap_count` → `3A`/`3B`) during/after flaps — **not** flap-*precursor* ML. Path asymmetry live separately. OSPF not first-class. See perimeter honesty table. |
| Tunnel degradation | **Done** | Class `tunnel_degradation` |
| Time-to-impact | **Done (Decide path)** / Partial (promoted TTI leg) | Multi-head LSTM cutover on Decide; older TTI validation notes remain for promoted congestion leg — [`TTI_VALIDATION_FINDINGS.md`](./TTI_VALIDATION_FINDINGS.md) |
| Packet-loss progression ML | **Done (Decide path)** | Real netem L4 + `lstm_q1_loss` |
| Path asymmetry | **Done** | Named detector + Q2 features + Prom |
| IPsec rekey anomaly | **Partial (rules; not demo-forced)** | Exporters + threshold rules exist; **no rekey-storm inject** in variant campaign — keep off live “inject → fire” demo |
| Fault classes (promoted) | **Done (5)** | Prior four + `policy_drift` (2026-07-24 school-exam promote) |
| Documented hard limitation | **Done (honest)** | Compound quieter-leg drowning — textbook Ch.11 / `models/archive/experiments/compound_*` |

**Remaining:** Stronger OSPF story if required; full-corpus retrain after `20260729T202832Z`; Prophet/graph-ML stay optional.

---

### Objective 3 — Offline LLM NOC Copilot

Q3 path (Phi-3 + Chroma RAG → Decide rail) is **live** — [`DECA_PREDICTIVE_ENGINE_PLAN.md`](./DECA_PREDICTIVE_ENGINE_PLAN.md) · [`DECA_Q3_KNOWLEDGE_BASE.md`](./DECA_Q3_KNOWLEDGE_BASE.md). DeepSeek GGUF removed earlier; production path uses **Ollama Phi-3**.

| Requirement | Status | Evidence |
| --- | --- | --- |
| Quantized local LLM on disk | **Done (Ollama Phi-3)** | User systemd orchestrator; air-gapped |
| Load via llama.cpp / local runtime | **Done** | Ollama path + optional llama.cpp remnants in backend |
| RAG over runbooks | **Done** | Chroma `deca_lnc` / runbooks collection |
| RAG over topology maps | **Done** | `deca-backend/runbooks/topology.md` indexed |
| RAG over past incidents | **Done** | `past_incidents.md` from sealed blinds |
| Structured response schema | **Done** | Decide `q3_nlp` merge |
| NL query interface for operators | **Done** | Decide rail + `query_lnc.py` / bridge CLI |
| Wired to Decide predictive gate | **Done** | Async after seed-preemption; does not block Approve |

**Remaining (Obj3 polish only):** JSON reliability under load; portable “WAN egress blocked” demo harness optional.

---

### Objective 4 — Integrated NOC workflow automation

| Requirement | Status | Evidence |
| --- | --- | --- |
| Continuous topology awareness / graph correlation | **Partial (Decide)** | Static blast-radius + `correlated_alert_ids` — satisfies lab O4.1 *slice*, **not** full graph-based correlation (`PS13-O4.1` downgrade above) |
| Confidence-scored alert prioritization | **Done (Decide)** / Partial (promoted) | XGBoost proba + min-firing-TTI urgency; multi-head OR-red + Q2 primary (`alert_fusion`) |
| Automated playbook suggestion / sequencing | **Partial (Decide)** | Ranked single-path + budgeted `bgp_soft_clear`→`force_path` — **not** multi-candidate engine (`PS13-O4.3` downgrade) |
| Operator-ready incident summaries | **Done (Decide Q3)** | Async Phi-3 narrative on Decide card |

**Remaining:** Silent auto-remediate still **not** claimed (HITL Approve required); Phase-2 graph correlation + multi-candidate playbooks **not** built.

---

## Phase checklist (expected solution steps)

| Phase | Intent | Done? | Notes |
| --- | ---: | --- | --- |
| **1** Network simulation | Topology + traffic + inject | **Yes (Pi lab)** | Multi-site SD-WAN/MPLS; OSPF-TE/SR-TE; not EVE-NG — see [`STATION_NETWORK_SETUP.md`](./STATION_NETWORK_SETUP.md) |
| **2** Telemetry pipeline | Local Prom/Telegraf time-series | **Yes** | Lab scrapes `192.168.50.{10,20,30}:9273`; lake in `data/processed/` |
| **3** Predictive modelling | Train/validate, lead time, FPR | **Yes (strong)** | School exam gate, blinds, control FA, specificity; documented compound gap |
| **4** Offline LLM deployment | Bundle + local RAG | **Yes (local)** | GGUFs + Chroma (topology + incidents); HF download disabled by default |
| **5** Copilot integration | Predictions → structured NL | **Yes** | Bridge from promoted declarations → intact alerts |
| **6** Scenario validation (copilot) | Congestion / BGP / tunnel / policy-drift **with** copilot quality | **Yes (scored)** | See [`COPILOT_INTEGRATION_FINDINGS.md`](./COPILOT_INTEGRATION_FINDINGS.md); BGP alert quality still gated by BGP ML confirms |

### Phase 6 scenario map (ML vs copilot)

| Scenario | ML / blind evidence | Copilot validated? |
| --- | --- | --- |
| Progressive congestion | Yes (class + blinds) | Yes — structured alerts schema-complete ([`COPILOT_INTEGRATION_FINDINGS.md`](./COPILOT_INTEGRATION_FINDINGS.md)) |
| BGP flap + cascade | Yes (class + Tier-5; exam F1 wound ~0.50 pending harden) | Partial — bridge OK when ML confirms; compound BGP blind lacked origin BGP confirm |
| MPLS/tunnel degradation | Yes | Yes — schema-complete alerts |
| Controller / policy drift | **Yes** — promoted 5-class + origin-lock blind HIT — [`POLICY_DRIFT_PROMOTION_FINDINGS.md`](./POLICY_DRIFT_PROMOTION_FINDINGS.md) | Yes — schema-complete alerts |

---

## Dataset required vs what we actually collect

**Verdict: PS13-D1–D5 = Yes with disclosed substitutions** (gate: `scripts/validate_data_sample.py` exit 0 on 2026-07-24).

| ID | Required signal family | Status |
| --- | --- | --- |
| `PS13-D1` | Interface util / latency / jitter / errors | **Yes via substitution** — perimeter says SNMP; lab uses **Prometheus exporters + Kafka bridge** (same family, not SNMP poll). Must say so aloud. |
| `PS13-D2` | Syslog + BGP/OSPF adjacency events | **Yes** — Phase D exporters: `syslog_err_count`, `ospf_adj_up`, `bgp_mauritius_adj_up`, `bgp_flap_count`, `path_asymmetry_ratio` (+ related); lab gauges, not a vendor syslog archive |
| `PS13-D3` | NetFlow/IPFIX | **Yes (lab softflowd IPFIX)** — see expansion Fix 3; port-class counters + ESP aggregate |
| `PS13-D4` | SD-WAN controller streaming telemetry | **Yes** — full 12/12 incl. `sdwan_path_healthy_*`; Prom + `METRIC_MAP` / unified raw |
| `PS13-D5` | Injected fault ground truth | **Yes** — sealed GT + fault logs + unified labels; **`policy_drift` / CE SLA = P6.4 path**, distinct from L1–L5 Q1/Q2 protocol book |
| *(extra)* | Path asymmetry / IPsec rekey | Asymmetry **Yes (lab)**; rekey **gauges/rules Yes**, **injectable demo No** (see O2.3 honesty) |

See also: [`DATA_SAMPLE.md`](./DATA_SAMPLE.md), [`NETWORK_EXPANSION_FINDINGS.md`](./NETWORK_EXPANSION_FINDINGS.md).

---

## Air-gap (Objective 3 + success criterion)

| Check | Status |
| --- | --- |
| Live ML path cloud APIs | **None** — only `requests.get` to Prometheus (`scripts/deca_live_common.py:126–138`, caller `deca_live_operator.py:635`) |
| Default Prom URL | Dual: Pi `localhost:9090` · GNS3 `localhost:9091` (`prom_url_for_fabric`) |
| Training-time internet scripts | Exist (`fetch_public_data.py`, `routeviews.py`, `ripe_atlas.py`, `cisco_scraper.py`) — **not** on live tick path |
| Backend LLM cold-start | **Hard-fail** if GGUF missing unless `DECA_ALLOW_HF_DOWNLOAD=1` (`main.py` / `models.py`) |
| Air-gap **demonstration** harness | **Partial** — default path refuses HF; optional WAN-block netns demo still missing |

---

## Artifact map (where the two stacks live)

| Stack | Path | Role today |
| --- | --- | --- |
| Production-ish ML + live NOC feed | `scripts/deca_live_operator.py`, `scripts/deca_inference.py`, `models/fault_classifier/` | Real 5-class detection + loom (incl. `policy_drift`) |
| Live→copilot bridge | `scripts/deca_copilot_bridge.py`, `deca_copilot_query.py`, `deca_copilot_phase6_score.py` | Promoted declarations → intact alerts + thin NL + Phase-6 score |
| Demo / RAG backend | `deca-backend/`, Chroma LNC, `runbooks/` | Ollama Phi-3 + RAG on Decide Ask |
| Decide-rail predictive | `predictive/` + `protocol_models/` | Multi-head Q1 + Q2 severity cutover |
| Canonical as-built | `docs/DECA_SDWAN_PROCESS_FLOW.md` | End-to-end Flow 1–3 + PS13 scoreboard |
| Compound limitation receipts | `models/archive/experiments/compound_*` | Honest ML edge-case documentation |

---

## What we have to do next (planning list only — not a build plan)

1. **Variant smoke gates (Pi + GNS3)** → review scores with user → **full only on explicit go** (no auto-start).
2. **Keep O2.2 / O2.3 claims as downgraded** unless closing work lands: flap precursor signal, or minimal rekey-storm injector for demo.
3. **P6.4** stays on L6 CE SLA / Decide rogue-victim (and promoted `policy_drift` if shown) — not Q1/Q2 L1–L5.
4. **Optional air-gap demo harness** — WAN-block netns while Prom stays lab-local.
5. **Dual-P / Prophet** — stay optional / not claimed.

---

## Explicit non-goals of this document

- Does not change code, promote models, or claim Phase 5/6 complete.
- Does not treat exam macro-F1 alone as PS success (success = lead time + operator-ready NL without cloud).
- Does not hide the compound quieter-leg limitation or the backend↔live split.
