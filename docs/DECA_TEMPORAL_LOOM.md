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

**Live path:** promoted bundle includes `loom: {enabled, enter_k, exit_k}`; chronological streams use `predict_fault_stream` / `apply_loom`. Random exam / playground papers stay **raw** (shuffled ≠ sequence).

---

## Results boost (Tier‑6 multi-scale champion)

Chronological network **tail 25%** (`n=3910`), loom `enter_k=3` / `exit_k=2`.  
Artifacts: `models/temporal_persist_score.json` and `decision_thresholds.json` → `loom.metrics` (baked into the live model).

| Mode | Macro‑F1 | Acc | BGP F1 | VRF F1 | Rare recall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Raw frame | 0.786 | 0.856 | 0.609 | 0.657 | 0.887 |
| **Sticky loom** | **0.880** | **0.938** | **0.858** | **0.865** | **0.901** |
| **Δ (boost)** | **+0.094** | **+0.082** | **+0.249** | **+0.208** | **+0.014** |

| Persistence summary | Value |
| --- | ---: |
| Frames changed | 510 |
| Raw fault frames → sticky | 1434 → 1078 |
| Fault frames suppressed | **356** (mostly aborted spikes) |

Classroom (random paper, **no** loom — expected):

| Metric | After multi-scale promote |
| --- | ---: |
| Exam Macro‑F1 | ~0.75–0.77 |
| BGP / VRF F1 | ~0.55 / ~0.51 |
| 3-seed Macro | ~0.748 ± 0.008 |

Tunnel F1 can dip slightly under sticky (sticky clears less aggressively mid-event) — rare BGP/VRF and overall Macro are the win.

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
# optional overrides: --enter-k 3 --exit-k 2 --tail-frac 0.25
# dry metrics only: --no-write-promoted
```

That script:

1. Scores raw vs sticky on the network time tail.  
2. Writes `models/temporal_persist_score.json`.  
3. Patches `loom` + `loom.metrics` (Δ Macro‑F1, per-class F1, suppression counts) into the promoted artifacts via `write_loom_into_promoted`.

**Live inference API** (chronological `X` only):

```python
from deca_inference import predict_fault_stream, loom_config_from_bundle

raw, final = predict_fault_stream(
    bundle["gate"], bundle["full_clf"], X_chrono,
    healthy_idx=bundle["healthy_idx"],
    gate_thr=bundle["gate_thr"],
    class_thr=bundle["class_thr"],
    loom=loom_config_from_bundle(bundle),  # or None → DEFAULT_LOOM
)
# final is what operators / dashboards should see
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

### Fixed classes, unbounded circumstance instances

**Fault / existence labels are a closed set.** The vocabulary is fixed: `healthy` plus the four classified faults. The existence head answers “which of *these* situations is present?” — not an open-ended essay.

**Circumstance patterns are not fixed.** Inside each class there are effectively **infinite variations** of the same cause family (slow vs fast ramp, more jitter vs more loss, different hosts/paths, mild vs severe). The model does **not** memorize a finite checklist of recipes; it learns a **region in multi-scale feature space** for each family.

| Layer | Nature |
| --- | --- |
| Class / `circumstance_label` | **Finite** vocabulary (4 faults + healthy) |
| Circumstance pattern (how it looks) | **Unbounded** variation inside each class |
| What XGB learns | A **region in feature space**, not hand-listed triggers |
| Sticky loom | Whether *this* instance of the pattern **holds** long enough to declare |

Add a **new fault type** only when ops defines a new labelled class (taxonomy change). Do **not** try to enumerate every possible operational circumstance by hand — labelled run-ups + multi-scale features teach the family; loom commitment handles each instance.

### Circumstance families (what tends to form each fault)

These are **cause-pattern families** in lab telemetry (shape + co-occurrence), not a closed list of exact triggers. Same family, many instances.

| Fault | Circumstance family (one line) | Typical forming signals |
| --- | --- | --- |
| `congestion_breach` | Path is filling and being choked | Falling throughput / TBF-style squeeze; octets pressure up then capped; rising queueing `jitter` / early `packet_loss` on short+long scales |
| `tunnel_degradation` | Path is getting dirty (delay+loss), not just busy | Rising `jitter_ms`, `latency_ms`, `packet_loss_pct` together; loss/jitter slopes up while octets often flatter than pure congestion |
| `bgp_route_flap` | Routing getting chatty / flappy before a storm | Bursty rising `bgp_update_rate`; spiky short-scale (`w2m_*`) more than a smooth 10 m congestion ramp |
| `vrf_leakage` | Wrong VRF / policy context is live | Often subtle early (control/topology-side); asymmetric or sudden misbehaviour without a classic congestion ramp — harder, fewer loud octets cues |

**Not a circumstance (by design):** injector wall-clock length; “this fault usually lasts N minutes”; a one-frame spike that dies (`precursor_aborted` / near-miss).

How the layers use this:

| Layer | Question |
| --- | --- |
| Circumstance head | Does fault X’s **situation** exist (forming or on)? |
| Fault classifier | Which fault class is this frame? |
| Sticky loom | Has that pattern **held** long enough to declare? (pre-arm if existence agrees) |

```bash
# hardware campaign (SSHes to lab Pis; ~4–6 h for 20 events + rests)
python scripts/deca_circumstance_campaign.py --per-type 5

# fold the run into the lake (adds circumstance_label + event_phase columns)
python scripts/rebuild_unified.py --rpi-run <new_run_id>
```

Do **not** paste `<new_run_id>` literally — substitute the printed run directory name.

Outputs per run dir: `circumstance_log.csv` (event_id, fault_type, 3 phase stamps), plus the usual `fault_injection_log.csv` / `network_telemetry.csv` (so the existing 5-class + loom pipeline keeps working unchanged).

**Existence head (wired):**

```bash
python scripts/deca_train_circumstance.py   # deferred until lake has circumstance_label
```

Trains `models/circumstance/circumstance_xgb.pkl` on `circumstance_label`. Live loom uses `predict_fault_stream_with_circumstance`: when existence agrees with a fault streak, `enter_k` drops to `prearm_enter_k` (default 2). Safe before campaign finish — script writes `deferred.json` if no existence signal yet.

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

After circumstance campaign `20260715_231056` finishes, rebuild with **both** runs then re-train school exam + circumstance:

```bash
python scripts/rebuild_unified.py \
  --rpi-run 20260714_165648_tier6_x10 \
  --rpi-run 20260715_231056
python scripts/deca_school_exam_train.py --auto-promote --families plain,wm --rare-boosts 1,1.5
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
      ▼
  persistence loom         ← enter_k / exit_k (live + temporal eval)
      │
      ▼
  operator / dashboard alert

  (parallel) circumstance existence ← does fault X's run-up exist? (Warp 4)
```

| Goal | Mechanism |
| --- | --- |
| Structure, not timetable | No duration feature |
| Instant vs slow | 2 m + 10 m warps |
| Aborted almost-faults | Persistence + `precursor_aborted` |
| Circumstance that causes a fault | 3-phase campaign + `circumstance_label` (finite classes, unbounded pattern instances) |
| Rare classes found | Classroom weights; don’t raise `enter_k` so high that rare streaks never land |
| Honest reporting | Random exam = promote; temporal script = sticky boost |

The loom does not invent physics. It **delays commitment** until the pattern repeats, and **clears** when healthy repeats — so rare real faults that persist still win, and one-frame ghosts usually lose.
