# DECA fault & model guide (human language)

**Status:** Cite / ship board — frozen Q2 `d2` + BGP specialist + Q1 LSTM ETA heads.  
**Do not swap in** unpromoted util-clean / τ / synth experiments as “the” scores.

**Artifacts:** [`DEMO_SHIP_CARD.md`](./DEMO_SHIP_CARD.md) · [`PREDICTIVE_MODEL_SCORES.md`](./PREDICTIVE_MODEL_SCORES.md) · [`../data/deca/predictive/SCOREBOARD.json`](../data/deca/predictive/SCOREBOARD.json)

---

## 1. What the system is trying to do (two jobs)

| Job | Who does it | Question it answers |
| --- | --- | --- |
| **What is wrong?** | **Q2** (XGBoost severity) + small **BGP specialist** | Rain? CPU? BGP? Loss? Congestion? CE conflict? How urgent? |
| **When will it hurt?** | **Q1** (LSTM time-to-impact) | Roughly how many seconds until we cross an SLA threshold? |

Live path: telemetry → features → Q1 ETA + Q2 class → Decide rail → (optional) Approve.

| Piece | Path |
| --- | --- |
| Frozen Q2 | `data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib` (`d2_e100_l6_mcw3`) |
| BGP specialist | `…/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib` (`min_3a_proba=0.85`) |
| Q1 latency | `…/lstm_q1_unified/q1_tti_lstm.keras` |
| Q1 loss | `…/lstm_q1_loss/q1_loss_tti_lstm.keras` |
| Q1 util | `…/lstm_q1_util/q1_util_tti_lstm.keras` |
| Q1 jitter (honest densify) | `…/lstm_q1_jitter_stride1/` (cite MAE **27.2**) |

---

## 2. Headline scores (say these)

### Q2 — “what fault / how bad?”

| Metric | Score | Meaning in plain English |
| --- | ---: | --- |
| Pi holdout | **0.884** | On held-out Pi windows, ~88% exact severity match |
| Chaos_final (one-shot) | **0.815** | On a long mixed chaos run never used for training, ~82% |
| GNS3 transfer | **0.655** | Same Pi model on the GNS3 twin — weaker, disclosed |
| Root-cause only | **0.992** | “Which *family*” (rain/CPU/BGP/…) almost always right |
| BGP phase (fresh + specialist) | **0.886** | On BGP-heavy sealed chaos, mild/severe grading with helper |
| Overall with locked BGP stack | **0.823** | Full chaos with specialist locked in |

### Q2 — scores by root (1A–6B families)

**Exact** = correct severity string (e.g. `4B` not just “loss”). **Family** = correct root (e.g. any of 3A/3B when truth is BGP).

| Root | Severities | Fault | Cite score (exact) | Family / notes |
| ---: | --- | --- | ---: | --- |
| 0 | `0` | Normal | (in overall) | Baseline; false alarms are the fail mode |
| 1 | `1A` `1B` `1C` | Rain / physical | **Strong on Pi** (drives overall 0.884 / chaos_dev 0.997) | Latency signature is clear; no separate line in chaos_final phase table (rain sits in chaos_dev half of the schedule) |
| 2 | `2A` `2B` | CPU exhaustion | **Strong on Pi** (same) | GNS3 weaker (shared-host CPU ≠ Pi) — part of transfer **0.655** |
| 3 | `3A` `3B` | BGP flap | **0.886** phase exact | Family **1.0** on same fresh oneshot; bare was **0.864**. Older FV chaos_final without locked specialist: exact ~**0.62**, family ~**0.86** (disclosed) |
| 4 | `4A` `4B` | Loss progression | **~0.97** (FV chaos_final) · **0.993** (fresh oneshot) | Among the strongest roots |
| 5 | `5A` `5B` | Util / congestion | **~0.97** (FV chaos_final) · **0.983** (fresh oneshot) | Strong on locked story; newer off-nominal util chaos can under-call — don’t swap cite mid-demo |
| 6 | `6A` `6B` | CE-SLA conflict | **~0.997** on Pi | GNS3 twin ~**0.30** (often predicts healthy) — disclose |

Sources: [`PREDICTIVE_MODEL_SCORES.md`](./PREDICTIVE_MODEL_SCORES.md) · [`RESULTS_HONEST_CHAOS.md`](../data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/RESULTS_HONEST_CHAOS.md) · BGP specialist [`ONESHOT_VERDICT.json`](../data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/ONESHOT_VERDICT.json).

**Not a Q2 class:** memory exhaustion, rekey-storm, netflow-only, asymmetry-only — those are metrics/features, not roots in `0`/`1A`…`6B`.

### Q1 — “when does it breach?”

MAE = average error in **seconds**. Lower is better. This is *not* accuracy %.

