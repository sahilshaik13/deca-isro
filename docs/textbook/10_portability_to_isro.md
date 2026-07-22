# Chapter 10 — Portability to ISRO

## The honest starting question

Can we just copy DECA, as it currently exists, directly onto ISRO's real
network and expect it to immediately work correctly? The honest answer,
stated plainly and up front, is **no** — and saying so directly, rather
than overselling the system, is itself part of what makes the rest of
this chapter's claims trustworthy. DECA's specific trained model (the
actual XGBoost trees, Chapter 6) is fitted to our lab's own specific
traffic scale and its own specific hardware quirks. Dropping those exact
trained weights onto a different, larger, real network, unmodified, would
almost certainly perform worse than on our own lab.

What *is* true, and genuinely defensible, is narrower — but still
meaningfully valuable: several specific parts of DECA transfer to a new
network far more easily than a full model would, and one specific, real
engineering decision (described in Chapter 7 and Chapter 8) has already
made that transfer meaningfully easier than it used to be.

---

## What actually transfers (and why)

### 1. The fault taxonomy itself — the four categories, not the specific numbers

`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, and
`vrf_leakage` (Chapter 3) are not categories we invented specifically for
our small lab. They are the standard, textbook failure categories for
*any* network built using the same protocol family — BGP peering, VRF
segmentation, and encrypted tunnels are the standard building blocks of
essentially any carrier-grade, multi-site private network. If ISRO's own
backbone or ground-segment network uses this same protocol family — which
is very likely, since these are the standard tools for exactly this kind
of multi-site network — then the underlying *physics* of what each fault
actually looks like in real telemetry (Chapter 3's "fingerprints")
carries over conceptually, even before any retraining happens on their
specific data.

### 2. The decision logic is a plain text file, not buried code

As explained in Chapter 6, every one of DECA's tunable decision
settings — the gate's cutoff, each fault's individual cutoff, the loom's
patience settings — lives in one single, human-readable JSON file
(`decision_thresholds.json`), not hidden inside program logic. The
concrete, demoable claim this supports: point DECA's monitoring queries
at a new network's own telemetry endpoints, then recalibrate roughly
eight specific numbers against a short, real, labeled sample from that
network. That is a calibration pass, not a from-scratch rebuild.

### 3. DECA's sense of "healthy" already spans more than one network

Recall from Chapter 5 that DECA's training data deliberately blends real
lab telemetry with genuinely public internet data (from sources like
RIPE Atlas and a Cisco network sandbox) — all labeled `healthy`, from
networks we have never touched ourselves. This means DECA's underlying
notion of "what does normal traffic look like" is not narrowly fit to
just our one small lab's specific quirks — it already has some exposure
to what "normal" looks like on genuinely different real-world networks.

### 4. The tooling to onboard a new network already exists and is fast

`scripts/deca_fault_campaign.py --per-type N` (Chapter 5) is a real,
already-tested, working tool that runs a controlled, quota-driven
campaign of real fault injections. Demonstrating this tool running on
our own lab genuinely *is* a live demonstration of exactly the procedure
ISRO would run on their own network — the tooling to run a calibration
campaign already exists today and takes hours, not weeks.

### 5. Features are now relative to "normal for this network," not fixed numbers

This is the single most important item on this list, and it is the
direct, deliberate outcome of the baseline-relative (z-score) feature
work described in full in Chapter 7 (Problem 8) and Chapter 8 (Tier 5c).
Because DECA's features can now express "how many typical spreads above
this specific network's own normal" instead of only "above 80 megabits
per second," the model's learned decision boundaries are expressed in
relative terms that mean roughly the same thing on any network — not
tied to our lab's own specific absolute traffic scale. This was not just
a theoretical claim; it was directly validated, on our own data,
immediately after being built (Chapter 8's Tier 5c numbers).

---

## What does NOT transfer yet — said proactively, because it's stronger than hiding it

A pitch that only lists what works, and quietly avoids what doesn't, is
weaker and less credible than one that states its own limits directly.
These are the specific, honest gaps as they stand today:

- **The specific trained model weights are lab-specific today.** Expect
  degraded accuracy on ISRO's raw telemetry until recalibrated — though
  the baseline-relative features above should meaningfully narrow this
  gap compared to before that fix existed, since the model's decision
  boundaries are now expressed in relative rather than absolute terms.
- **No live ISRO data exists yet, and none is assumed.** The calibration
  campaign described below is specifically the mechanism meant to close
  this gap, on ISRO's own network, under their own permissions, on their
  own schedule — it is not something that can be faked using public data
  as a substitute.
- **Cross-network transfer is currently an engineering *claim*, not yet
  an empirically *proven* one.** We have built baseline-relative
  features and externalized configuration, and we believe both should
  genuinely help — but we have not yet actually run this exact procedure
  against a second real network to directly prove it. This distinction
  — "the tooling and mechanism exist and are fast" versus "we've already
  proven it works on a second network" — should be stated explicitly if
  asked, rather than blurred.

---

## The two-tier onboarding plan

We designed onboarding to a new network as two tiers, ordered from
cheapest to most expensive, trying the cheaper option first.

### Tier A — Threshold-only recalibration (fastest, no retraining at all)

**When this is enough:** if the general *shape* of ISRO's fault
signatures is similar to ours, and the main difference is simply scale
(a different baseline traffic volume, different absolute jitter/loss
numbers) — meaning the model's basic learned patterns are approximately
right, just calibrated to the wrong starting point.

**How it works:** `scripts/deca_recalibrate.py` (Chapter 2's
"recalibration," as distinct from full retraining) loads the already-
trained gate and multiclass head exactly as they are — not one single
tree is refit — and simply re-runs the existing threshold-tuning search
(Chapter 6's Tier 3 process) against a labeled sample from the new
network. It defaults to a safe "dry run" that only *prints* what would
change, touching no files at all, unless you explicitly pass `--apply`.

```bash
# Demo mode: proves the mechanism works, using our own lab's data
python scripts/deca_recalibrate.py

