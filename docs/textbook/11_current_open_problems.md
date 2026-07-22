# Chapter 11 — Current Open Problems

## Why this chapter exists

Every chapter so far has been honest about failures *along the way* to a
fix. This chapter is about the failures that are **still open right
now**, as of the writing of this book. A textbook that only describes
solved problems would be misleading about the current state of a project
that is still actively being worked on. Nothing in this chapter is a
secret — every item here is already documented somewhere in this
project's own working notes; this chapter simply gathers them all into
one honest, plain-English list.

---

## Problem A — Two faults overlapping at the exact same time is still genuinely hard

### The current state

Chapter 7 (Problem 5) and Chapter 9 described real progress on this: the
cross-host "echo" confusion was found and fixed, and an *isolated* VRF
leak test now detects cleanly (2 out of 2, both correctly classified).
But when a VRF leak happens **at the same time** as a loud `congestion_
breach` or `tunnel_degradation` fault on a different part of the network,
the VRF leg is still missed in most of our compound blind tests — this
specific gap is not yet closed.

### Why this is still open

The working theory (confirmed in Chapter 7, Problem 8) is that this used
to be a *feature* problem — absolute-scale traffic features simply
couldn't separate two things happening at once. The baseline-relative
z-score features (Tier 5c) have measurably helped the aggregate score and
helped at least one compound blind test go from a full miss to a correct
detection — but we have not yet run a full new round of compound blind
tests specifically re-checking every combination *after* this fix, so we
cannot honestly claim this specific gap is fully closed yet, only that it
has real reason to be smaller than it was.

### What would close this properly

A dedicated new round of compound blind tests (Chapter 9), specifically
re-run after the Tier 5c feature change, checking each pairing
(tunnel+VRF, congestion+VRF, bgp+VRF) again, with results compared
directly against the pre-fix numbers already on record.

---

## Problem B — Severity estimation is not trustworthy enough to ship yet

### What "severity" means here

Beyond just naming *which* fault is happening, DECA also attempts to
estimate roughly *how bad* it is (low/medium/high), by comparing live
packet loss, jitter, and throughput deviation against a healthy baseline.

### The current state

Our own internal results explicitly flag this with a direct warning:
*"do not ship — bucket agreement / Pearson weak across nights."* In plain
words, when we check whether DECA's severity estimate actually lines up
with what really happened, the agreement has been weak, and in at least
one measurement, the correlation was actually **negative** — meaning the
severity score was, if anything, pointing in the wrong direction on that
particular test.

### Why this is genuinely different from "the model is bad"

The main fault classifier (naming *which* fault) has been tested and
measured extensively and is demonstrably improving over time (Chapter
8). Severity estimation is a separate, additional feature bolted on top,
and it simply has not received anywhere near the same amount of
dedicated tuning and campaign-based evidence yet. It is explicitly called
out as unproven, rather than quietly presented alongside the
better-tested fault classification numbers as if it had the same level
of confidence behind it.

---

## Problem C — Cross-network portability is a real engineering claim, not yet an empirically proven one

### The current state

As explained in full in Chapter 10, we have built genuinely real
mechanisms that should make onboarding to a new network faster and
cheaper — externalized, editable configuration, and baseline-relative
features that don't depend on one specific network's absolute traffic
scale. But we have never actually run this procedure, end to end, against
a second real network. Every claim about portability today is a
reasoned engineering argument, not a proven, measured result.

### Why we say this proactively

The project's own portability documentation states this directly: *"We
have baseline-relative features and externalized config; we have not yet
run this procedure against a second real network. Say this distinction
explicitly if asked."* This chapter is doing exactly that — stating it
plainly here, rather than only in a document someone might not read.

### What would close this properly

Actually running a real (even small) calibration campaign against a
genuinely different network — ISRO's own, or any other real network
willing to participate — and directly measuring whether Tier A
(recalibration only) or Tier B (a lightweight retrain) is what's actually
needed there, and how much it helps.

---

## Problem D — `bgp_route_flap` remains the hardest of the four fault classes

### The current state

Even after a real, live-verified exporter fix (Chapter 7, Problems 7–8)
and multiple dedicated campaigns, `bgp_route_flap`'s own exam F1 score
(around 0.43–0.51 depending on the specific retrain and exam draw) is
still the lowest of the four fault classes, and it is the class most
frequently confused with a different fault under compound (simultaneous-
fault) conditions.

### Why this is still open, honestly

Two real, structural reasons, both already established earlier in this
book: this fault's telemetry signature is inherently spikier and more
short-lived than the other three (Chapter 3), which makes its raw
frame-level scores noisier by nature (this is also why a "faster onset"
tweak to its loom settings backfired badly, Chapter 6); and its dedicated
real exporter (`bgp_flap_count`) is still relatively new, meaning only a
partial fraction of this class's total historical training rows carry
the real signal — a large share of older rows still have the fabricated,
pre-fix signal baked in, or none at all.

### What would close this properly

Continued, gradual dilution of the older, legacy rows as newer campaigns
add more real `bgp_flap_count`-backed examples over time, plus continued
monitoring of whether this class's F1 keeps climbing as it has in every
recent round so far.

---

## Problem E — Small operational gaps that are known but not yet fixed

These are smaller, more mundane items, explicitly tracked in our own
working notes, that simply haven't been addressed yet:

- **The VRF recall campaign script has no automatic retry on a failed
  injection.** If a single fault injection silently fails partway
  through a longer automated campaign, the script does not currently
  detect this and retry it — a human currently has to notice and re-run
  it manually.
- **Occasional false alarms right after a real fault clears.** A small
  number of near-miss false alarms have specifically landed in the few
  minutes immediately following a real fault's clean recovery — a
  "bleed-over" pattern that is noted but not yet specifically
  investigated or fixed on its own.

---

## Problem F — The promotion gate has failed more times than it has passed, historically

### Why we are listing this as an "open problem" rather than hiding it

Across this project's history, several full retraining rounds — an
entire deeper-architecture experiment (Chapter 6's `moe`), two full
rounds of dedicated bgp+VRF campaign volume (Chapter 8), and at least one
compound-overlap retrain explicitly noted in our own records as
"promote FAIL — old model" — did **not** result in a newly promoted
model. Each of these was a genuinely useful, informative result (we
learned real things from every one of them, as told throughout Chapters
7 and 8), but it is worth being explicit that **most individual attempts
at improvement do not succeed on the very first try**, and that this is
the normal, expected texture of this kind of iterative engineering work,
not a sign that something is broken.

### Why this is actually a sign of health, not weakness

A project whose promotion gate always says "yes" to every single new
attempt would be far more worrying than one that says "no" most of the
time and "yes" only when a change has genuinely, honestly earned it
(Chapter 6). The fact that this project has a real, documented, sometimes
frustrating record of failed promotion attempts is direct evidence that
the promotion gate is doing its actual job.

---

## The honest summary of this chapter

DECA today reliably detects the four fault classes it was built for on
its own lab, is measurably calm on healthy traffic (Chapter 9), and has a
real, working plan for onboarding a new network (Chapter 10) — but it has
not yet been proven on a second real network, its severity estimates are
explicitly not trustworthy enough to use yet, its ability to catch two
faults happening at exactly the same time still has a real, measured
gap, and one of its four fault classes remains meaningfully harder than
the other three. None of these are secrets. Every one of them is written
down, in this project's own working files, in the same plain language
used here.

---

## Continue

Chapter 12, the final chapter, gathers every numeric result quoted
anywhere in this book into one single place, for quick reference.
Continue to
[Chapter 12 — Appendix: Every Results Table](12_appendix_results_tables.md).
