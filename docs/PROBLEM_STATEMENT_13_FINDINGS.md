# PROBLEM STATEMENT 13 — Findings (done vs remaining)

**Written:** 2026-07-22 (audit, read-only); status rows updated as work lands  
**Last refresh:** **2026-08-06** — util CAPTURE_CONTRACT root-cause chain (offer · PE class miss · BE 1:20 lift) · jitter cite scrub · planning list refresh  
**Prior:** **2026-08-05** board lock · **2026-08-04** scoreboard honesty · GNS3 L3 selection honesty · perimeter honesty  
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

**Architecture note (2026-08-04):** quieter-leg drowning is **not** fixed by more compound capture into single-label Q2 — already proved (exam F1 rose, collision slices did not). Closing it requires a **separate multi-label presence layer** (+ SLA-normalized features + collision-pair reweight), scored with the same chaos_dev/chaos_final discipline. Until then: disclose and demo Q1 heads + Q2 dominant. Details: [`MULTI_FAULT.md`](../data/deca/predictive/MULTI_FAULT.md).

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
| Multi-head arbitration (compound) | **Live (explicit)** | OR-red · Q2 primary · min-ETA · `firing_tti_heads` · Decide compound panel · blast radius · [`MULTI_FAULT.md`](../data/deca/predictive/MULTI_FAULT.md) — **more COMPOUND volume ≠ drowning fix** (architectural: single-label argmax); Phase-2 = multi-label **presence** layer beside Q2 |
| Q3 Phi-3 + Chroma on Decide | **Live (async)** | Orchestrator `:8000` · does not block Approve |
| Protocol `--full` schema v2 | **Baseline captured** | Stamp `20260729T202832Z` — clone-recipe iters; **retrain on variants** |
| Variant + compound train path | **Hardened** | Unique recipes · traffic×fault matrix · CE SLA L6 · chaos holdout · `accuracy_contract` in plan |
| **Model scores (canonical)** | **LOCKED** | [`PREDICTIVE_MODEL_SCORES.md`](./PREDICTIVE_MODEL_SCORES.md) · cite **0.884 / 0.815 / 0.655 / 0.992 / 7.1s** · frozen `d2` won **six** honest NO_PROMOTEs · current-data ceiling ~0.72/0.62/0.55 · BGP ~0.62 disclosed · do not cite 0.101 / 0.533 / 0.544 / ~1838s |
| L2 CPU metric | **Fixed** | Gate on `cpu_usage_user` (not system) |
| Prophet / dual-P netns | **Not claimed** | Suggested Tools / scripts only |

Canonical narrative: [`DECA_SDWAN_PROCESS_FLOW.md`](./DECA_SDWAN_PROCESS_FLOW.md) · [`DECA_PREDICTIVE_ENGINE_PLAN.md`](./DECA_PREDICTIVE_ENGINE_PLAN.md) · scores index [`PREDICTIVE_MODEL_SCORES.md`](./PREDICTIVE_MODEL_SCORES.md).

---

## 2026-08-04 — Predictive scoreboard honesty (eval fixes ≠ retuning)

**Cite:** holdout **0.884** · chaos_final **0.815** · GNS3 **0.655** · Q2 root **0.992** · Q1 loss val MAE **7.1s** (n=185).

### GNS3 L3 selection honesty (caught before execution)

**Risk class:** not “pipeline lying to us” (eval/label bugs) — **“we were about to make the pipeline lie”** by deleting honest data and fabricating labels.

| Temptation (rejected) | Why it is worse than a tuning mistake |
| --- | --- |
| `rm -rf` soft `l3_storm_*` (rate≈0.43 → **3A**) | Erases the real quieter-twin transfer signal |
| Replace with `period=1` + auto `bgp_flap_count` EXTRA → forced **3B** | Fabricates the severity band you are trying to measure |

**Locked policy:**

1. **Keep** original GNS3 soft storms — storm→often **3A** is **disclosed twin behavior**, not a bug.
2. **Remove** auto counter EXTRA entirely (no dormant nudge).
3. **Additive only** `l3_storm_hard_*` at **period=3** — if they still land 3A, disclose; never delete soft runs.
4. Pi `storm_3` redo is separate (corrupt counter jump) — archive under `_pre_best_storm/`.

