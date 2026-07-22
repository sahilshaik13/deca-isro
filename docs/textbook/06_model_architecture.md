# Chapter 6 — The Model Architecture

## The big picture first

DECA is not one single model. It is a small team of specialized models,
each with its own specific job, working together. This chapter walks
through every member of that team, what it does, why it exists, and how
they all fit together into one final answer. If you haven't read Chapter
2 (the machine learning glossary) yet, this is a good time to at least
skim it — nearly every term used here is defined there in detail.

Here is the whole team, at a glance, before we go through each one:

```
                              telemetry (Chapter 4/5)
                                      │
                                      ▼
                      ┌───────────────────────────────┐
                      │     feature engineering        │
                      │  (rolling stats, slope, accel,  │
                      │   z-score companions)           │
                      └───────────────┬───────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
     ┌─────────────────┐   ┌──────────────────┐    ┌────────────────────┐
     │  Isolation       │   │  The Gate +      │    │  Prophet (×3) +    │
     │  Forest + Platt  │   │  Multiclass Head │    │  LSTM (time-to-    │
     │  (unsupervised   │   │  (the main fault  │    │  breach) +         │
     │  "how weird is   │   │  classifier)      │    │  Topology graph    │
     │  this" score)    │   │                  │    │  (supporting cast) │
     └─────────────────┘   └────────┬─────────┘    └────────────────────┘
                                     │
                                     ▼
                          ┌────────────────────┐
                          │  The temporal loom  │
                          │  (sticky hysteresis, │
                          │   Chapter 2)         │
                          └────────┬───────────┘
                                     │
                                     ▼
                            final, stable answer
                       (healthy, or a specific fault,
                        with a confidence level)
```

---

## The main event: the gate + multiclass head

This is DECA's central classifier, and it works in two stages —
deliberately, not by accident.

### Stage 1 — the gate: "is anything wrong at all?"

The gate is a simple binary classifier (Chapter 2). Its only job is to
ask a single yes/no question about the current window of telemetry:
"does this look anomalous, or does it look healthy?"

**Why split the decision into two stages at all, instead of one big
five-way decision?** Because of a problem explained in detail in Chapter
2 (class imbalance): `healthy` massively outnumbers any single fault
class in the training data. If you tried to train one single model to
choose directly between all five options at once, the overwhelming
majority of "healthy" examples can end up dominating the model's
learning, making it much harder to notice the comparatively rare fault
patterns. Splitting the decision into "first, a simple healthy-vs-not
filter, then, only if needed, a detailed which-fault decision" lets each
stage focus on a cleaner, easier version of its own specific job.

The gate produces a number between 0 and 1 — its confidence that
something is wrong (`p(anomaly)`). This number is compared against a
tunable cutoff, `gate_thr` (currently **0.40** to **0.50** depending on
the specific promoted configuration), to actually make the yes/no call.

### Stage 2 — the multiclass head: "okay, but which specific fault?"

Only once the gate has said "something looks anomalous" does DECA move
on to ask the more detailed question: which of the four specific fault
types (Chapter 3) does this look like? This second stage is a multiclass
classifier (Chapter 2), and it also produces a confidence score for each
of the four fault classes, which is then compared against its own
per-class threshold (`class_thr`) to make the final call.

### What both stages are actually built from: XGBoost

Both the gate and the multiclass head are built using **XGBoost**
(Chapter 2) — an ensemble of many decision trees, each new tree
specifically trained to fix whatever mistakes the earlier trees were
still making. We chose this over a deep neural network deliberately:
tree-based methods like XGBoost are known to work better than large
neural networks on this *kind* of data — a moderately-sized table of
carefully engineered numeric features (tens of thousands of rows,
roughly a hundred columns) — rather than, say, raw images or raw text,
where deep neural networks tend to have a real advantage.

### Fighting class imbalance inside training itself: inverse-frequency weighting

On top of the two-stage split above, both the gate and the multiclass
head are trained using inverse-frequency sample weighting (Chapter 2) —
mistakes on the rarer fault classes are deliberately made to count for
more during training, so the model can't get away with ignoring them
just because they're less common.

### Three interchangeable "head" architectures — and an honest experiment

DECA's multiclass head actually comes in three different, swappable
architecture designs, all trained and compared every single training
cycle:

| Head name | What it adds on top of the basic XGBoost head | Result on our data |
| --- | --- | --- |
| `plain` | Nothing extra — the straightforward, basic booster | The long-running champion on most training rounds |
| `wm` | An extra KMeans clustering step (Chapter 2) added as additional input features, plus a slightly more regularized booster | Roughly a wash most rounds; won by a statistically insignificant margin (0.0005) in one specific promoted round |
| `moe` | A full "mixture of experts" design (Chapter 2) — one specialist sub-model per fault class, blended by a separate gating model | Measurably **worse** — about 0.064 lower macro-F1 than `plain` in one head-to-head test |