| Head | What it watches | Cite / honest MAE | How to read it |
| --- | --- | --- | --- |
| **Latency** | GRE delay → TT&C **25 ms** | Val MAE **~61 s** (n≈1022) | ETA often within about a minute on similar ramps |
| **Loss** | GRE loss → Payload **2%** | Val **7.1 s** (n=185); chaos scoped **~39 s** (n=15) | Best ETA head in-lab; chaos noisier, small n |
| **Util** | Congestion vs ceil | Val **~31 s** (n=432) | Useful lead time; not as tight as loss |
| **Jitter** | GRE jitter → **5 ms** | Honest group-holdout **~27 s** (n=1026) | Cite this — not the old bad ~131 s random-split |

---

## 3. The faults — what they are, how they feel, how we do

### Healthy / normal (`0`)

| | |
| --- | --- |
| **What** | No injected fault; network at baseline |
| **Feel** | Low latency (sub‑ms to a few ms on Pi GRE), tiny util, CPU calm, BGP counter flat |
| **Model** | Baseline class; when quiet it should stay here (false alarms are the failure mode) |

---

### L1 — Rain fade / physical path degrade (`1A` / `1B` / `1C`)

| | |
| --- | --- |
| **What it is** | Preferred underlay (GRE toward CORE) gets delayed — lab analogue of weather / RF / bad path quality |
| **How it occurs (lab)** | `tc netem delay` ramp on `gre-te-core` |
| **How the network feels** | Packets still flow, but the **TT&C path gets “farther”** — RTT/latency climbs, jitter often rises, backup eth0 stays relatively clean so asymmetry grows. Voice/control feels sluggish before a hard outage |
| **Severity** | Early (1A) → critical (1B) → breach ≥25 ms (1C) |
| **Q2 score** | Strong on Pi (supports overall holdout **0.884** / chaos_dev **0.997**); rain is in the chaos_dev half of the locked schedule, not a separate chaos_final phase line |
| **Q1 latency ETA** | Time to 25 ms SLA; ~60 s average error means “minutes-scale warning,” not millisecond precision — still useful for Decide preemption |

---

### L2 — CPU / crypto exhaustion (`2A` / `2B`)

| | |
| --- | --- |
| **What it is** | Station CPU burned (crypto/forwarding pressure analogue) |
| **How it occurs** | `stress-ng` / CPU burn on station1 |
| **How the network feels** | Control plane and encrypt/decrypt get **sluggish**; latency/jitter can creep as a side effect, but the fingerprint is **high user CPU**, not rain alone. Sessions feel “sticky” / slow to converge |
| **Severity** | Moderate 40–70% user (2A) vs severe ≥70% (2B) |
| **Q2 score** | Solid on Pi (same overall board); GNS3 weaker — shared-host cgroups (part of transfer **0.655**) |
| **Q1** | No dedicated “CPU ETA” head; urgency is mostly Q2 severity + latency/jitter side effects |

---

### L3 — BGP route flap (`3A` mild / `3B` severe)

| | |
| --- | --- |
| **What it is** | Routing adjacency / VPN routes bouncing — soft-clears or link events |
| **How it occurs** | Cyclic `clear bgp … soft` (optional GRE bounce) |
| **How the network feels** | **Reachability blinks** — paths withdraw/reappear, traffic may blackhole briefly or take backup, tunnels look “alive” while routes thrash. Operators see flaps and churn, not necessarily high latency first |
| **Severity** | Flap-rate bands — mild **3A** vs storm **3B** |
| **Q2 score** | Phase exact **0.886** with locked specialist @0.85 (family **1.0**; bare **0.864**). Older FV chaos_final without that lock: exact ~**0.62**, family ~**0.86** |
| **Honest line if asked** | “We catch BGP well; grading mild vs severe needed a specialist — we disclose that and ship it.” |
| **Q1** | No BGP-seconds ETA; Decide uses class + red-gate on 3B |

---

### L4 — Loss progression (`4A` / `4B`)

| | |
| --- | --- |
| **What it is** | Growing packet loss on the preferred path |
| **How it occurs** | `tc netem loss` ramp on GRE |
| **How the network feels** | Apps **retransmit / freeze / glitch** — TCP collapses, UDP/voice breaks up. Before full cut, Payload SLA (**2%**) is the tripwire |
| **Severity** | 0.5–2% (4A) vs ≥2% (4B) |
| **Q2 score** | **~0.97** exact on FV chaos_final · **0.993** on fresh oneshot |
| **Q1 loss ETA** | Best ETA story — **~7 s** val MAE; chaos scoped ~39 s. Clearest “we can warn before breach” head |

---

### L5 — Util / congestion (`5A` / `5B`)