# Real onboarding: point at the new network's own labeled sample
python scripts/deca_recalibrate.py --sample-parquet path/to/isro_sample.parquet --apply
```

**An honest note about testing this tool on our own data:** when we
demo this tool using a sample drawn from the *same* lake the model was
already tuned against, the reported change is exactly zero — which is
the *correct*, expected result in that specific case, not a bug. It
proves the mechanism runs end-to-end and produces a genuine, real
before/after score — it does not prove recalibration always does
nothing. A genuinely different network's real sample would be expected
to show a real, nonzero shift.

### Tier B — A lightweight retrain (only if Tier A genuinely isn't enough)

**When needed:** if ISRO's fault physics is different enough — a
different topology depth, a genuinely different tunnel or VRF
implementation — that the underlying tree structure itself, not just the
decision cutoffs, needs to adapt.

**How it works:** exactly the same pipeline used throughout this entire
project (Chapter 5 and Chapter 6) — fold the new labeled sample into the
feature lake, then retrain and let the promotion gate judge the result:

```bash
python scripts/rebuild_unified.py          # fold ISRO's labeled sample into the lake
python scripts/deca_school_exam_train.py --auto-promote   # retrain + threshold sweep + gate
```

Crucially, our own lab data is deliberately **kept in the lake** during
this process, as a prior — this is a form of transfer learning by
pooling data together, rather than starting completely from scratch.
ISRO's own sample does not need to be large enough to train an entire
model by itself; it only needs to be large enough to nudge the decision
boundary meaningfully toward their network's own specific signature.

---

## The calibration campaign — the actual, concrete procedure

This is the specific runbook, detailed fully in
[`docs/CALIBRATION_CAMPAIGN_SPEC.md`](../CALIBRATION_CAMPAIGN_SPEC.md),
that describes exactly what ISRO would need to run on their own side.

### Step 1 — Generate a short, labeled sample (this is the one part only ISRO can do)

```bash
python scripts/deca_fault_campaign.py \
  --run-id "isro_calibration_$(date -u +%Y%m%d_%H%M)" \
  --per-type 3
```

`--per-type 3` means 3 injections of each of the 4 fault classes — 12
events total. Based on our own campaign logs (roughly 8 minutes of fault
plus 20 minutes of rest per event), this is estimated to take about
**5 to 6 hours**, comfortably run overnight or during a single scheduled
maintenance window — not weeks.

This step genuinely requires ISRO's own access and their own explicit
permission to run controlled fault-injection-style commands (traffic
shaping, BGP soft-clears, deliberate VRF misconfiguration) on their own
infrastructure. This is explicitly a permissions and access conversation
with ISRO, not something we can substitute or fake from our side.

### If live fault injection isn't permitted on production hardware at all

There's a deliberate fallback: a **passive-only** calibration —
collecting only a healthy-traffic sample (with zero injected faults),
long enough to recalibrate the anomaly gate's own sense of "healthy" for
that specific network. This is weaker (the fault-classification side
would stay at our lab-trained defaults until real fault-labeled data
becomes available later), but it requires zero fault injection at all on
their live network, which may be the only realistic option depending on
their operational constraints.

### Step 2 — Fold the sample into the lake, and recalibrate or retrain

```bash
python scripts/rebuild_unified.py --rpi-run isro_calibration_<timestamp>
python scripts/deca_recalibrate.py --sample-parquet ... --apply   # Tier A first
# or, if Tier A isn't sufficient:
python scripts/deca_school_exam_train.py --auto-promote           # Tier B
```

---

## What we can already demonstrate today, without needing ISRO's network at all

Everything up to the point of "now point it at ISRO's real telemetry" is
fully demoable right now, live, on our own lab, as a realistic stand-in
for the real procedure:

1. Run a small, `--per-type 2` mini calibration campaign live, narrating
   it as "this is the exact procedure ISRO would run on their own
   network."
2. Show `rebuild_unified.py` folding that new run directly into the
   existing data lake.
3. Show a real before/after diff of `decision_thresholds.json` from a
   retrain — concrete, visible proof that onboarding changes roughly
   eight JSON values, not that it requires building a brand-new model
   from nothing.
4. Show the public-data healthy-baseline blend (rows explicitly tagged
   `source=public`) inside the unified dataset, as direct evidence that
   the model's sense of "healthy" is not narrowly overfit to only our own
   lab's traffic pattern.

---

## The single-sentence pitch

*"Four protocol-standard fault classes, a config-driven decision layer
already externalized in a plain JSON file, and a tested campaign tool
that recalibrates it in hours — that's what's genuinely inheritable. The
specific trained weights are a useful starting prior to build from, not
the actual deliverable."*

---

## Continue

Chapter 11 gives the same kind of direct honesty to DECA's *current*
state — a plain list of what still isn't perfect today, without
softening or hiding any of it. Continue to
[Chapter 11 — Current Open Problems](11_current_open_problems.md).