**Reporting rule:** even if hard storms later hit 3B reliably, do **not** let slides/scores become “GNS3 L3 = hard 3B only.” Soft twin remains visible.

Artifact: [`L3_SELECTION_HONESTY.md`](../data/deca/predictive/protocol_gns3/eff_pack_gns3_20260804T094436Z/L3_SELECTION_HONESTY.md).

---

### Chaos_final — same model, cleaner score

**One line that pre-empts the judge question:** chaos_final was scored twice — the first run surfaced **evaluation/labeling bugs** (not model quality); both were fixed; the **same** promoted model `d2_e100_l6_mcw3` was rescored once clean. **Model selection never touched chaos_final.**

### Sequence (do not collapse into “we retuned until 0.815”)

| Step | What happened | Number |
| --- | --- | ---: |
| Select | Rank configs on **chaos_dev** only (`t_rel < 3600`) | winner `d2_e100_l6_mcw3` |
| Contaminated full-chaos peek | Multi-config rank on full chaos — **do not cite** | 0.533 |
| First chaos_final | Contig XGB class id compared to raw `SEVERITY_TO_ID` — **eval bug** | 0.101 |
| After contig map | Instant/row-by-row BGP stamp under-labeled final half — **labeling bug** | 0.544 |
| Clean one-shot | Full-series severity stamp + 10s rolling BGP flap rate; **same weights** | **0.815** |

Both bugs were **evaluation/labeling**, not model changes. Auditing an implausibly bad score found the pipeline was lying; fixing the lie is meaningfully different from retuning until the number improved.

### BGP phase ~0.62 — disclosed limitation (not another silent eval bug)

Audited before assuming a capability ceiling:

- Family (root=3) recall on BGP windows ≈ **0.86** — model knows it is flap texture.
- Exact severity ≈ **0.62** — mainly **3A→3B over-call** + quiet gaps labeled `0` while the model still fires `3B`/`5B`.
- Switching window GT from worst-of (`window_severity`) to mode does **not** reveal a contig-style bug; it makes exact match worse because the model persistently predicts `3B`.
- Retrain with rolling BGP labels (same knobs) **regressed** (holdout 0.767 / final 0.583) — correctly **not** promoted.

**Decision:** disclose BGP severity carefully — **fresh specialist @0.85 → exact 0.886** on sealed one-shot ([`ONESHOT_VERDICT.json`](../data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/ONESHOT_VERDICT.json)); do **not** cite the old ~0.62 exact / FV-final path as the live claim. Family recall remains strong. Same honesty posture as O2.3 rekey / O2.2 precursor for *precursor* language. No further Q2 retrain pass unless new labeled flap data or multi-scale features land.

Hard-stop audit (`train_logs/bgp_roll_retrain/BGP_HARD_STOP_AUDIT.json`): mild-boundary rows ≈ 0; 251/340 BGP windows mix 3A+3B (intermittency, not contig-style bug). Multi-roll GT with default bands does not honestly clear +0.05 without lowering the 3B threshold to flatter the model’s over-call — **rejected**. Prior rolling-label retrain already regressed. **Stop.**

### Q1 chaos TTI MAE ~1838 — found a real bug, fixed it, honest number

**One line (same shape as chaos_final / BGP):** old ~1838s was a **full-series ETA eval bug**, not a weak model — rain/CPU windows were scored against a loss breach ~3700s later; scoped to loss phase (`gt_root==4`) → **~39s** MAE (n=15). Do not cite 1838.

Detail: first loss breach at ~t=3704 became the ETA target for every earlier window, so true labels ≈ 1800s while the loss head predicted ~2s. Fix is in `eval_chaos` (phase-scoped Q1), not a retrain. In-distribution val MAE **7.1s** (n=185) remains the train claim; scoped chaos TTI is honest but thin-n / not demo-primary.

### Do not cite (scrubbed from claim surfaces)

| Number | Why |
| --- | --- |
| 0.533 | Selection-contaminated full chaos |
| 0.101 | Contig vs raw class-id bug |
| 0.544 | Row-stamp BGP under-label before full-series fix |
| ~1838s | Q1 loss MAE on full-series chaos windows |