| | |
| --- | --- |
| **What it is** | Payload class filling toward its HTB ceiling — congestion, not rain |
| **How it occurs** | Continuous iperf + CE shaping + BE-lift physics so util tracks ceil (~1.07×) |
| **How the network feels** | Path **saturates** — queues build, bulk slows, latency/jitter can rise *because* of fullness; loss may appear late. Feels like “pipe is full,” not “path is far” |
| **Severity** | Elevated vs near-ceil (schedule-based 5A/5B) |
| **Q2 score** | **~0.97** exact on FV chaos_final · **0.983** on fresh oneshot. Newer off-nominal util chaos can under-call — don’t swap cite mid-demo |
| **Q1 util ETA** | ~31 s val MAE — useful lead into ceil breach, coarser than loss |

---

### L6 — CE SLA conflict (`6A` / `6B`)

| | |
| --- | --- |
| **What it is** | Bronze site (Mauritius rogue) competes with Gold TT&C on shared PE resources |
| **How it occurs** | Rogue bulk from `ce-mauritius` + gold TT&C probe |
| **How the network feels** | **Policy unfairness** — scavenger/bronze load squeezes premium traffic; util climbs; gold mission feels degraded though “the link isn’t down” |
| **Q2 score** | Pi **~0.997** exact; GNS3 twin ~**0.30** (often predicts healthy) — disclose for dual-fabric demos |
| **Q1** | Util-like pressure; no separate L6 ETA head |

---

## 4. How the pieces fit in the NOC story

```text
Prom metrics (1 Hz)
    → Q1 LSTMs: "ETA to SLA breach" (latency / loss / util / jitter)
    → Q2 XGBoost: "which severity right now"
    → BGP specialist: refine 3A vs 3B when Q2 is in BGP land
    → Decide: show class + confidence + ETA + runbook
    → Approve (HITL): steer path / policy
```

- **Q2 ~0.88 holdout / ~0.82 chaos** → reliable enough to demo “we know what’s wrong” on Pi.
- **Q1** → the predictive pitch: not only detect, but **warn**. Loss is sharpest; latency/util/jitter are usable but looser.
- **GNS3 0.655** → same brain, different body — show Pi-primary, disclose twin gap.

---

## 5. One-page cheat sheet — how well per fault

| Fault | Severities | Q2 exact (cite) | Family / note | ETA (Q1) |
| --- | --- | ---: | --- | --- |
| Rain / physical | 1A–1C | Strong (in **0.884** / chaos_dev **0.997**) | Clear latency signature | Latency ~61 s MAE |
| CPU | 2A–2B | Strong on Pi | GNS3 weaker | Indirect only |
| BGP | 3A–3B | **0.886** (+spec) | Family **1.0**; was ~0.62 exact pre-lock | No dedicated ETA |
| Loss | 4A–4B | **~0.97** / **0.993** | Very strong | Loss **~7 s** val MAE |
| Util | 5A–5B | **~0.97** / **0.983** | Strong on locked story | Util ~31 s MAE |
| CE-SLA | 6A–6B | **~0.997** Pi | GNS3 ~**0.30** | Via util-like signals |

---

## 6. Weak spots — one sentence each (say if asked)

- **BGP mild vs severe:** Family detection is strong; exact mild-flap grading is softer — we disclose it and ship a locked 3A/3B specialist rather than pretend 0.95.
- **GNS3 transfer:** Pi-primary demo; twin transfer is **0.655** on the same `d2` (shared-host CPU / CE-SLA texture gaps) — documented, not hidden.
- **Util on older dirty L5:** Pre-contract util captures were physically wrong; densify fixed physics. Cite board stays on frozen `d2`.

---

## 7. Do not cite

| Number / story | Why |
| --- | --- |
| 0.101 chaos | Contig vs raw ID eval bug |
| ~1838 s loss MAE | Full-series scope bug — use scoped ~39 s |
| 0.533 / 0.544 contaminated chaos | Selection / label contamination |
| Unpromoted util-clean / τ / synth stacks as “the” score | Not on cite board |
| Circular fabric remaps | Walked back |

---

## 8. Live infer (frozen stack)

```bash
cd /home/brain/deca-isro
export PYTHONPATH=/home/brain/deca-isro
.venv-predictive/bin/python -m predictive.infer_q1_q2_live \
  --q1-model data/deca/predictive/protocol_models/lstm_q1_unified/q1_tti_lstm.keras \
  --q1-scaler data/deca/predictive/protocol_models/lstm_q1_unified/q1_scaler.npz \
  --q2-model data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib \
  --bgp-specialist data/deca/predictive/protocol_models/bgp_3a3b_specialist/honest_threshold/bgp_3a3b_locked.joblib \
  --dry-run --seconds 30
```

Jury dual-fabric script: [`JURY_DUAL_FABRIC_DEMO.md`](./JURY_DUAL_FABRIC_DEMO.md)