**Why bother testing `wm` and `moe` at all, if they mostly don't win?**
Because this is exactly the honest, disciplined way to answer the
question "would a fancier, more complicated model actually do better
here?" without just guessing. The answer we got, tested fairly and
repeatedly, was: *not really, at least not with the amount of rare-class
data we currently have.* `moe` in particular suffers from **overfitting**
(Chapter 2) — with only around 40 to 75 real examples of some rare fault
classes, a model with that many extra adjustable parts ends up
memorizing quirks of those specific few examples rather than learning a
pattern general enough to work on new ones. This is one of the clearest,
most important lessons of the whole project: **more model complexity is
not automatically better, especially when your rarest classes don't have
much data to support it.** All three heads stay wired into the training
pipeline permanently, ready to be re-evaluated every time — if a future
data campaign eventually supplies enough rare-class examples to actually
support a deeper model, the promotion gate (below) will notice and
promote it automatically, with no manual intervention needed.

### The promotion gate: how a new model earns the right to go live

Every time we retrain, the newly trained "challenger" model is compared,
head-to-head, against the current "champion" model already in
production, on the exact same held-out exam data (Chapter 2). The
challenger is only allowed to actually replace the champion if it:

1. Scores at least as well as the champion on that shared exam, **and**
2. Clears an overall minimum bar of macro-F1 **≥ 0.717**.

This whole process is run by `scripts/deca_school_exam_train.py` — our
own internal nickname for it is "the School Exam." If a challenger fails
either condition, nothing changes — the existing champion keeps running,
and the failed attempt is simply recorded as useful, honest information
about what didn't work (Chapter 8 documents several such honest,
recorded failures in detail).

---

## The supporting cast: four extra specialist models

Alongside the main gate + multiclass head, DECA includes four additional
models, each answering a genuinely different question the main
classifier doesn't try to answer:

### Isolation Forest — "how weird does this look, in general?"

An Isolation Forest (Chapter 2) trained only on healthy examples, with
no fault labels at all, providing an independent "how unusual does this
look" confidence score, calibrated into an honest probability using
Platt calibration (Chapter 2). Because it never learns any specific
fault's shape, it can in principle flag something as unusual even if
it's a kind of problem the main classifier was never specifically taught
to recognize by name — a general-purpose safety net, not a replacement
for the main classifier. Measured performance: ROC-AUC **0.720**.

### LSTM — "how many minutes until this actually breaks?"

An LSTM neural network (Chapter 2) that doesn't try to name the fault at
all — its only job is to look at a short recent sequence of measurements
and estimate "time to breach" in minutes: roughly how long remains before
a developing problem is likely to fully "break." Measured performance:
mean error of about **2.13 minutes** on a held-out set of 623 sequences.

We deliberately tested, and rejected, tightly binding this "when" signal
directly into the main classifier's fault-declaring decision (a "TTB
gate" that would require the LSTM's trend to also be falling before the
classifier is allowed to declare a fault). The honest result: at its
strictest setting, this gate was actively harmful — it dropped overall
accuracy sharply and caused the system to miss 6 out of 15 real fault
events in a test, because the LSTM's own minute-to-minute predictions are
naturally too noisy to demand a perfectly smooth, ever-falling trend over
such a short window. This stays shipped **off** by default, as an honest,
measured negative result rather than an assumed improvement.

### Prophet (×3) — "what does a normal day/week usually look like?"

Three separate Prophet models (Chapter 2), one each for traffic volume,
jitter, and BGP update rate, that learn typical calendar patterns
(busier on weekdays, quieter at night, and so on) to build an "expected
normal" envelope for each of those three metrics — useful context for
questions like "is a serious problem structurally more likely given how
this metric is trending," independent of moment-to-moment fault
detection.

### Topology graph — "do my neighbors agree with me?"

A simple map (Chapter 2) of which stations connect to which other
stations (PE1 ↔ CORE ↔ PE2), used in an experimental feature that checks
whether neighboring stations' predictions agree before letting a fault
be declared. Honestly tested and found not to help enough to justify
turning it on by default — the underlying idea (neighbors often *do*
agree during a real fault) is real and measured (an 85% agreement rate at
one setting), but gating strictly on it still ended up blocking enough
genuine fault detections that overall accuracy went down, not up. Stays
shipped **off**, as another honest negative result.

### The circumstance existence head — "is this fault's situation forming?"

