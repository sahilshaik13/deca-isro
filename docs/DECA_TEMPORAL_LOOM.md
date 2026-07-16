# DECA Temporal Loom

How DECA balances **false starts** vs **missed faults** without using fault duration as a classifier feature.

The “loom” is the pattern-over-time layer that sits **after** the frame classifier: multi-scale features weave short onset threads with long build-up threads, then sticky hysteresis (persistence) decides when a fault is **real enough** to declare — and when an almost-fault that dies should stay silent.

| Layer | Script / artifact |
| --- | --- |
| Multi-scale features | `scripts/rebuild_unified.py` → `engineer_features` |
| Frame promote (raw) | `scripts/deca_school_exam_train.py` (School Exam gate) |
| Sticky loom | `scripts/deca_inference.py` (`apply_loom` / `predict_fault_stream`) |
| Measure + bake boost | `scripts/deca_score_temporal.py` → patches `decision_thresholds.json` |
| Campaign near-miss | `scripts/deca_fault_campaign.py` (`precursor_aborted`) |
| Circumstance campaign | `scripts/deca_circumstance_campaign.py` (5×4 events, 3-phase capture) |
| Existence labels | `scripts/rebuild_unified.py` → `label_circumstance_existence` |
| Existence head | `scripts/deca_train_circumstance.py` → `models/circumstance/` |

**Live path:** promoted bundle includes `loom: {enabled, enter_k, exit_k, enter_k_by_class, exit_k_by_class, advisory_enabled, advisory_enter_k, advisory_exit_k}`; chronological streams use `predict_fault_stream` / `apply_loom` (confirmed only) or `predict_fault_stream_two_tier` / `apply_two_tier_loom` (advisory + confirmed). Random exam / playground papers stay **raw** (shuffled ≠ sequence).

---

## Results boost

### After circ_v2 merge + promote (`20260715_191519_circ_v2` + Tier‑6)

Chronological network **tail 25%** (`n=5874`), loom `enter_k=3` / `exit_k=2` global fallback **+ per-class `exit_k=3` for `bgp_route_flap`/`vrf_leakage`** (§4 sweep).

| Mode | Macro‑F1 | Acc | BGP F1 | VRF F1 | Rare recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw frame | 0.841 | 0.871 | 0.616 | 0.844 | 0.823 |
| Sticky loom (global-only, prior) | 0.908 | 0.933 | 0.774 | 0.903 | 0.814 |
| **Sticky loom + per-class exit** | **0.912** | **0.932** | **0.790** | **0.911** | 0.889 |
| **Δ (boost, vs raw)** | **+0.071** | **+0.061** | **+0.174** | **+0.067** | +0.066 |

| Persistence summary | Value |
| --- | ---: |
| Frames changed | 703 |
| Raw fault frames → sticky | 2497 → 2245 |
| Fault frames suppressed | **252** |

**Circumstance existence head** (exam paper, not sticky): Macro‑F1 **0.719** · Acc **0.913** · VRF F1 **0.830** · BGP F1 **0.484** · rareR **0.858**. Artifact: `models/circumstance/`.

Classroom promote (random paper): Macro‑F1 **0.758** (`plain` β=1.0) after Mode‑B re-baseline on the merged lake.

### Prior Tier‑6-only sticky (historical)

Chronological network **tail 25%** (`n=3910`):

| Mode | Macro‑F1 | Acc | BGP F1 | VRF F1 |
| --- | ---: | ---: | ---: | ---: |
| Raw frame | 0.786 | 0.856 | 0.609 | 0.657 |
| Sticky loom | 0.880 | 0.938 | 0.858 | 0.865 |
| Δ | +0.094 | +0.082 | +0.249 | +0.208 |

Artifacts: `models/temporal_persist_score.json` and `decision_thresholds.json` → `loom.metrics`.

---

## 1. The problem (odds and evens)

Real network faults are messy:

| Reality | Failure mode if we ignore it |
| --- | --- |
| Faults are **rare** | Majority “healthy” drowning rare BGP/VRF |
| Some start **slowly** (accumulation) | Single short window misses the ramp |
| Some hit **instantly** (flap / cut) | Long-only features smear the onset |
| Many look like a fault then **die** | One loud frame → false alarm |
| Different faults last different times | Using duration as a feature → false signals |

**Odds** = “cry wolf” (declare a fault that never sticks).  
**Evens** = “miss a real one” (require so much proof that a true fault is delayed or ignored).

---

## 2. What we deliberately do *not* do

**Fault duration is not a classifier input.**

- Labels still use `fault_start` → `breach_time` to mark which *rows* are inside a real window.
- Absolute minutes / injector schedule length are **not** features.
- Reason: VRF windows are often shorter than BGP; the model would learn timetable length instead of telemetry shape.

Time is used only as:

1. **Alignment** — which rows fall inside a labelled event.  
2. **Order** — consecutive frames for persistence.  
3. **LSTM target** — `time_to_breach_minutes` for the “when?” head, not the “what fault?” head.

