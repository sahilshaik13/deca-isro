# Predictive model scores — index

**Canonical stamp (train):** `full_variants_pi_20260803T175816Z`  
**GNS3 twin (transfer only, no mash):** `full_variants_gns3_20260803T175816Z`  
**Legacy 3-day:** archived — **not used**

**Honesty write-up:** [`PROBLEM_STATEMENT_13_FINDINGS.md`](./PROBLEM_STATEMENT_13_FINDINGS.md) § *2026-08-04 — Predictive scoreboard honesty* · § *2026-08-05 — Board locked* · § *2026-08-06 — Util CAPTURE_CONTRACT*  
**Machine dump:** [`SCOREBOARD.json`](../data/deca/predictive/SCOREBOARD.json)  
**Board status:** **LOCKED** — frozen `d2_e100_l6_mcw3` (six honest NO_PROMOTEs + current-data ceiling ~0.72/0.62/0.55). Util densify/chaos in flight — **no cite change until promote bar cleared.**

---

## Cite vs do-not-cite

| Number | Cite? | Why |
| --- | --- | --- |
| Holdout **0.884** | **Yes** | Group holdout, L4 + COMPOUND forced |
| Chaos_final **0.815** | **Yes** | One-shot clean rescore of **same** model after eval fixes |
| GNS3 transfer **0.655** (Pi `d2` on twin) | **Yes** | Disclosed; Pi-primary demo path |
| GNS3 twin route **0.722** (`d3`) | **Yes** | Per-fabric routing only — not a Pi promote |
| GNS3 L3 soft storm→often **3A** | **Disclose** | Quieter twin is information — keep soft `l3_storm_*`; hard `l3_storm_hard_*` additive only ([`L3_SELECTION_HONESTY.md`](../data/deca/predictive/protocol_gns3/eff_pack_gns3_20260804T094436Z/L3_SELECTION_HONESTY.md)) |
| Q2 root **0.992** | **Yes** | Group holdout |
| Q1 loss val MAE **7.1s** (n=185) | **Yes** | In-distribution |
| Q1 loss chaos MAE **~39s** (scoped, n=15) | Optional | `gt_root==4` only — small n |
| Chaos_dev 0.997 | Selection only | Not a claim |
| BGP phase exact **0.886** (fresh @0.85) | **Yes** | Locked on L3-dev; one-shot sealed chaos |
| 0.544 / 0.101 / 0.533 / ~1838s | **No** | Eval bugs or selection contamination |

**One line:** chaos_final scored twice — first run surfaced eval/label bugs, same model rescored once clean; **selection never touched chaos_final.**

---

## Q2 severity — promoted (`d2_e100_l6_mcw3`)

| Metric | Score |
| --- | ---: |
| Pi group-holdout | **0.884** |
| Chaos_dev (selection) | 0.997 |
| **Chaos_final (clean one-shot)** | **0.815** |
| GNS3 transfer (same `d2` on twin) | **0.655** |

### Per-fabric GNS3 route (`d3_e120_l4_mcw2`)

| Metric | Score |
| --- | ---: |
| Pi holdout (sibling of `d2`, not promoted) | 0.795 |
| **GNS3 transfer (cite-style)** | **0.722** |
| Historical form-sweep receipt | 0.721 |

Routing: Pi → frozen `d2`; GNS3 → `xgb_q2_sev_gns3_d3` ([`ACTIVE_Q2_ROUTING.json`](../data/deca/predictive/protocol_models/ACTIVE_Q2_ROUTING.json)). Reproduced from pre-BGP-roll 3838 CSV + exact CFGS after original sweep joblib went missing on disk. **No remaps.**

| chaos_final phase | Exact acc | Note |
| --- | ---: | --- |
| Loss | ~0.97 | |
| Util | ~0.97 | |
| BGP | **0.886** (fresh one-shot @0.85) | Honest lock; bare was 0.864 on same sealed set |

Eval fixes (not retunes): contig→severity map · full-series severity stamp · BGP 10s rolling flap rate.

---

## Q1 TTI