Canonical machine dump: [`data/deca/predictive/SCOREBOARD.json`](../data/deca/predictive/SCOREBOARD.json).

---

## 2026-08-05 — Board locked: frozen `d2` won six honest attempts

**Cite (unchanged):** holdout **0.884** · chaos_final **0.815** · GNS3 **0.655** · Q2 root **0.992** · Q1 loss val MAE **7.1s**.

**Judge one-liner:** We ship frozen `d2_e100_l6_mcw3` because it is the best model that exists — confirmed by six honest attempts that failed to beat it, under a pre-committed promote bar, plus a diagnosed reason current data cannot reproduce its holdout (BGP-roll rebuild 3838→4632 rows). Not “we ran out of time.”

**Rejected / NO_PROMOTE (promote-bar discipline held):** threshold inflation · GNS3 soft-storm fabrication · BGP rolling-label retrain (regressed) · efficiency-pack merge retrain · idle-delta on mismatched recipe · **current-abs form-sweep ceiling** (best new-train ≈ **0.72 / 0.62 / 0.55** — none clear bar). Soft twin kept; no EXTRA fabrication.

**Dataset-drift finding:** cite 0.884 is a frozen-artifact score on the pre-rebuild matrix; same knobs on today’s balanced CSV land ~0.70. Using 0.884 as the *train* bar for new candidates was apples-to-oranges — corrected by the ceiling run. Rescored today, the frozen joblib still reads chaos_final **0.815** / GNS3 **0.655**.

**Walkback (same day):** twin util/CPU/CE “fixes” that hardcoded `severity_label` bands at inference, and a BGP specialist whose `P(3A)` gate was swept on **chaos_final**, produced inflated numbers (e.g. GNS3 ~0.907). **Discarded from demo path** — same honesty class as storm fabrication / threshold inflation. See [`WALKBACK_CIRCULAR_REMAP.md`](../data/deca/predictive/protocol_models/xgb_q2_sev_unified/fix_receipts/WALKBACK_CIRCULAR_REMAP.md).

**Open bottlenecks (precise — volume is *not* the lever for most):**

