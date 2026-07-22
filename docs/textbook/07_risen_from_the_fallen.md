# Chapter 7 — Risen from the Fallen

## What this chapter is

This is the honest story of everything that went wrong while building
DECA, told in the order it actually happened, with the real numbers from
our own logs and result files. A shorter version of this story already
exists as its own standalone document,
[`docs/RISEN_FROM_THE_FALLEN.md`](../RISEN_FROM_THE_FALLEN.md) — written
for a judge who wants the whole thing in about one page. This chapter is
the expanded, textbook version of that same story: every one of the same
eight problems, but with the specific numbers, the specific files, and
the specific reasoning behind each fix filled back in.

We are telling this story on purpose, not despite it being embarrassing.
A system that hides its own history of mistakes is much harder to trust
than one that shows you exactly how it found and fixed them — and, as you
will see, the process of finding and fixing these problems is *itself*
most of what actually makes DECA good today.

---

## Problem 1 — The model cried wolf too much

### What happened

Very early in testing DECA on live, continuous telemetry (not just
pre-recorded training data, but a real, ongoing stream), we ran a
one-hour "control" test — a period where the network stayed completely
healthy the entire time, with zero real faults injected. A perfectly
behaved system should raise **zero** alarms during this hour. Instead,
our very first version raised **21 false alarms in that single hour**
(`control_20260716_1924_60m` in our records) — roughly one false alarm
every three minutes.

### Why this matters more than it might seem

**Real-life comparison:** this is exactly the "boy who cried wolf"
problem from the old fable. A fire alarm that goes off constantly, even
when there's no fire, doesn't make a building safer — it makes people
stop trusting it, and eventually stop reacting to it at all, including
on the one day it's actually right. A network operations team that gets
paged 21 times an hour for nothing would very quickly either mute DECA
entirely or ignore its alerts on reflex — which would make it worse than
having no system at all, because it would create a false sense that "the
network is being watched" when, in practice, nobody is actually listening
anymore.

### The investigation

We traced these false alarms and found that a large share of them —
**18 out of 21** — were specifically the model wrongly declaring
`bgp_route_flap`, even though no real BGP fault was happening at all.
This was an early clue (later confirmed much more thoroughly in Problem 6
below) that something was specifically wrong with how DECA was reading
BGP-related signals, not just a general noise problem.

### The fix

We built what we internally call a "densify + evidence gate" for BGP
specifically: since real BGP flap evidence only exists as a stamped
signal at the exact moment a real flap-inducing command runs (rather
than a continuously scraped measurement, at the time), the operator was
taught to treat long stretches with **no** stamped evidence as a
genuine, confident **zero** — rather than letting small amounts of
missing or sparse data get quietly filled in with something that looked
like a signal. In plain words: teach the system "no news is actually no
news," instead of letting a gap in the data accidentally look like
suspicious activity.

### The result

A later control run under similar conditions,
`control_20260718_0848_60m`, came back completely clean: **0 false
alarms in a full 60-minute healthy run.** Multiple later control runs
(`control_after_vrf_20260718_2142`, `control_echo_20260719_1027_30m`)
confirmed this held steady, not as a one-off lucky result.

---

## Problem 2 — It couldn't tell a "close call" from a real fault

### What happened

We deliberately tested DECA with fake "near-misses" — brief blips
deliberately engineered to look like the very beginning of a real fault,
but that are designed to abort and fade away before anything actually
breaks (recall `precursor_aborted` from Chapter 5). DECA's early version
kept treating these harmless blips as real, full faults.

**Real-life comparison:** like a smoke detector that goes off every
single time you make toast, because toast also produces a small amount
of smoke — technically true that *some* smoke is present, but not
remotely the same emergency as an actual kitchen fire, and treating them
identically trains everyone in the house to ignore the alarm.

### The fix

Two things had to happen together: first, we specifically taught DECA's
training data that these aborted near-misses should be labeled
`healthy`, not any fault type (this is exactly what
`label_circumstance_existence` and the `HEALTHY_ALIASES` mapping do,
described in Chapter 5). Second, we tightened the "patience" settings on
DECA's temporal loom (Chapter 6) — specifically requiring a longer,
more consistent streak of matching evidence (`enter_k`, soft-streak
cumulative confidence thresholds) before officially declaring a fault,
so a brief, quickly-fading blip doesn't have enough time to accumulate
enough evidence to trigger a false alarm.