A separate specialist classifier, trained specifically on data from the
circumstance campaign (Chapter 5), that answers a subtly different
question than the main classifier: not "which fault is happening right
now," but "does the *run-up pattern* toward one of these four fault
families currently exist" — whether that pattern is still just building
up, or has already fully broken into a real fault. This is used to
"pre-arm" the main sticky-persistence system (below) slightly faster when
its own, independent existence signal agrees with what the main
classifier's raw frame predictions are starting to show.

---

## The temporal loom: turning a jumpy series of guesses into one stable answer

Everything described above works on one single "frame" (one moment in
time) at a time. But a real, live stream of these frame-by-frame guesses
is naturally somewhat jumpy — a single noisy frame here or there could
otherwise trigger (or clear) a fault alarm all on its own. DECA's
"temporal loom" (Chapter 2's "hysteresis" and "temporal persistence,"
explained in much more implementation detail in
`docs/DECA_TEMPORAL_LOOM.md`) is the layer that fixes this.

### How it works, in one paragraph

The loom requires a fault prediction to repeat consistently for several
frames in a row (`enter_k`, default **3**) before it will officially
"declare" that fault, and requires several healthy frames in a row
(`exit_k`, default **2**) before it will officially "clear" a declared
fault back to healthy. This alone produced one of the single biggest
measured improvements in the whole project: on one measured chronological
test slice, this pushed macro-F1 from **0.841** (raw, frame by frame,
un-smoothed) up to **0.912** — using the exact same underlying frame-level
predictions, just organized more sensibly across time.

### Refinements that were tried, measured, and either kept or dropped

The project ran a whole series of honest, measured experiments on top of
this basic idea, each one either kept (because it genuinely helped) or
explicitly turned off (because it didn't):

| Refinement | Idea | Kept or dropped? | Why |
| --- | --- | --- | --- |
| Per-class `enter_k`/`exit_k` | Give each of the four faults its own tuned patience settings instead of one global setting | **Kept** (partially) | Raising exit patience specifically for `bgp_route_flap` and `vrf_leakage` (both prone to brief mid-event quiet frames) measurably helped; the "obvious" idea of *lowering* entry patience for BGP's supposedly fast onset actually hurt badly (0.774 → 0.543 F1) because BGP's raw per-frame scores are unusually noisy |
| Two-tier loom (advisory + confirmed) | Run the exact same state machine twice, with a fast/loose set of settings and a slow/strict set, giving an early "may be forming" heads-up alongside the slower, trustworthy "confirmed" alarm | **Kept** | Genuinely useful extra dashboard information (about 3.8 frames of average early warning), honestly reported as noisier (about 27% correct during the early-only window) rather than oversold as a second reliable classifier |
| TTB gate (binding "what" and "when") | Only let the loom declare a fault if the LSTM's time-to-breach trend also agrees | **Dropped** | Measured actively harmful at its strict setting; see the LSTM section above |
| Soft streak (confidence-weighted entry) | Count cumulative confidence instead of a flat frame count, so a few very strong frames can enter faster than several weak, wobbly ones | **Kept** | Clear, measured win, especially for `bgp_route_flap` (F1 jumped from 0.790 to 0.874) |
| Branch agreement (two model families must agree) | Require the `plain` and `wm` heads to agree before declaring | **Dropped** | The two heads only agreed on about 41.5% of real fault frames — requiring agreement blocked far more genuine detections than it filtered false ones (macro-F1 dropped from 0.933 to 0.524) |
| Topology gate (neighbors must agree) | See the Topology graph section above | **Dropped** | Real signal, but net negative on overall accuracy |

This table is, honestly, one of the best single illustrations in the
whole project of good scientific practice: a plausible-sounding idea was
proposed, actually implemented, measured fairly against the same test
data, and then either kept or dropped based on what the numbers actually
showed — not based on which idea sounded better in theory.

---

## Where all the settings actually live: `decision_thresholds.json`

Every one of the tunable numbers described in this chapter — `gate_thr`,
each fault's `class_thr`, `enter_k`/`exit_k` (including all the
per-class overrides), the advisory tier's settings, and which
refinements are turned on or off — lives in one single, plain,
human-readable text file:
`models/fault_classifier/decision_thresholds.json` (Chapter 1's JSON
format). None of this is hidden or hard-coded buried inside program
logic.

**Why this matters so much:** this is exactly what makes Chapter 10's
whole "can DECA move to a different network quickly" story possible.
Adjusting DECA's behavior for a new environment can, in the best case,
mean editing roughly eight numbers in a plain text file — not rewriting
any code, and not necessarily retraining any trees at all.

---

## Continue

You've now seen every member of DECA's model "team" and how they work
together. Chapter 7 tells the honest, detailed story of how this whole
system actually got built — including everything that went wrong along
the way, in the order it happened. Continue to
[Chapter 7 — Risen from the Fallen](07_risen_from_the_fallen.md).
