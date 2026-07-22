# Chapter 8 — Tier-by-Tier History

## What "tiers" means in this project

As DECA's accuracy problems got harder to solve, we deliberately worked
through fixes in a specific, disciplined order — cheapest and safest
fixes first, more expensive or riskier fixes only once the cheaper ones
were genuinely exhausted. We nicknamed each step a "tier." This chapter
walks through that whole ladder, one rung at a time, in the order it was
actually climbed, with the real before/after numbers for each step. The
full technical version of this same history lives in
[`docs/DECA_ROI_TIERS.md`](../DECA_ROI_TIERS.md) — this chapter is the
plain-English walkthrough of that same document.

**Why climb a ladder instead of just trying everything at once?**
Because if you change five things at the same time and the score goes
up, you have no idea which of the five changes actually helped, which
one hurt, and which ones did nothing at all. Climbing one rung at a
time, and measuring honestly after each one, is what lets every claim in
this book be backed by a specific, isolated piece of evidence rather than
a vague "we did a bunch of stuff and it got better."

```
Phase 1  →  Tiers 1–3   (smarter use of the software we already had)
Phase 2  →  Tier 4      (a tempting shortcut we deliberately refused)
Phase 3  →  Tiers 5–6   (genuinely new features and new real data)
```

---

## Tier 1 — Splitting one hard decision into two easier ones (the "gate")

### The problem this solves

`healthy` massively outnumbers any single fault class in our data. A
single model trying to choose directly between all five options at once
can get a deceptively good-looking overall score just by being great at
recognizing `healthy`, while barely learning the much rarer fault
patterns at all — before this fix, mean recall on the two rarest classes
(BGP + VRF combined) was only about **0.26**.

### The fix