---

## Problem 3 — Fixing #1 and #2 came at a real cost: it got a little too cautious

### What happened

Once DECA was taught to stay calm during fake-outs and healthy periods,
it also, honestly, became slightly less sensitive to some real faults.
One measured live blind test, `blind_20260718_0848_60m`, caught 3 out of
4 real fault events, missing one genuine PE2 `vrf_leakage` event it had
caught before the calming fixes above were applied.

### Why this is not a bug, but a real, normal trade-off

**Real-life comparison:** imagine tightening the mesh on a fishing net so
it stops accidentally catching seaweed and driftwood (the false alarms).
A tighter net does successfully catch less junk — but a net tightened
*too* far can also occasionally let a genuinely small, real fish slip
through that a looser net would have caught. This tension between
"catch every real fault" (recall) and "don't cry wolf" (precision) is a
fundamental, well-known tension in this kind of system (explained fully
in Chapter 2's discussion of precision and recall) — it is not something
you can ever fully "solve" away to zero on both sides at once; you can
only find the best available balance and be honest about exactly where
that balance currently sits.

### The response

Rather than just accepting a permanent loss on this one class, we ran a
dedicated data-collection campaign specifically aimed at improving VRF
recall — `deca_vrf_recall_campaign.py` — and re-tested afterward. The
very next comparable blind test, `blind_20260718_2219_60m`, caught
**4 out of 4** real events, **100%** correctly classified on first
declaration. We also specifically re-ran the earlier specificity checks
(Problems 1 and 2's trust bar) afterward to make sure fixing recall
hadn't quietly reopened the cry-wolf problem — it hadn't
(`specificity_exam_v1_20260718_2107` and `_v2_20260718_2142` both still
PASS).

---

## Problem 4 — Three fault types kept getting confused with each other

### What happened

`tunnel_degradation`, `vrf_leakage`, and `congestion_breach` can look
genuinely similar to the model in their first few moments — all three
can start with a modest rise in loss or jitter before their individual
character becomes clearer. Several early blind tests show this
confusion directly: for example, in `blind_compound_bgp_recheck_
20260719_1516_40m`, a real BGP flap was, for a while, declared as
`tunnel_degradation` instead.

**Real-life comparison:** like three different illnesses that all start
with the exact same early symptom — a mild fever — making it genuinely
hard for a doctor to tell them apart in the first hour, even though
they're clearly different diseases by the second day.

### The fix

This is answered partly by the two-tier loom design (Chapter 6): DECA is
allowed to be tentative and even wrong in its early "advisory" guesses,
while the slower, more patient "confirmed" tier waits for the pattern to
become clearer before committing to a specific name. The scorecard used
to grade these tests deliberately tracks both "was the *first* call
correct" and "did the system *eventually* self-correct to the right
answer" (`class_accuracy` versus `class_accuracy_eventually`) — precisely
because "wrong at first, then self-corrected" is a meaningfully different
(and much less serious) outcome than "wrong the entire time."

---

## Problem 5 — When two faults happened at the same time, the quieter one got drowned out

### What happened

When we deliberately ran "compound" tests — two different real faults
happening at the same time on the network — a consistent pattern
emerged: a loud, obvious fault (like `tunnel_degradation` or
`congestion_breach`) tended to hijack the model's attention, while a
quieter, simultaneous `vrf_leakage` event on a different part of the
network went completely undetected. Across the compound test series
(`blind_compound_tunnel_degradation_20260719_1317_40m`,
`blind_compound_congestion_breach_20260719_1256_40m`, and others), the
VRF leg was specifically missed in most of these overlapping runs, even
though an *isolated* VRF test on its own (`blind_vrf_isolated_
20260719_1333_45m`) caught it cleanly, 2 out of 2.

**Real-life comparison:** like trying to hear someone whispering a
question right next to a running jackhammer — the whisper is real and
technically audible in isolation, but gets completely masked the moment
a much louder sound happens at the same time, in the same place, at the
same moment.

### Two genuinely different causes found along the way

During this investigation, we also found a related but distinct problem:
some of what looked like "confusion" was actually **cross-host echo** —
`station2` (playing the receiving end of `station1`'s traffic) was
seeing the real physical *side effects* of a `station1` fault in its own
received-path measurements, and wrongly declaring that as its own,
separate, independently-originating fault. This was fixed with an
"origin-lock" rule: `station2` is not allowed to *confirm* certain fault
classes on its own, since those specific classes are only physically
possible to originate on `station1` in our topology. A dedicated proof
test, `blind_echo_20260719_1102_45m`, confirmed this fix directly: **0**
false alarms from echo, with detection still holding at 3 out of 3 real
events.

### Where this stands

The deeper "loud fault drowns out quiet fault when both happen
simultaneously" problem is the direct motivation for the entire "Tier 5"
protocol-feature effort described in Chapter 8 and in Problems 6–8
below — the working theory, later confirmed, was that ordinary traffic-
shape features (octets, jitter, loss) simply cannot reliably separate two
faults that are *both* nudging those same few numbers at once, and that
the fix has to be a genuinely new, orthogonal kind of signal (like a
direct route count or a direct BGP counter) that only reacts to its own
specific fault, regardless of what else is happening on the network at
the same time.

---

## Problem 6 — A silent data bug meant the "VRF leak" training data wasn't real for a long time

### What happened

This is the single most important bug found in the entire project. Our
fault-injection script for `vrf_leakage` was written to target a VRF
named `ADMIN`. The real VRF configured on our actual routers was named
`vrf-admin` (different capitalization, different punctuation). Because
of this exact mismatch, **every single "VRF leak" fault our lab had ever
generated, for a long time, was a complete no-op at the actual network
level** — no route ever actually leaked anywhere. FRR simply reported
"VRF ADMIN not found" and did nothing.

### Why this went unnoticed for so long

The fault injector also added a secondary, deliberate `netem` traffic
ramp alongside the (broken) VRF leak attempt — originally added because
a "pure" leak, on its own, produces a genuinely subtle telemetry
signature (Chapter 3). Because of this secondary ramp, DECA's training
data for `vrf_leakage` still had *some* recognizable shape to learn from
— just not the shape of an actual leak. It was learning to recognize the
side effect of a fake fault, not the real fault itself, and there was no
obvious symptom (like an error message visibly crashing the pipeline) to
draw attention to the mistake.

### How it was found

While wiring up a brand-new, direct detection feature for this exact
fault (`vrf_route_count` — explained fully in `docs/TIER5_VRF_ROUTE_COUNT.md`
and in Chapter 5), we needed to manually verify, step by step, that
injecting a leak actually caused the route count to rise. It didn't. That
forced a direct investigation into exactly what the injector script was
doing versus what actually existed on the router — and the VRF name
mismatch was found immediately once we looked closely with `vtysh`
directly on the router.

### The fix, and the verification

We corrected `inject_vrf_leakage()` and the matching `clear_all_faults()`
cleanup function (in `scripts/deca_fault_campaign.py`) to target the
real `vrf-admin` name. We also had to write a small, one-off cleanup
script (`scripts/deca_vrf_cleanup_admin_stub.py`) to remove a leftover,
orphaned, incorrectly-targeted BGP configuration stanza that had been
silently accumulating on `station2` from the old, broken injector. After
the fix, we specifically re-verified, live, that a real leak now actually
happens: the BGP route count inside `vrf-admin`'s table went from **0 to
4** the instant we injected the corrected leak, and back down from **4
to 0** the instant we reverted it — a clean, direct, unambiguous
before/after proof, not just a hopeful assumption that the fix worked.

### What this teaches

A model can appear to be learning something specific and can even show
improving scores over time, while silently learning from the wrong
underlying reality the whole time, if nobody directly verifies that the
*cause* being simulated is actually happening at the level the model is
supposed to be learning from. "The score went up" is not, by itself,
proof that the thing you think you're teaching is the thing that's
actually being taught — you have to go and check the ground truth
directly, the way we eventually did here with `vtysh`.

---

## Problem 7 — Throwing more training data at the weak spots stopped working

### What happened

After fixing Problem 6, the very next obvious move was: generate more
labeled examples of the fault classes DECA was still weakest on —
`vrf_leakage` first, then `bgp_route_flap`. This is a completely
reasonable, standard first response to a rare-class problem, and it did
work, for a while: a dedicated campaign weighted toward VRF-related
compound faults (`tier5_vrf_overlap_20260720_0252`) raised `vrf_leakage`
exam F1 from 0.47 to 0.59. But it came with a cost: `bgp_route_flap`'s
own F1 *dropped* at the same time, from 0.51 to 0.45.

We then tried the opposite approach — a deliberate follow-up campaign
(`tier5_vrf_consolidate_20260720_1418`) that scheduled **zero** new
bgp+VRF compound events at all, specifically hypothesizing that the BGP
dip was simply a "dilution by volume" side effect that avoiding new
bgp+VRF training rows would let recover naturally. It didn't:
`vrf_leakage` kept climbing (0.59 → 0.63), but `bgp_route_flap` **kept
dropping anyway** (0.45 → 0.35), even though we had deliberately stopped
adding any new BGP-related training data that round.

### Why this was a genuinely useful, if frustrating, result

**Real-life comparison:** like squeezing one side of a balloon and
watching a different side bulge out no matter how carefully you try to
avoid touching it — a strong hint that the real problem isn't simply
"not enough air on that one side," but something structural about the
balloon itself.

This result — BGP dropping *even when we deliberately avoided adding any
new BGP training volume* — was the single most important clue that led
directly to Problem 8's diagnosis: whatever was actually capping BGP's
performance, it clearly was **not** simply a matter of how much data was
in the training schedule.

### The direct diagnosis

We built a dedicated diagnostic tool, `scripts/deca_bgp_diagnose.py`,
specifically to look past the aggregate score and directly instrument
the anomaly gate's behavior class by class. The result was unambiguous:
of 539 true `bgp_route_flap` exam rows, **288 of them (53%) were being
silently predicted `healthy` by the gate itself** — the very first
stage, before the multiclass head even got a chance to weigh in. Only 30
were being confused with a *different* fault class. This proved the
failure was a **gate miss**, not head confusion — the earliest possible
point of failure in the whole two-stage pipeline (Chapter 6).

Tracing this one level deeper into the actual injector code
(`inject_bgp_route_flap()`), we found the real root cause: this
particular fault's simulation relied entirely on a single scalar number
that was being manually written directly into a CSV file
(`stamp_bgp_update_pulse()`) — not a real, continuously scraped
measurement — and, unlike every other fault, it had **no accompanying
real traffic disturbance at all**. `tunnel_degradation` and
`congestion_breach` both directly manipulate real traffic shaping tools
(`netem`, `tbf`); even `vrf_leakage` had been given a deliberate,
supporting `netem` ramp specifically because a "pure" leak alone left too
little telemetry shape. `bgp_route_flap` alone had no such support at
all. In short: part of the "signal" the model was supposed to be
learning from wasn't a real measurement — it never was.

### The fix (which leads directly into the next section)

We confirmed, live and directly through `vtysh`, that FRR does have a
real, genuine, monotonically increasing counter that reflects real BGP
route-refresh activity: `messageStats.routeRefreshSent` and
`routeRefreshRecv` (on `show bgp neighbor 10.1.3.1 json`). This became
the foundation of the fix described in Problem 8 and in Chapter 8's
detailed "Tier 5b" history.

---

## Problem 8 — The real root cause: the model was measuring things in absolute numbers, not "normal for this network"

### The turning point

After building a real, live `bgp_flap_count` exporter (fixing the
fabricated-signal problem from Problem 7) and running two dedicated
follow-up data campaigns, we hit a genuinely puzzling result: per-class
F1 for `bgp_route_flap` kept climbing steadily round after round (0.35 →
0.41 → 0.43), and `vrf_leakage` held steady rather than trading off
against it — yet the single number the promotion gate actually judges,
aggregate macro-F1, **did not move toward the required bar at all**
across either round (0.7094 → 0.7077 — the gap to the bar actually
*widened* slightly). At the same time, a live blind test of exactly the
compound this campaign was targeting got measurably *worse*, not better
(1 out of 2 correctly classified, down to 0 out of 2).

This mismatch — real, per-class improvement that somehow wasn't
translating into overall improvement, plus a live regression on exactly
the case being targeted — was the pre-agreed signal to stop adding more
training volume and instead fix something structural about the features
themselves.

### The actual fix

We went back to `engineer_features()` (the core feature-building function
in `scripts/rebuild_unified.py`, described fully in Chapter 2 and
Chapter 5) and added an entirely new family of features, built on top of
every existing metric, without collecting a single new row of lab data:
for every metric, within every individual network run, compute a robust
median and MAD (Chapter 2's "robust statistics" — deliberately chosen
over an ordinary mean and standard deviation, specifically so that the
small number of genuine fault rows mixed into that run's own data
wouldn't distort the estimate of what's "normal" for that run). Then
compute the exact same four feature types (slope, rolling mean, rolling
standard deviation, acceleration) on the resulting **z-score** — "how
many typical spreads above or below this specific network's own normal
is this reading right now" — instead of only on the raw absolute value.
This doubled the feature count from 56 to 112.

### The result

We ran two independent retrains on this new feature set, on two
different random exam draws, with the model's underlying architecture
completely unchanged (still `plain`, the same booster as always):

| Retrain | Result |
| --- | --- |
| Dry run (no promotion) | Macro-F1 **0.7743**, `bgp_route_flap` F1 **0.51**, `vrf_leakage` F1 **0.76** |
| Promotion run | `wm` head narrowly won the tiebreak at **0.7642** (`plain` scored 0.7637 on the same paper — a statistically insignificant 0.0005 difference); `bgp_route_flap` F1 **0.48**, `vrf_leakage` F1 **0.75** |

The gate, which had failed for two consecutive rounds straight, **passed
immediately** — and by a wide margin, not a narrow squeak. Two entire
rounds of dedicated bgp+VRF campaign volume, combined, had moved macro-F1
by roughly **+0.015** total. This single feature change, using data that
already existed, moved it by **+0.055 to +0.065** — at least three times
as much, from a change that required zero new lab hours.

We also specifically re-checked the live compound blind test that had
just gotten worse in the previous round: the very next comparable
BGP+VRF compound test came back detected **and correctly classified** —
the exact cross-class confusion (mislabeling `vrf_leakage` as
`bgp_route_flap` when both happened together) that had shown up in the
volume-only rounds was gone, without needing any hand-built interaction
feature between the two specific metrics.

### Why this is the single most important lesson of the whole project

This result directly confirmed the earlier "balloon-squeezing" puzzle
from Problem 7: the two rare classes were separable in **volume** terms
all along (more real examples reliably nudged their individual F1 up)
but were not separable in **feature** terms — an absolute-scale feature
like "traffic is at 80 megabits per second" carries very different
meaning depending on which network, which link, and which time of day
you're looking at, and no amount of additional training rows can fully
compensate for a feature that fundamentally can't express the concept
"unusual for *this specific* context." Once the features could express
that concept directly (a z-score, by construction, always means the same
thing — "unusually far from this context's own normal" — no matter what
network it's computed on), both weak classes improved together, for the
first time, instead of trading off against each other.

### The unplanned bonus: this is also what makes DECA portable

This same fix, built purely to solve an accuracy problem, turned out to
be exactly the change that makes DECA realistically capable of moving to
a different network without a full retrain — because "3 MAD above this
network's own normal" is a statement that means the same thing on any
network, while "above 80 megabits per second" is a statement that is
specific and meaningless on a network with a very different traffic
scale. This connection — one engineering fix solving two separate
problems (accuracy *and* portability) at once — is explored in full in
Chapter 10.

---

## In one sentence, for a judge

The model went from *"raises too many false alarms and gets confused
between similar or simultaneous faults, partly because some of its own
training data for two of its four faults was quietly broken or
fabricated"* → to *"reliably quiet when genuinely healthy, correctly
detects real faults including when two happen at once, and — because of
how the final fix actually works — is now portable, in principle, to a
network it has never seen before."*

---

## Continue

Chapter 8 takes this same story and re-tells it as a structured,
chronological ledger of every measurable improvement, tier by tier, with
every number gathered in one place for reference. Continue to
[Chapter 8 — Tier by Tier History](08_tier_by_tier_history.md).