---

## 3. Warp 1 — Multi-scale pattern weave

`rebuild_unified.engineer_features` builds **two** rolling scales on the same metrics:

| Scale | Window | Column pattern | What it catches |
| --- | --- | --- | --- |
| **Long (slow)** | ~10 minutes | `{metric}_slope`, `_rolling_mean`, `_rolling_std`, `_accel` | Congestion fill, slow degradation |
| **Short (fast)** | ~2 minutes | `{metric}_w2m_slope`, … | Instant flaps, sharp onset spikes |

Metrics: `ifInOctets`, `ifOutOctets`, `jitter_ms`, `packet_loss_pct`, `bgp_update_rate` → **40 pattern features**.

```
        short warp (onset)          long warp (accumulation)
              │                           │
   accel / jump on 2m           rolling mean/std on 10m
              │                           │
              └──────────┬────────────────┘
                         ▼
              frame classifier (gate + XGB / wm)
```

```bash
python scripts/rebuild_unified.py --rpi-run 20260714_165648_tier6_x10
```

Do **not** paste shell placeholders like `<id>` literally — that causes a bash syntax error.

---

## 4. Warp 2 — Sticky hysteresis (persistence)

After the classifier emits a class **per frame**, `apply_loom` / `apply_persistence` in `deca_inference.py` walks the series **in time order**.

### State machine

| Current state | Incoming streak | Action |
| --- | --- | --- |
| `healthy` | Same **fault** class for `enter_k` frames (default **3**) | **Enter** that fault |
| Fault `F` | `healthy` for `exit_k` frames (default **2**) | **Exit** → healthy |
| Fault `F` | Different fault `G` for `enter_k` frames | **Switch** to `G` |
| Anything | Streak too short | Keep previous **committed** label |

```
healthy ──(enter_k × same fault)──► FAULT
   ▲                                  │
   └────(exit_k × healthy)────────────┘
```

| Knob | Turning it up | Effect |
| --- | ---: | --- |
| `enter_k` | harder to leave healthy | Fewer false starts; slower declare |
| `exit_k` | harder to clear a fault | Fewer blink-offs; longer sticky alarms |
| `enter_k = 1` | — | Same as raw frame scores on declare |

Default **enter_k=3, exit_k=2**: slightly stricter on raising than clearing.

**Critical:** loom only on **chronological** streams. Do not persist shuffled School Exam / playground papers.

### Per-class hysteresis — one window doesn't fit all four faults

A single global `(enter_k, exit_k)` forces every fault family through the same debounce window, even though each family's raw frame scores behave differently. `loom.enter_k_by_class` / `loom.exit_k_by_class` (dicts keyed by fault class name) override the global default per family; classes not listed fall back to `enter_k`/`exit_k`. `apply_persistence` / `apply_loom` / `apply_persistence_with_prearm` all accept `classes` (index→name) plus the two override dicts.

**The naive fix doesn't win — measure, don't guess.** The obvious hypothesis is *"BGP flap is fast/instant → give it a low `enter_k` so it declares quickly."* Swept empirically (`deca_score_temporal.py --enter-k-by-class '{"bgp_route_flap":1}'`), this **hurt** BGP F1 (0.774 → 0.543): BGP's raw frame scores are the noisiest of the four classes, so a short entry window mostly commits on single-frame noise instead of a real onset — entry speed and entry *robustness* are in tension, and for this classifier robustness wins.