Split the decision into two stages (fully explained in Chapter 6): first
a simple binary gate ("is anything wrong at all?"), then, only if the
gate says yes, a more detailed multiclass decision ("okay, but which
specific fault?"). This stops the overwhelming `healthy` majority from
dominating every single decision boundary in the model.

### The result

Mean recall on the rare classes (BGP + VRF) jumped from about **0.26 to
about 0.67** — more than double, from this one structural change alone.

---

## Tier 2 — Making rare mistakes cost more during training (inverse-frequency weighting)

### The problem this solves

Even with the gate in place, a model being trained can still find it
"cheap" to get a rare class wrong, simply because there are so few
examples of it that getting them all wrong barely dents the overall
training score.

### The fix

Inverse-frequency weighting (explained fully in Chapter 2): during
training, a mistake on a rarer class is deliberately made to count for
more than an equivalent mistake on a common class, proportional to how
rare that class actually is. This was applied to the gate and both
multiclass head variants, computed only on the training data (never on
the held-out test data, to keep the evaluation honest).

---

## Tier 3 — Choosing the model's decision cutoffs deliberately, not by default

### The problem this solves

A trained model produces a confidence *score*, not an automatic yes/no
answer — something has to decide exactly where the cutoff line is
(Chapter 2's "threshold"). Leaving this at some arbitrary default value
wastes an opportunity to specifically tune it for what actually matters
most here: not missing rare faults.

### The fix

We swept a whole grid of possible cutoff values on validation data (a
portion of data kept separate purely for this tuning step, distinct from
the final honest test set) and picked whichever combination scored best
on a formula that deliberately weights rare-class performance heavily:

$$
S = 0.4 \cdot \text{Macro-F1} + 0.6 \cdot \text{mean}(F1_{\text{rare}})
$$

In plain words: this formula deliberately cares more (60% of the weight)
about how well the rare classes are doing than about the single overall
average score (40% of the weight) — a deliberate choice reflecting that
missing a rare, serious fault matters more than a small overall score
change.

### The result

Together, Tiers 1–3 raised overall macro-F1 from **0.716 to 0.721**, and
raised recall specifically on `bgp_route_flap` from **0.23 to 0.68**, and
on `vrf_leakage` from **0.29 to 0.65**. Overall accuracy actually
*dropped slightly* (0.97 → 0.94) — an expected, accepted trade-off, since
the model is now correctly calling more genuine anomalies instead of
defaulting to "healthy" so often.

---

## Tier 4 — The tempting shortcut we deliberately refused: SMOTE

### The problem this "solves" (on paper only)

With so few real examples of the rare fault classes, a very common,
well-known technique called SMOTE (Chapter 2) can artificially generate
brand-new, synthetic, made-up examples of a rare class by mathematically
blending together features of the few real ones — instantly balancing
out the dataset and, on paper, boosting the reported score.

### Why we said no

DECA's features are built from real, physical, chronological
relationships across real time — slope, acceleration, rolling averages
over a real 10-minute or 2-minute window (Chapter 2). Artificially
blending together rows to invent fake new ones breaks that real physical
relationship, producing rows that could never have actually occurred in
real time. The resulting score boost would be dishonest — it would
measure how well the model learned to recognize fabricated data, not real
network behavior.

### The decision, recorded permanently

This refusal is written directly, permanently, into the model's own
saved configuration files: `smote: false`,
`smote_policy: refused_tier4_temporal_integrity`. This is not something
that could be quietly reversed later without it showing up clearly in the
model's own record of itself.

---

## Tier 5 — Genuinely new, protocol-level features (the multi-round story)

This is the longest, most eventful tier in the whole project's history —
essentially the technical backbone of Chapter 7's Problems 6 through 8,
now laid out purely as a numbers timeline.

### Tier 5, phase 1 — `vrf_route_count` (and the phantom-VRF discovery)

We built and deployed a brand-new, direct measurement:
`vrf_route_count` — literally counting how many routes exist inside the
supposedly-locked `vrf-admin` VRF's own table (Chapter 4, Chapter 5).
While wiring this up and testing it end to end, we discovered the
phantom-VRF bug described in full in Chapter 7's Problem 6 — for a long
time, the actual fault injector had never been leaking a real route at
all. This was fixed and verified live (route count 0→4 on inject, 4→0 on
revert).

### Tier 5, round 1 — a first dedicated VRF campaign, and an unwelcome side effect

A campaign weighted toward tunnel+VRF and congestion+VRF combined faults
(`tier5_vrf_overlap_20260720_0252`) raised `vrf_leakage` exam F1 from
**0.47 to 0.59** — but `bgp_route_flap` dipped from **0.51 to 0.45** in
the same round.

### Tier 5, round 2 — deliberately avoiding BGP data, and a surprising non-result

Hypothesizing the BGP dip was simply "dilution by volume," a follow-up
campaign (`tier5_vrf_consolidate_20260720_1418`) deliberately scheduled
**zero** new bgp+VRF compound events. `vrf_leakage` kept climbing (0.59
→ **0.63**), but `bgp_route_flap` **still dropped** (0.45 → **0.35**),
even with zero new BGP training volume added that round — the exact
"balloon-squeezing" clue from Chapter 7, Problem 7.

### Tier 5, the direct diagnosis — a gate miss, and a fabricated signal

A dedicated diagnostic (`scripts/deca_bgp_diagnose.py`) proved the
failure was happening at the very first stage (the gate), not the later
classification stage: **53% of real `bgp_route_flap` rows were being
silently called `healthy`**. Tracing this into the injector code
revealed that `bgp_route_flap`'s only "signal" was a manually-written,
fabricated scalar — not a real measurement — and that, unlike every
other fault, it had no accompanying real traffic disturbance at all.

### Tier 5b — a real, live `bgp_flap_count` exporter

We confirmed, live via `vtysh`, that FRR's own `routeRefreshSent`/
`routeRefreshRecv` neighbor counters genuinely move every time our
BGP-flap-simulating command runs (verified: +6 sent / +3 received across
3 test clears). We built and deployed a real exporter for this
(`lab/deca-bgp-flap-count.sh`), verified live end-to-end through the full
Telegraf → Prometheus pipeline (53 → 56 on the live series, after 2 real
clears).

### Tier 5b — the seed campaign: a real, if partial, effect

Because the exporter only started collecting data *after* it went live,
existing historical rows had zero real `bgp_flap_count` signal. A small,
lean 6-event seed campaign
(`scripts/deca_bgp_flap_recall_campaign.py`) added real signal to only
about 18% of the class's total rows, but even that partial coverage
moved the gate's mean confidence on `bgp_route_flap` from **0.516 to
0.542**, and moved the overall candidate macro-F1 from **0.6948 to
0.7110** — the closest any round had yet come to the 0.717 bar (a gap of
just 0.006, down from 0.022).

### Tier 5b — two dedicated bgp+VRF campaigns: real progress, stalled aggregate

Two more full campaigns, each 6 events of combined bgp+VRF faults, pushed
`bgp_route_flap`'s own exam F1 steadily upward: **0.35 → 0.41 → 0.43**,
with no plateau in sight and, notably, `vrf_leakage` holding steady
rather than trading off against it this time (0.63 → 0.65 → 0.65).
**But** the single aggregate number the promotion gate actually judges
did not follow: **0.7094 → 0.7077** — the gap to the bar actually
widened slightly, and a live blind test of exactly this compound got
measurably worse (1/2 → 0/2 correctly classified). This mismatch —
real, per-class improvement not translating into aggregate improvement
— was the pre-agreed signal to stop adding volume and fix the features
instead.

### Tier 5c — baseline-relative (z-score) features: the actual breakthrough

We added the median/MAD-based z-score companion feature family described
in full in Chapter 2 and Chapter 7's Problem 8 — no new lab data, just a
smarter way of expressing every existing measurement. Two independent
retrains, same unchanged architecture:

| | Before Tier 5c | After Tier 5c |
| --- | ---: | ---: |
| Candidate macro-F1 | 0.7094 (best of prior rounds) | **0.7642** (promoted) / 0.7743 (dry-run) |
| Gate result | FAIL (2 rounds straight) | **PASS** |
| `bgp_route_flap` exam F1 | 0.43 | **0.48** |
| `vrf_leakage` exam F1 | 0.65 | **0.75** |
| Chronological (temporal, sticky) macro-F1 | — | **0.8233** raw / **0.8923** with advisory tier |
| Live BGP+VRF compound blind | 0/2 | **1/2 detected and correctly classified** |

Two full rounds of dedicated campaign volume had moved macro-F1 by
roughly **+0.015** total, combined. This single feature-engineering
change moved it by **+0.055 to +0.065** — at least three times as much,
using zero new lab hours. This is the single largest, most efficient
improvement in the entire project's history.

---

## Tier 5.5 — Testing whether a "smarter" architecture could do even better (it couldn't, honestly)

### The question

Separately from adding new features, we also tested whether giving the
model itself more internal "thinking" capacity — clustering, specialist
sub-models — could lift the rare classes further, without any new data
at all. Fully explained in Chapter 6; the honest scoreboard:

| Head | Exam Macro-F1 | Mean rare recall |
| --- | ---: | ---: |
| `plain` (the plain, unmodified booster) | **0.722** | 0.55 |
| `wm` (added clustering) | 0.719 | 0.52 |
| `moe` (mixture of specialist experts) | 0.658 | 0.53 |

### The honest conclusion

Neither extra-complexity option beat the simple, plain design on this
data — `moe` was clearly and measurably worse, a textbook case of
overfitting (Chapter 2) with too few real rare-class examples to support
that many extra adjustable parts. **The bottleneck was never how much
"thinking" the model was capable of — it was whether the classes were
separable in the feature space at all**, which is exactly the problem
Tier 5c's baseline-relative features later solved directly.

---

## Tier 6 — Scaling up the physical campaign itself (ongoing, as needed)

### The idea

Beyond smarter formulas (Tiers 1–3) and smarter features (Tier 5), the
most direct lever of all is simply: collect more real, physical fault
examples in the lab, so the rarer classes have a larger, statistically
sturdier support (Chapter 2) to be measured and learned from. Our fault
campaign tooling (`scripts/deca_fault_campaign.py`, Chapter 5) is
purpose-built to support this, with a simple `--per-type N` flag that
runs an exact, controlled quota of each fault type, resting a realistic
15–25 minutes of normal traffic between each injected event.

### Why this is treated as a "last resort," not a first move

A single round of a 10×4-fault Tier 6 campaign can take **many hours** of
real wall-clock lab time — a legitimate cost, especially compared to
Tier 5c's feature-engineering fix, which required zero new lab hours and
delivered a bigger single improvement than two entire rounds of dedicated
campaign volume combined. The project's actual, lived experience across
Tiers 5 and 5.5 is a genuinely important lesson worth restating plainly:
**smarter features beat more data, and smarter data beats a fancier
model, in that order, for this specific problem** — a lesson worth
carrying into any future work on this system.

---

## The whole ladder, at a glance

| Tier | What it changed | Cost | Biggest measured win |
| --- | --- | --- | --- |
| 1 | Split one hard decision into two easier ones (the gate) | Free (structural change only) | Rare recall 0.26 → 0.67 |
| 2 | Made rare-class mistakes cost more during training | Free | Supports Tier 1's gain, prevents rare classes being "cheap to ignore" |
| 3 | Deliberately tuned decision cutoffs instead of using defaults | Cheap (a grid search) | Macro-F1 0.716 → 0.721 |
| 4 | Refused to fabricate synthetic training rows (SMOTE) | A deliberate non-change | Protected the honesty of every other number in this table |
| 5 (parts 1–5b) | Built real, direct protocol features (`vrf_route_count`, `bgp_flap_count`); found and fixed two real data bugs along the way | Moderate (new exporters, several campaigns) | Fixed two silently-broken fault signals; macro-F1 climbed toward 0.71 |
| 5.5 | Tested deeper model architectures | Cheap (no new data, just retrains) | Honest negative result — confirmed data/features, not model capacity, was the bottleneck |
| 5c | Baseline-relative (z-score) feature family | Very cheap (pure feature engineering, zero new lab data) | Macro-F1 0.71 → **0.76+**, gate PASS, also unlocked portability (Chapter 10) |
| 6 | More raw campaign volume, as still needed | Expensive (many lab-hours per round) | Ongoing, used selectively where features alone aren't enough |

---

## Continue

Chapter 9 explains exactly *how* we know any of these numbers are
trustworthy in the first place — including a real detective story about
double-checking our own results using nothing but timestamps. Continue
to [Chapter 9 — Verification and Trust](09_verification_and_trust.md).