| Head | Val MAE ↓ | n | Chaos (scoped) |
| --- | ---: | ---: | --- |
| Latency | **60.8** | 1022 | rain-scoped (see eval) |
| Loss | **7.1** | **185** | **~39s** MAE on `gt_root==4` (n=15); do not cite full-series ~1838s |
| Util | **31.1** | 432 | Soft ceiling |
| Jitter | **27.2** (group holdout) | **1026** | Densify stride-1; was 131.7@303 — do **not** cite random-split ~11 |

---

## Locked decisions

- **Board LOCKED (2026-08-05):** ship frozen `d2_e100_l6_mcw3` — best existing model, not a time-box default ([FINDINGS lock](./PROBLEM_STATEMENT_13_FINDINGS.md#2026-08-05--board-locked-frozen-d2-won-six-honest-attempts))
- **GNS3:** Pi-primary demo still discloses **0.655** on `d2`; twin infer routes to **`d3` at 0.722** ([routing](../data/deca/predictive/protocol_models/ACTIVE_Q2_ROUTING.json)) · no mash  
- **GNS3 L3 storms:** soft twin (storm→often 3A) **always cited**; hard period=3 attempts are additive — never the sole story ([selection honesty](../data/deca/predictive/protocol_gns3/eff_pack_gns3_20260804T094436Z/L3_SELECTION_HONESTY.md))
- **BGP specialist @0.85:** promoted after L3-holdout lock → fresh sealed one-shot ([`ONESHOT_VERDICT.json`](../data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/ONESHOT_VERDICT.json)); old 0.75/FV-final path stays uncitable
- **Util %-of-ceiling:** tried on current 4632 CSV — **NO_PROMOTE** (≈ same as abs ceiling ~0.72/0.62/0.55; GNS3 util still ~0.13). Both fabrics applied HTB=40 so %≈scaled Mbps ([`UTIL_PCT_SWEEP.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_form_sweep_util_pct/UTIL_PCT_SWEEP.md))
- **No further Q2 promote attempts** on current 4632-row CSV without a new labeled campaign; cite 0.884 is frozen-artifact, not a reachable train bar ([ceiling receipt](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_form_sweep_current_abs/CURRENT_ABS_CEILING.md))
- **Jitter densify PROMOTE:** group-holdout MAE **27.2** (n=1026) replaces cite 131.7 — [`lstm_q1_jitter_stride1/PROMOTE.md`](../data/deca/predictive/protocol_models/lstm_q1_jitter_stride1/PROMOTE.md)
- **O3/O4 GNS3:** RAG + `topology.py` GNS3 adjacency **already wired** ([`O3_O4_GNS3_WIRING.json`](../data/deca/predictive/protocol_models/O3_O4_GNS3_WIRING.json)); not a data problem
- **Still open (not volume):**
  - **GNS3 util ~0.13** — shared-host virtualization + capture physics (HTB=40 both fabrics ≠ isomorphic eth0)
  - **Multi-label presence** — skeleton validated (quiet-leg ~0.98 vs Q2 ~0.04; macro prec~0.86; L6 triage-only) — not Decide-wired
  - **~0.70 holdout ceiling on current CSV** — structural (FULL_x8 still 0.719; trim/contract cleared); suspect BGP-roll/label matrix — **not** a densify util-phase score. When campaign finishes, judge util phase + chaos_final, not aggregate holdout alone ([`X4_TRIM_ABLATION.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/x4_trim_ablation/X4_TRIM_ABLATION.md))
  - **Util capture fix** — CE-shape + BE lift proven on ratio sweep; **await** util_clean densify + 7200s chaos `end=24` before any util retrain
  - **BGP multi-scale** — skel `MULTISCALE_HELPS` (+12pp exact / 3A F1↑ on L3 holdout) — not in `FEATURE_COLS` / not promote yet ([`BGP_MULTISCALE_EVAL.json`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_multiscale/BGP_MULTISCALE_EVAL.json))
  - **CE-SLA** — Pi OK (0.997); GNS3 ~0.30 = twin under-call healthy — no Pi densify