| Open item | Real bottleneck | Wrong lever (already tested) |
| --- | --- | --- |
| GNS3 util root ~**0.13** / transfer util ~**0.46** | **Shared-host virtualization** (below) + capture physics — HTB 40 on both does not make eth0 TX isomorphic | More util windows / %-of-ceiling (**NO_PROMOTE**) |
| GNS3 CPU ~**0.57** / CE-SLA ~**0.30** | **Shared-host confound** — Pi L6 is fine (below); GNS3 L6 under-calls healthy | More modeling / idle-norm alone · Pi L6 densify |
| Multi-label presence / quiet-leg drowning | **Architecture** — second model/output head (`MULTI_FAULT.md`) · **skeleton validated** on static FV (presence quiet-leg ~0.98 vs Q2 ~0.04) — not live-wired / not chaos_final | More COMPOUND into single-label Q2 (F1↑, drowning slices unchanged) |
| ~0.70–0.72 current-data holdout ceiling | **Structural / pre-existing** — three-arm ablation cleared this week’s levers: FULL_x8 **0.719** · TRIM_x4 **0.705** (−1.3pp) · CONTRACT_x4_plus **0.701** (≈ trim). Not the ×4 cut, not contract fixes. Leading suspect still **BGP-roll rebuild / label matrix** on the current CSV ([`X4_TRIM_ABLATION.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/x4_trim_ablation/X4_TRIM_ABLATION.md)). **Densify read:** do **not** treat a stuck ~0.70–0.72 *aggregate holdout* as “util/PE-class fix failed” — score **util phase + chaos_final** specifically; holdout ceiling is a separate open mystery | Treat 0.884 as a reachable *train* bar on today’s CSV |
| O2.3 rekey demo | **Design ready, not launched** — [`REKEY_STORM_INJECTOR_DESIGN.md`](./REKEY_STORM_INJECTOR_DESIGN.md); gauges/rules live; storm inject **after** densify+chaos only | Pretend ambient rekey = injectable demo · launch inject during densify |
| BGP multi-scale features | **Engineering** — 5s/30s/60s · time-since · burst · **skel `MULTISCALE_HELPS`** (+12pp exact; 3A F1 0.43→0.75 on L3 group-holdout) — not in FEATURE_COLS / not promote ([`BGP_MULTISCALE_EVAL.json`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_multiscale/BGP_MULTISCALE_EVAL.json)) | Another single 10s-rate retrain on same flaps |

**Closed (do not re-open as “open MAE”):** jitter densify — group-holdout MAE **27.2** (n=1026); do **not** cite 131.7.

### GNS3 CPU / CE-SLA / util — root cause (shared hardware, not vague shift)

**Judge one-liner:** Pi metrics come from dedicated per-node hardware; GNS3 PE/CE nodes are virtual instances sharing one physical CPU/NIC — same Prom names, different physics. That is why CPU (~0.57) and CE-SLA (~0.30) transfer stay weak, and why more modeling is the wrong lever.

| Fault | Why the twin signal differs |
| --- | --- |
| **L2 CPU** | Pi `cpu_usage_user` = dedicated core under real stress. GNS3 = cgroup/share competing with PE1–3, COREs, 8+ CEs on one host. Severity bands 2A/2B (40/70%) were set on Pi dedicated behavior — same number ≠ same meaning. |
| **L6 CE-SLA** | Story needs genuinely separate CEs contending on the wire. On GNS3, rogue vs victim often meets at a **virtual switch**, so the “stolen bandwidth” signature is weaker/different than Pi physical contention. **Measured 2026-08-06:** Pi L6 window exact **0.997** (frozen `d2`); GNS3 L6 exact **0.303** with **~78% predicted healthy** (not util-5* confound). Receipt: [`CE_SLA_PI_ANALYSIS.json`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/ce_sla_pi_check/CE_SLA_PI_ANALYSIS.json). |
| **L5 util** | Identical HTB 40 Mbit config does not imply identical shaping on virtual NICs vs real eth0 — contributes to util transfer staying ~0.46 even after fabric routing. |

**Practical:** these gaps are **less likely to close with more data/features alone**. Cheap first lever (safe): **GNS3-native severity bands at LABEL time** from that fabric’s idle/stress distribution (`severity_bands.py`) — same “don’t mash fabrics” discipline, extended to band cutpoints. **Not** inference remaps (quarantined — [`WALKBACK_CIRCULAR_REMAP.md`](../data/deca/predictive/protocol_models/xgb_q2_sev_unified/fix_receipts/WALKBACK_CIRCULAR_REMAP.md)). Optional later: Docker/cgroup isolation (attacks the cause; riskier near demo).

**Option 1 result (2026-08-05) — thresholds were not the main issue:**

| Check | Result |
| --- | --- |
| Chaos_dev select (BGP discipline) | All cands tied **0.695** (= baseline); pick `cand_d3_e120_l4` |
| Chaos_final oneshot | **0.445 → 0.613** (+17pp) — real sealed lift; keep bands for twin GT consistency |
| Pure L2 LOO (L2_* iters) | Pi bands **0.995** → GNS3 bands **0.994** — flat |
| Pure L6 LOO (L6_* iters) | **0.659 → 0.580** — slightly worse |
| In-sample window exact 0.83 / 0.99 | **Do not cite** — trained on same `q2_windows` |

**Read:** `THRESHOLDS_NOT_MAIN` for CPU/CE. Removing the wrong-thresholds explanation did not move those classes; shared-host contention remains the blocker. Receipt: [`OPTION1_VERDICT.json`](../data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/train_logs/option1_sev_bands/OPTION1_VERDICT.json).

**Closed same pass:** jitter densify **PROMOTE** — honest group-holdout MAE **27.2** (n=1026) vs cite 131.7; cleaning alone stayed ~150 ([`PROMOTE.md`](../data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/PROMOTE.md)). **O3/O4 GNS3:** RAG corpus + `topology.blast_radius(..., fabric=)` already include GNS3 ([`O3_O4_GNS3_WIRING.json`](../data/deca/predictive/protocol_models/O3_O4_GNS3_WIRING.json)).

**Sample row-audit (packaging):** asymmetry / 1s gaps / util>HTB — all three real; none block the locked board. Receipt [`METRIC_SAMPLE_ROW_AUDIT.md`](../data/deca/predictive/protocol_models/METRIC_SAMPLE_ROW_AUDIT.md).

**Lane A started (CAPTURE_CONTRACT):** locked choices + code — asymmetry derive/drop stale · util=eth0 TX @1Hz · gaps align+ts-ETA+capture log · **L5 default = tc-ramp** (continuous offer + class ceil steps + plateau; not pulsed iperf) · L6 continuous CE plateau · L2/L3/COMPOUND primary-signal smoke PASS (`contract_smoke_full_20260805T025000Z`). See [`CAPTURE_CONTRACT.md`](./CAPTURE_CONTRACT.md) · validation [`CAPTURE_CONTRACT_SMOKE.md`](./CAPTURE_CONTRACT_SMOKE.md).

**Full campaign trim (locked):** L2/L3 short injects · L1/L4 ×4 (not ×8) · keep L5×8+plateau≥40 · L6×4 · COMPOUND×8 · chaos **7200s** · Pi∥GNS3. Plan est **~9.25 h**/fabric (was 12.54). Does **not** change locked cite numbers.

If collecting data further: only if jitter group-holdout stalls. Eff-pack / full-campaign volume already raised holdout while hurting chaos_final + GNS3 transfer — do not repeat that pattern for util / presence.

**Done (same day, legitimate):** per-fabric GNS3 `d3` (**0.722**) · BGP specialist @**0.85** fresh one-shot (**0.886**) · util-%-of-ceiling form-sweep **NO_PROMOTE** (no lift vs current-abs ceiling).

Receipts: [`CURRENT_ABS_CEILING.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_form_sweep_current_abs/CURRENT_ABS_CEILING.md) · [`UTIL_PCT_SWEEP.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_form_sweep_util_pct/UTIL_PCT_SWEEP.md) · [`ONESHOT_VERDICT.json`](../data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/ONESHOT_VERDICT.json) · [`ACTIVE_Q2_ROUTING.json`](../data/deca/predictive/protocol_models/ACTIVE_Q2_ROUTING.json) · [`PREDICTIVE_MODEL_SCORES.md`](./PREDICTIVE_MODEL_SCORES.md).

---

## 2026-08-06 — Util CAPTURE_CONTRACT: diagnosis chain (model untouched)

**Cite board unchanged:** holdout **0.884** · chaos_final **0.815** · GNS3 **0.655** · Q2 root **0.992** · Q1 loss **7.1s** · jitter **27.2**. Frozen `d2_e100_l6_mcw3`. **No retrain / NO_PROMOTE** until capture proves separable util across L5 ends + off-nominal chaos.

### Why earlier util “fixes” looked correct but did not move scores

Every mid-week util attempt (schedule-gating, `htb_payload_ceil_mbps` feature, offer≥2×) was partly right as *logic*, but the physical quantity being labeled often **could not** track the configured payload ceil. Correct diagnosis + small/no lift = expected when the shaper class being measured never saw the traffic.

### Sequence (keep this order in slides)

| Finding | Evidence | Fix |
| --- | --- | --- |
| Offer fixed while ends rose → util = offered load | Smoke / contract logs | Auto offer ≥ **2× end_mbit** |
| Ends above parent 40 impossible on eth0 | HTB parent | Cap L5 ends ≤ soft payload ceil (~34) |
| **PE `1:15` never saw CE util traffic** | Post-IPsec/MPLS on eth0 → default **BE `1:20`**; `tc -s` showed ~0 bytes on 1:15 | Shape on **ce-a `veth-cea-pe`** *before* encrypt; mirror PE 1:15 **audit-only** |
| Softness at high ceils was **progressive**, not constant ratio | Pre-BE-lift sweep: util flat ~**24** for ceil≥24 | BE `1:20` nominal ceil **24** was the hard cap |
| After BE lift (ceil→40 during inject, restore on EXIT) | Full L5 ends `[12…34]`: util/ceil ≈ **1.07** constant (encap overhead); mono separable | Densify L5 under new injector; chaos util phase **end=24** (off-nominal vs idle 34) |

**Smoke (pre-BE-lift, CE-shape only):** ceil=16 → ~17; ceil=28 → ~24 — separated but soft at 28 (= BE cap).  
**Ratio sweep (post-BE-lift):** ratios ~1.07 across 12…34 — prerequisite for `util/ceil` as a feature if needed later.

**In flight (do not parallel-interfere):** Pi `util_clean_pi_20260805T233437Z` densify (resume JOB 3/12) → auto **7200 s** chaos holdout `end_mbit=24`. Retrain only after util phase separates on that capture.

**Still open (not answered by this chain):** ×4 trim vs contract ablation for ~0.70 holdout ceiling; GNS3 util shared-host physics; multi-label presence layer.

Mermaid: [`DECA_COMPLETE_MERMAID_MAPS.md`](./DECA_COMPLETE_MERMAID_MAPS.md) §4.1 · injector [`scripts/inject_util_congestion.sh`](../scripts/inject_util_congestion.sh) · contract [`CAPTURE_CONTRACT.md`](./CAPTURE_CONTRACT.md).

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

**Running now (do not parallel-interfere):** Pi util_clean densify → 7200 s chaos `end=24` — gate for any util retrain.

**Safe in parallel (analysis / code only):**

1. **FINDINGS / cite scrub** — done 2026-08-06.
2. **CE-SLA (L6) check on Pi** — done (`PI_L6_OK_GNS3_TWIN_GAP`).
3. **BGP multi-scale features** — done skel (`MULTISCALE_HELPS`); wire into FEATURE_COLS only after explicit go + chaos discipline.
4. **Multi-label presence layer** — skeleton validated; Decide wiring later.
5. **Rekey-storm injector** — **design done** ([`REKEY_STORM_INJECTOR_DESIGN.md`](./REKEY_STORM_INJECTOR_DESIGN.md)); implement/smoke only **after** densify+chaos; **do not launch** now.
6. **×4 trim ablation** — done (`TRIM_NOT_THE_CEILING`); ceiling = structural, not this week’s trim/contract.

**When densify+chaos lands — score correctly:** util-phase separation + chaos_final (and family slices) first. Aggregate holdout may still sit ~0.70–0.72 because that ceiling predates util/PE-class work — do not misread it as inject failure.

**2026-08-06 util_clean retrain (oneshot):** physics→model payoff **confirmed** — winner util phase **0.43→0.94**, **5B recall 0→0.85** on sealed off-nom chaos. Overall chaos_final **0.56** (BGP exact collapsed) → **NO_PROMOTE**; cite board untouched. Receipt: [`ONESHOT_VERDICT.md`](../data/deca/predictive/protocol_models/_candidates/util_clean_retrain_20260806T093000Z/ONESHOT_VERDICT.md).

**2026-08-06 util_clean + BGP multi-scale:** wired MS into train/eval; chaos_dev→oneshot **`d2_e80_l8_mcw4_ms`**. Util held (**0.944** / 5B~0.89); BGP exact **0.05→0.33** (partial); overall **0.56→0.66**. Still **NO_PROMOTE** vs frozen BGP 0.54 / bar 0.70. Receipt: [`util_clean_bgp_ms/.../ONESHOT_VERDICT.md`](../data/deca/predictive/protocol_models/_candidates/util_clean_bgp_ms_20260806T094500Z/ONESHOT_VERDICT.md).

**Blocked on campaign result:** latency Q1 densify · any util/BGP Q2 retrain/promote · rekey inject smoke.

**Keep claims downgraded until closed:** O2.2 flap precursor · O2.3 injectable rekey · O4.1 full graph · O4.3 multi-candidate playbooks · P6.4 not inside Q1/Q2 L1–L5.

**Optional / not claimed:** air-gap WAN-block harness · Dual-P · Prophet.

---

## Explicit non-goals of this document

- Does not change code, promote models, or claim Phase 5/6 complete.
- Does not treat exam macro-F1 alone as PS success (success = lead time + operator-ready NL without cloud).
- Does not hide the compound quieter-leg limitation or the backend↔live split.