What actually helped was patience on the **exit** side. BGP flaps and VRF leakage both have brief quiet frames mid-event (a flap storm pauses for a beat; a leak's symptoms flicker); declaring "recovered" one frame too early re-opens the door to a fresh entry debounce for no reason. Bumping `exit_k` 2→3 for just those two classes (`enter_k` untouched, congestion/tunnel untouched):

| Sweep | Macro‑F1 (sticky tail) | BGP F1 | VRF F1 |
| --- | ---: | ---: | ---: |
| Global `enter_k=3, exit_k=2` (baseline) | 0.9077 | 0.774 | 0.903 |
| + `bgp_route_flap enter_k=1` (naive fast-enter) | 0.8440 ↓ | 0.543 ↓ | 0.905 |
| + `bgp_route_flap exit_k=3` only | 0.9104 | 0.790 | 0.903 |
| **+ `bgp_route_flap` & `vrf_leakage` `exit_k=3`** (promoted) | **0.9120** | **0.790** | **0.911** |
| + also `congestion_breach`/`tunnel_degradation exit_k=3` | 0.9069–0.9071 ↓ | — | — |
| + any class `enter_k=4` (more patient onset) | 0.9047–0.9075 ↓ | — | — |

Congestion and tunnel were already at their best global exit setting — leave them alone. Live promoted config: `enter_k_by_class={}`, `exit_k_by_class={"bgp_route_flap": 3, "vrf_leakage": 3}`.

To re-sweep after a retrain or new campaign:

```bash
python scripts/deca_score_temporal.py --no-write-promoted \
  --no-per-class --exit-k-by-class '{"bgp_route_flap":3}'   # isolate one class
python scripts/deca_score_temporal.py                        # bake the winner in
```

### Two-tier loom — advisory (may be forming) + confirmed (declared)

Same philosophy as the outlook itself: *soft probabilities plus loom stability, what is likely forming, not prophecy.* Rather than picking one debounce window, run the **same state machine twice** on the same raw frame stream with different knobs — no new architecture, two honest outputs:

| Tier | `enter_k` | `exit_k` | Meaning |
| --- | ---: | ---: | --- |
| **advisory** | 2 (`advisory_enter_k`) | 1 (`advisory_exit_k`) | "Something may be forming" — cheap to flicker, never commits an alarm alone |
| **confirmed** | 3 (+ per-class exit above) | 2 (+ per-class) | "This is now declared" — the tuned sticky loom |

`apply_advisory` / `apply_two_tier_loom` / `predict_fault_stream_two_tier` in `deca_inference.py`. Dashboards can show both — an operator decides what an early, noisier signal is worth versus waiting for the robust one.

**Measured tradeoff** (chrono tail, `n=5874`, per-event lead via `summarize_advisory_lead`):

| Metric | Value |
| --- | ---: |
| Real fault events in tail | 15 |
| Events advisory caught | 15 / 15 |
| Events confirmed caught | 15 / 15 |
| **Mean lead time** (advisory correct before confirmed) | **3.8 frames** |
| Max lead time | 15 frames |
| Advisory-only window (advisory on, confirmed still healthy) | 93 frames |
| … correct early warning | 25 frames |
| … wrong-class | 0 frames |
| … pure noise (false advisory) | 68 frames |
| **Advisory lead-window precision** | **0.269** |
| Advisory's own Macro‑F1 (all frames) | 0.873 (vs raw 0.841, confirmed 0.912) |

Swept `advisory_enter_k=1` (no entry debounce at all — identical to raw): lead grows to 7.5 frames but lead precision drops to 0.149, i.e. mostly noise. `advisory_enter_k=2` is the sweet spot: still meaningfully smoother than raw, still ~4 frames ahead of the confirmed declaration. **Read this honestly**: advisory is *not* a second classifier — it is the confirmed tier's own raw material, just declared on a shorter fuse, so ~73% of its early-only frames are noise. It's a genuinely richer dashboard story ("may be forming" vs "confirmed"), not a free accuracy win.

```bash
python scripts/deca_score_temporal.py \
  --advisory-enter-k 2 --advisory-exit-k 1   # defaults; --no-advisory to skip
```

### Binding "what" + "when" — LSTM time-to-breach gate (measured, kept off)

The classifier's streak (the "what") and the LSTM's time-to-breach regression (the "when", `models/lstm/fault_lstm_v1.keras`, MAE ≈2 min) run in parallel today but never talk to each other inside the loom's decision. The obvious extra binding: **only let `enter_k` commit if the TTB trend has also been falling** over the same window the streak was built over — a genuinely building fault should show both signals agreeing; a noisy single-frame misclassification usually won't have a consistent falling-TTB trend backing it up.

Implemented as `_ttb_falling` (in `apply_persistence` / `apply_persistence_with_prearm`, threaded through `apply_loom`): at the moment the streak reaches its (possibly per-class) `enter_k`, additionally require the TTB predictions over that exact window to be non-increasing, allowing up to `ttb_gate_tolerance` upticks. `predict_ttb_stream` runs the LSTM over a chronological `X` to produce the per-frame TTB series (imputing missing columns the same way training did — see below).

**Measured — and this is why it ships disabled.** Swept on the same chrono tail:

| `ttb_gate_tolerance` | Confirmed Macro‑F1 | Events confirmed still catches | Advisory-only window precision |
| --- | ---: | ---: | ---: |
| Gate off (baseline) | **0.9120** | 15 / 15 | 0.269 |
| 0 (strict monotonic) | 0.6278 ↓↓ | 9 / 15 | 0.892 |
| 1 (allow 1 uptick) | 0.9027 ↓ | 15 / 15 | 0.588 |
| ≥2 (= window size − 1, `enter_k=3`) | 0.9120 (no-op) | 15 / 15 | 0.269 |

At `tolerance=0` the gate is devastating: Macro‑F1 drops to 0.628 and confirmed misses 6 of 15 real events entirely, because the LSTM's frame-to-frame TTB predictions bounce around too much (regression noise) to be perfectly monotonic over a 2–3 frame window — most genuine fault buildups get blocked, not just noisy misclassifications. `tolerance=1` is less destructive but still a net loss. `tolerance≥2` has literally no effect at `enter_k=3` (2 consecutive diffs, both allowed to rise) — it isn't a looser gate, it's a disabled one.

**Read honestly**: the "what" and "when" branches disagreeing on a 2–3 frame timescale, given a companion regressor with ~2-minute MAE, is not necessarily a **fault detection is wrong** signal — it's mostly telling you the LSTM is too coarse-grained for frame-level gating at the classifier's own entry window size. A longer, smoother trend window *independent* of `enter_k` (e.g. a regression slope over 8–10 frames, not raw adjacent-frame diffs over 2–3) might do better, but that wasn't validated here and would no longer be "the same window" as specified — flagged as follow-up, not shipped. Live default: `ttb_gate_enabled=False`.

```bash
python scripts/deca_score_temporal.py --ttb-gate --ttb-gate-tolerance 0   # reproduce the sweep
python scripts/deca_score_temporal.py --no-ttb-gate                       # default / promoted
```

### Soft streak — confidence-weighted entry (measured, **on**)

Hard mode counts consecutive frames equally: three wobbles at 0.4 confidence and three frames at 0.9 both need exactly three frames to enter. Replace the entry counter with a **running sum of per-frame confidence** — the threshold-adjusted winning score the classifier already uses for argmax (can exceed 1.0 when a class clears its decision threshold with room to spare). `enter_k` becomes the cumulative confidence threshold when `soft_streak_enabled` is true; **exit stays frame-based** (consecutive healthy frames).

`predict_weighted_multiclass_with_confidence` in `deca_school_exam_train.py` emits the per-frame scores; `apply_persistence(..., confidences=..., soft_streak=True)` accumulates them. Strong single-frame signals can commit faster; weak scattered votes need more real evidence — without losing the anti-flicker property on exit.

**Measured** (same chrono tail, per-class `exit_k=3` for BGP/VRF unchanged):

| Mode | Confirmed Macro‑F1 | BGP F1 | VRF F1 | Mean rare recall |
| --- | ---: | ---: | ---: | ---: |
| Hard streak (`enter_k=3` frames) | 0.9120 | 0.790 | 0.911 | 0.889 |
| Soft streak (`enter_k=3` conf) | 0.9264 | 0.866 | 0.908 | 0.841 |
| **Soft streak (`enter_k=2` conf)** | **0.9328** | **0.874** | **0.915** | **0.889** |
| Soft streak (`enter_k=4` conf) | 0.9209 | 0.853 | 0.900 | 0.821 |

The win is real and concentrated where it was needed: **BGP F1 jumps 0.790 → 0.874** because strong flap frames no longer wait for two extra weak frames to satisfy a hard count — weak wobbles still fail to accumulate enough confidence. VRF and congestion/tunnel hold or improve. Live default: `soft_streak_enabled=True`, `enter_k=2` (interpreted as cumulative confidence threshold, not frame count, while soft is on).

```bash
python scripts/deca_score_temporal.py --soft-streak --enter-k 2   # promoted config
python scripts/deca_score_temporal.py --no-soft-streak --enter-k 3  # revert to hard frames
```

### Multi-branch agreement — plain + wm in parallel (measured, kept off)

Extension #5: run the promoted primary head (`plain`) and a secondary challenger (`wm`, KMeans cluster layer) in parallel; only let the loom **enter** when the **full streak** matches on both branches. The secondary head is retrained on the chrono train slice (pre-tail) sharing the promoted gate — same inference path, different booster.

**Measured — net negative, ships disabled.** On the chrono tail the two branches agree on only **41.5%** of raw fault frames (1037/2497). Requiring full-streak agreement blocks most genuine buildups:

| Mode | Confirmed Macro‑F1 | BGP F1 | Mean rare recall |
| --- | ---: | ---: | ---: |
| Soft streak alone (baseline) | **0.9328** | **0.874** | **0.889** |
| + branch agreement (`wm`) | 0.5244 ↓↓ | 0.501 | 0.173 |

The branches disagree too often at frame level for strict streak agreement to help — `wm` was never promoted for a reason on this lake (School Exam gate). The code path (`--branch-agreement`, `branch_agreement_enabled`) stays for experimentation if a better secondary head appears, but live default: `branch_agreement_enabled=False`.

```bash
python scripts/deca_score_temporal.py --soft-streak --enter-k 2 --branch-agreement
```

### Topology correlation — neighbor-node echo (measured, kept off)

Extension #6: at each timestamp, parse `run_id` → station host, look up neighbors in `models/topology/topology_graph.json` (PE1↔CORE↔PE2), and only allow fault **entry** when ≥`topology_min_neighbors` neighbors also predict the same fault class at that timestamp. Healthy frames are always open.

**Measured — does not beat soft-streak baseline.** Neighbor echo rate on fault frames is high (85% at `min_neighbors=1`), but gating still blocks enough real onsets to lower Macro‑F1:

| `topology_min_neighbors` | Confirmed Macro‑F1 | vs soft baseline |
| --- | ---: | ---: |
| Gate off (baseline) | **0.9328** | — |
| 1 (≥1 neighbor agrees) | 0.9271 ↓ | −0.006 |
| 2 (both neighbors) | 0.9292 ↓ | −0.004 |

The graph signal is real (neighbors often agree) but the interleaved multi-station stream + strict per-frame gate still costs more than it saves on this eval tail. Worth revisiting with per-station chronological streams or a softer “weighted vote” instead of hard block — flagged as follow-up, not shipped. Live default: `topology_gate_enabled=False`.

```bash
python scripts/deca_score_temporal.py --soft-streak --enter-k 2 --topology-gate --topology-min-neighbors 1
```

---

## 5. Production wiring

On **promote**, `promote_candidate` writes loom defaults into:

- `models/fault_classifier/fault_classifier_xgb.pkl` → `loom`
- `models/fault_classifier/label_encoder.pkl` → `loom`
- `models/fault_classifier/decision_thresholds.json` → `loom`
- `models/manifest.json` → `school_exam.loom`

After promote (or anytime on the live model):

```bash
python scripts/deca_score_temporal.py
# global overrides: --enter-k 3 --exit-k 2 --tail-frac 0.25
# per-class overrides: --enter-k-by-class '{"bgp_route_flap":2}' --exit-k-by-class '{"vrf_leakage":3}'
# isolate the global-only baseline: --no-per-class
# dry metrics only (don't touch promoted artifacts): --no-write-promoted
```

That script:

1. Scores raw vs sticky (and advisory, with per-event lead time) on the network time tail.  
2. Writes `models/temporal_persist_score.json`.  
3. Patches `loom` + `loom.metrics` (Δ Macro‑F1, per-class F1, suppression counts, advisory + advisory_lead) into the promoted artifacts via `write_loom_into_promoted`.

**Live inference API** (chronological `X` only):

```python
from deca_inference import predict_fault_stream, loom_config_from_bundle

le_classes = label_encoder_bundle["classes"]  # index→name, from label_encoder.pkl

# Confirmed tier only (most callers):
raw, final = predict_fault_stream(
    bundle["gate"], bundle["full_clf"], X_chrono,
    healthy_idx=bundle["healthy_idx"],
    gate_thr=bundle["gate_thr"],
    class_thr=bundle["class_thr"],
    loom=loom_config_from_bundle(bundle),  # or None → DEFAULT_LOOM
    classes=le_classes,                    # activates per-class enter/exit_k
)
# final is what operators / dashboards should see as the declared alarm

# Both tiers, for a dashboard that wants an early heads-up too:
from deca_inference import predict_fault_stream_two_tier

raw, confirmed, advisory = predict_fault_stream_two_tier(
    bundle["gate"], bundle["full_clf"], X_chrono,
    healthy_idx=bundle["healthy_idx"],
    gate_thr=bundle["gate_thr"],
    class_thr=bundle["class_thr"],
    loom=loom_config_from_bundle(bundle),
    classes=le_classes,
)
# advisory: "may be forming" (fast, noisier) · confirmed: "declared" (robust)
```

Playground / exam: keep `predict_weighted_multiclass` only; scoreboard notes loom boost from `loom.metrics` when present.

---

## 6. Warp 3 — Near-miss labels

Campaign mid-rest mild `netem` blip (~40% of rests), logged as:

| Field | Value |
| --- | --- |
| `fault_type` | `precursor_aborted` |
| Rebuild mapping | → **healthy** (`HEALTHY_ALIASES`) |

Not required for the boost table above (persistence already suppresses raw spikes). Near-miss labels teach “pattern that dies ≠ fault class” at train time.

---

## 7. Warp 4 — Circumstance temporal (the run-up that *causes* a fault)

The loom does not only ask “is the breach on?”. Every fault has a **circumstance**: a run-up pattern of conditions that precedes and causes it. `scripts/deca_circumstance_campaign.py` runs a clean, balanced experiment — **5 events × 4 faults = 20** — and records **three phases** per event:

```
circumstance_start ──ramp──► breach_time ──hold──► recovery_time
   (pre-conditions forming)   (fault commits)       (cleared)
```

| Phase | Span | Meaning | Label emitted |
| --- | --- | --- | --- |
| **circumstance** | `circumstance_start` → `breach_time` | cause pattern building | `event_phase=circumstance`; `circumstance_label=<fault>` |
| **breach** | `breach_time` → `recovery_time` | the event itself | `event_phase=breach`; `fault_type=<fault>`; `circumstance_label=<fault>` |
| healthy | elsewhere | normal ops + aborted near-misses | `healthy` |

**Train on the basis of existence.** `rebuild_unified.label_circumstance_existence` adds `circumstance_label` — *which fault’s situation exists here* (run-up **or** breach), else `healthy`. That is a distinct target from the 5-class breach model: it teaches the model the **circumstance exists** before/around the breach, not just the loud frame. It is **additive** — `fault_type` / `unified_label` and the promoted loom are untouched.

Still no duration feature: phases only *label rows*; existence is judged from telemetry **shape and co-occurrence over order**, never from how many minutes an injector ran.

### What a circumstance is

In DECA, a **circumstance** is the **run-up pattern** in telemetry (shape + co-occurrence), **not the clock and not the breach itself**. From how the injectors work and what Prometheus scrapes, each fault has a recognizable circumstance family:

#### `congestion_breach`

- **What’s forming:** progressive capacity squeeze on the PE path.
- **Signals:** rising `ifIn` / `ifOut` pressure with a **falling** throughput slope; short-window accel turns sharp as the TBF steps down; mild→growing `packet_loss` / queueing `jitter` *before* the hard cap.
- **One line:** “path is filling and being choked.”

#### `tunnel_degradation`

- **What’s forming:** path quality dying (delay/loss on the tunnel face), not necessarily a bitrate wall.
- **Signals:** rising `jitter_ms` + `latency_ms` + `packet_loss_pct` together; multi-scale slopes up on loss/jitter while octets may look flatter than pure congestion.
- **One line:** “path is getting dirty (delay+loss), not just busy.”

#### `bgp_route_flap`

- **What’s forming:** control-plane instability, then accelerating.
- **Signals:** rising / bursty `bgp_update_rate` (and related control noise) with intermittent short metric spikes; often **spiky short-scale** (`w2m_*`) more than a smooth 10 m congestion ramp.
- **One line:** “routing is getting chatty / flappy before the rapid flap storm.”

#### `vrf_leakage`

- **What’s forming:** wrong reachability / policy leak (ADMIN VRF RT pollution in the lab).
- **Signals:** often **subtle** until wrong routes take effect — asymmetric host behavior, odd loss/latency without the classic congestion ramp; may look “almost healthy” longer, then jump. Hardest class: circumstance is more **control/topology-side** than a loud octets ramp.
- **One line:** “wrong VRF context is live; traffic starts to misbehave.”

**So:** circumstance = the **cause-pattern cocktail** (which metrics ramp together, short vs long scale) that makes that fault *able* to happen — congestion ≠ tunnel ≠ BGP ≠ VRF, even when they eventually all look “bad.”

### What is *not* a circumstance (by design)

- How many minutes the injector slept
- “This usually lasts 7 minutes”
- A single one-frame spike that dies (`precursor_aborted` / near-miss)

### How the loom uses that

| Layer | Question |
| --- | --- |
| Circumstance head | “Is fault X’s **situation** present (forming or on)?” |
| Fault classifier | “Which fault class is this frame?” |
| Sticky loom | “Has that pattern **held** long enough to declare?” (pre-arm if existence agrees) |

### Fixed classes, unbounded circumstance patterns

**Fault classes are fixed. Circumstance patterns are not.**

- **Fixed (closed set):** the 4 labelled faults + healthy. The existence head also predicts among those same names — “which of *these* situations exists?”
- **Not fixed (open / many):** *how* each situation shows up. Congestion can ramp slow or fast, with more jitter or more loss, on PE1 or another path, mild or severe. That is a continuous space of telemetry shapes — effectively **infinite variations** of the *same* circumstance family.

It is not “here are exactly 7 circumstances forever.” It is:

| Layer | Nature |
| --- | --- |
| Class / existence label | **Finite** vocabulary (BGP, VRF, congestion, tunnel, healthy) |
| Circumstance pattern | **Unbounded variation** inside each class |
| What the model learns | A **region in feature space**, not a hard checklist of recipes |
| Sticky loom | Whether *this* instance of the pattern **holds** long enough to declare |

You *can* add more later if ops invents new fault types (that is a new **class**, not infinite classes by accident). You should *not* try to enumerate every possible circumstance by hand — multi-scale features + labelled run-ups teach the family; sticky loom handles “does this instance stick?”

**Practical takeaway:** 4 cause-*families*, infinitely many *instances* — the loom is for the latter; the labels keep the former manageable.

### What the circumstance campaign extracts (exactly)

Each finished run under `data/rpi-net/runs/<id>/` produces:

| Artifact | What it is | Used for |
| --- | --- | --- |
| `circumstance_log.csv` | `event_id`, `fault_type`, `circumstance_start`, `breach_time`, `recovery_time`, precursor/breach minutes, `run_id` | Existence + phase labels; true TTB anchor = `breach_time` |
| `fault_injection_log.csv` | Compat log (`fault_start`→`breach_time`) | Older rebuild path; overridden when circumstance log present |
| `network_telemetry.csv` | Long-form Prom scrape + **BGP flap pulses** (`bgp_update_rate`) | Feature lake (octets, jitter, loss, BGP rate) |
| `network_campaign_export.csv` | Pivoted metrics + `event_phase` + `circumstance_label` + `fault_type` | Sanity plots / audit before training |
| `bgp_update_samples.csv` | Soft-clear pulse series (Prom has no FRR BGP counter) | Merged into telemetry for BGP family visibility |
| `campaign_state.json` / `campaign_run.log` | Resume + audit | Ops only |

**Label semantics after rebuild** (`label_circumstance_existence`):

| Column | Meaning |
| --- | --- |
| `event_phase` | `circumstance` (ramp) · `breach` (hold) · `none` |
| `circumstance_label` | Which fault’s **situation exists** (ramp ∪ breach), else `healthy` |
| `fault_type` / `unified_label` | Aligned to the same existence window when circumstance log is present |
| `time_to_breach_minutes` | Minutes to **true** `breach_time` (not recovery, not duration-as-feature) |

Multi-scale features (`*_slope`, `*_accel`, `*_w2m_*`) are built from telemetry **shape** — injector wall-clock length is never an XGB column.

Active campaign id: **`20260715_191519_circ_v2`** (completed; superseded killed run `20260715_231056`).

### Campaign quality rating

#### Historical first design — **7.5 / 10**

Strong as a **first circumstance campaign** (3-phase labeling, balanced 5×4, resume, near-misses, existence wiring). Not a 9+ yet — telemetry coverage and some family physics were thin, and dual logs could confuse “what trains what.”

**Already good (then and now)**

- True **circumstance → breach → recovery** stamps (varied precursor lengths)
- Reuses proven injectors (no untested chaos)
- Resumable, interleaved quota, cleanup, near-misses
- Additive `circumstance_label` path without breaking the 5-class + loom stack

#### Fixes (done before `circ_v2` restart)

| Fix | Why | Status |
| --- | --- | --- |
| BGP pulses → `bgp_update_rate` in export | BGP circumstance was invisible (no FRR Prom series) | **Done** |
| Align dual logs via circumstance rebuild | Ramp-only vs full-span conflict | **Done** |
| Mid-campaign Prom snapshot after each event | Crash ≠ lose hours of telemetry | **Done** |
| Richer VRF (RT + PE2 symptom ramp) | Pure RT+wait had weak graph signature | **Done** |
| Sanity plots after finish | Catch empty VRF/BGP windows before training | **Still to do** after run completes |

**Provisional design score after fixes: ~8.5 / 10.** After `circ_v2` finish + train: sticky Macro **0.908**, VRF existence F1 **0.830** — treat empirical campaign quality as **~8.7 / 10** (BGP existence still the soft spot at ~0.48).

#### Do **not** “fix” (and why)

| Don’t | Why |
| --- | --- |
| Stop mid-run to rewrite injectors again | Finish balanced 20 on `circ_v2`, then iterate |
| Add duration / “usual length” features | Breaks the loom rule; teaches schedule, not pattern |
| Invent infinite new fault mechanisms this run | Finite families + varied instances is the design |
| Replace sticky loom with RAG “explanations” | RAG is why/how-to-ops; not a substitute for scores/TTB |
| Merge randomly with dirty incomplete exports | Wait for `VALIDATION PASS` + `network_telemetry.csv` |
| Raise `enter_k` a lot to “feel safer” | Hides rare streaks; fix data visibility first |

#### Bottom line

| Score | Meaning |
| --- | ---: |
| First campaign design | **7.5** |
| After BGP/VRF/export/label upgrades | **~8.5** (provisional) |
| Proven (post-finish audit + train) | **TBD** |

```bash
# hardware campaign (SSHes to lab Pis; ~4–6 h for 20 events + rests)
python scripts/deca_circumstance_campaign.py --per-type 5

# fold the run into the lake (adds circumstance_label + event_phase columns)
python scripts/rebuild_unified.py --rpi-run <new_run_id>
```

Do **not** paste `<new_run_id>` literally — substitute the printed run directory name (current: `20260715_191519_circ_v2`).

**Existence head (wired):**

```bash
python scripts/deca_train_circumstance.py   # deferred until lake has circumstance_label
```

Trains `models/circumstance/circumstance_xgb.pkl` on `circumstance_label`. Live loom uses `predict_fault_stream_with_circumstance`: when existence agrees with a fault streak, `enter_k` drops to `prearm_enter_k` (default 2). Safe before campaign finish — script writes `deferred.json` if no existence signal yet.

### Human-in-the-loop outlook (not prophecy)

The loom’s job is to make **fault occurrence easier to anticipate before it fully happens** — without claiming certainty.

- It does **not** say “this will happen.”
- It reports **chance** that a given fault’s circumstance is forming / that the event is committing, and the **chances of what else** could be unfolding (distribution across congestion, tunnel, BGP, VRF, healthy).
- Sticky persistence reduces flicker so operators see a stable outlook, not one-frame ghosts.
- **A human decides the action** — mute, investigate, drain, open a change window, escalate. DECA advises; it does not own the remediation choice.

| Output style | Meaning |
| --- | --- |
| Hard declare only | Too brittle — looks like prophecy, hides near misses |
| Soft probabilities + loom stability | “What is *likely* forming, and what else?” — decision support |
| Automated fix from argmax | Out of scope — human remains the last mile |

Wire this as dashboard **outlook** panels: circumstance existence probs (forming), fault-class probs (what), optional TTB/Prophet (when) — loom sticky state as “committed outlook,” never as an unattended command.

**Rate of change → time left (the “when” channel).** Multi-scale slopes / accels (`*_slope`, `*_accel`, `*_w2m_*`) measure how fast the circumstance graph is changing. From that trajectory the loom can estimate **duration left until the event is likely to commit** — e.g. LSTM `time_to_breach_minutes` — still as a **chance / range**, not a fixed countdown. Important distinctions:

| Do | Don’t |
| --- | --- |
| Infer **time-to-event** from how steep the run-up is | Treat “faults last N minutes” as a class feature |
| Show “~X minutes left *if* this trajectory continues” | Promise a certainty clock |
| Combine with existence probs (what is forming) | Collapse “when” into the fault-class XGB input |

So the operator sees: **what** may occur (class + alternatives), **how likely**, and **how soon** the graph’s rate of change implies — then decides.

---

## 8. Full pipeline

```bash
cd /home/brain/deca-isro
source .venv/bin/activate

python scripts/rebuild_unified.py --rpi-run 20260714_165648_tier6_x10
python scripts/deca_school_exam_train.py --auto-promote --families plain,wm --rare-boosts 1,1.5
python scripts/deca_train_circumstance.py   # existence head (deferred until circumstance labels exist)
python scripts/deca_retrain_companions.py   # optional
python scripts/deca_score_temporal.py       # measure + bake loom metrics into live model
```

After circumstance campaign `20260715_191519_circ_v2` (**done** — VALIDATION PASS 5×4), rebuild with both runs then re-train:

```bash
python scripts/rebuild_unified.py \
  --rpi-run 20260714_165648_tier6_x10 \
  --rpi-run 20260715_191519_circ_v2
python scripts/deca_school_exam_train.py --auto-promote --families plain,wm --rare-boosts 1,1.5 \
  --baseline-macro-f1 0.75   # Mode-B re-baseline when lake distribution shifts
python scripts/deca_train_circumstance.py
python scripts/deca_score_temporal.py
```

School Exam unit-test Macro‑F1 ~0.80 on a fresh paper after promote can look “high” if the active model already matches the lake; the **gate** still compares the new student to the honest same-paper champion.

---

## 9. Design summary

```
  telemetry
      │
      ▼
  multi-scale features     ← short onset + long accumulation
      │
      ▼
  gate + multiclass head   ← frame scores (School Exam promotes this)
      │
      ├──────────────────────────────┐
      ▼                              ▼
  advisory loom                confirmed loom      ← same state machine,
  enter_k=2 / exit_k=1         enter_k=3 / per-class exit_k   two knob sets
  "may be forming"             "now declared"       (per-class tuned, §4)
      │                              │
      └──────────────┬───────────────┘
                      ▼
  probability outlook      ← chances of each fault / circumstance (not “will happen”)
      │
      ▼
  human decision           ← operator chooses the action; advisory = heads-up,
                              confirmed = trustworthy alarm

  (parallel) circumstance existence ← does fault X's run-up exist? (Warp 4)
```

| Goal | Mechanism |
| --- | --- |
| Structure, not timetable | No duration feature |
| Instant vs slow | 2 m + 10 m warps |
| Aborted almost-faults | Persistence + `precursor_aborted` |
| Circumstance that causes a fault | 3-phase campaign + `circumstance_label` (finite classes, unbounded pattern instances) |
| Anticipate before hard breach | Existence + class probabilities as chance outlook |
| Human remains in control | Advise probabilities; never auto-own remediation |
| Rare classes found | Classroom weights; don’t raise `enter_k` so high that rare streaks never land |
| One window doesn't fit every fault | Per-class `enter_k_by_class`/`exit_k_by_class`, swept not guessed |
| Early heads-up vs trustworthy alarm | Two-tier loom — advisory (fast/noisy) + confirmed (robust), same state machine |
| "What" + "when" binding, tried honestly | `ttb_gate_*` — measured net negative at this window size, shipped **off** rather than assumed helpful |
| Finer entry sensitivity without more flicker | `soft_streak_enabled` — cumulative confidence for entry, frame count for exit; BGP F1 0.79→0.87 |
| Multi-head agreement, tried honestly | `branch_agreement_*` — plain+wm agree only 41% on fault frames; net negative, **off** |
| Graph correlation across nodes, tried honestly | `topology_gate_*` — neighbor echo real but Macro‑F1 still ↓, **off** |
| Honest reporting | Random exam = promote; temporal script = sticky boost + advisory lead-time |

The loom does not invent physics and does not replace the operator. It **delays commitment** until the pattern repeats, surfaces **chances** of what is forming (and alternatives), and **clears** when healthy repeats — so humans can act with better foresight, not false certainty.
