# Chapter 9 — Verification and Trust

## Why an entire chapter about "checking our own work"

Any project can print an impressive-looking number. The much harder, and
much more important, question is: *how do we know that number is telling
the truth?* This chapter is about the specific tools and habits we built
to make sure DECA's reported results are actually trustworthy — including
a real story about a moment where we almost convinced ourselves something
was broken, purely because of a timezone mix-up, before catching the
mistake in our own checking process.

---

## Level 1 — Testing on data the model never saw (the "exam")

The most basic form of honesty in this whole project is described fully
in Chapter 2: DECA is never scored on data it was trained on. Every
single number in this book came from a held-back "exam" — data the model
never got to study — and the "promotion gate" (Chapter 6) specifically
requires a new model to beat the old one on a shared, fair exam before it
is allowed to go live. This is the foundation everything else in this
chapter builds on top of.

---

## Level 2 — Testing live, on a real, unscripted network (the "blind test")

An exam score, by itself, only proves the model is good at recognizing
patterns in a table of already-recorded numbers. It doesn't prove the
model actually works *live*, on a real, ongoing network, reacting to
events as they happen — which is the actual job DECA needs to do in the
real world. For that, we built a completely separate testing harness,
the **adversarial blind test**.

### How a blind test actually works

A blind test has three separate, deliberately isolated pieces, each of
which is not allowed to see what the other two are doing:

1. **The adversary** (`deca_blind_chaos.py`) — randomly decides when and
   what kind of fault (or harmless near-miss) to inject into the real
   lab network, on a schedule that no one, including the model, knows in
   advance. It writes down the true, real answer key
   (`ground_truth.sealed.jsonl`) — but this file is **sealed**, meaning
   the model is never allowed to look at it.
2. **The operator** (`deca_live_operator.py`) — this is DECA itself,
   running live, watching only the real Prometheus telemetry (Chapter
   4), with absolutely no access to the sealed answer key. It writes its
   own running log of everything it declares, moment by moment
   (`declarations.jsonl`).
3. **The judge** (`deca_blind_scorecard.py`) — only after the test is
   completely finished does this script open the sealed answer key and
   compare it against what the model actually declared, producing an
   honest scorecard.

**Real-life comparison:** this is exactly how a fair magic trick or a
fair science experiment works — the person being tested must never see
the answer key while the test is running, and the person grading the
test must not be the same person who ran it, or there's a real risk
(even an accidental, well-meaning one) of the test quietly becoming
unfair.

### What gets measured

For every real event the network creates, the blind test scorecard
checks several genuinely different things at once:

| What's measured | The plain-English question |
| --- | --- |
| Detection | Did DECA notice *something* was wrong at all? |
| Class accuracy (first call) | Was DECA's *very first* guess at the specific fault type correct? |
| Class accuracy (eventual) | Did DECA *eventually* correct itself to the right answer, even if its first guess was wrong? |
| Confirmed lead time | How much advance warning did the confirmed alarm give before the fault fully "broke"? |
| False alarms | Did DECA raise an alarm during a harmless near-miss, or during a genuinely calm period? |

### Judging the judge

We take this seriously enough that the judge itself has its own built-in
self-test (`--selfcheck`): a synthetic, hand-built scenario with a known,
hand-computed correct answer (one clean hit, one "eventually correct"
recovery, one miss, one false alarm on a near-miss, one spurious false
alarm) — and the judge must correctly reproduce every single one of
those known answers before we trust its grading logic on a real run.

**Why bother self-testing the grader itself?** Because a broken judge
could quietly hand out a flattering grade to a broken model, and no one
would notice unless the judge's own logic was independently verified
first. This is the same principle as a school double-checking that its
own grading rubric produces the expected score on a sample answer sheet,
before trusting it to grade real student exams.

### One night is noise — you need a range, not one number

A single one-hour blind test only samples a small handful of random
events — maybe 4 or 5. Just like flipping a coin 5 times can easily give
you 4 heads by pure chance, one blind test's specific score can swing a
fair amount purely due to which random events happened to occur that
particular night. `deca_blind_aggregate.py` is a dedicated tool that
pools several separate nights' worth of graded runs together and reports
a proper range (mean, spread, minimum, maximum) — the project's own rule
is to never quote a single blind-test number to a judge without first
checking whether it holds up across multiple nights.

---

## Level 3 — A dedicated test just for "does it cry wolf?" (the specificity exam)

Blind tests measure detection — did DECA catch the real faults. But a
separate, equally important question is: how calm is DECA when *nothing*
is actually wrong? Mixing that question into the same randomly-scheduled
blind test made past false alarms hard to pin down and hard to
consistently re-test, since the timing was different every single night.

### The fix: a fixed, repeatable script

We built a **deterministic specificity exam** — a fixed, human-written
timeline of calm periods and deliberate near-misses, always in the same
order, for the same durations, every single time it's run
(`scripts/playlists/specificity_exam_v1.json`). Because the timeline
never changes, we can re-run the *exact same test* again after making a
fix, and directly compare before-and-after results on a truly
apples-to-apples basis — something a randomly-timed test could never
offer.

### The pass bar

| Check | Requirement |
| --- | --- |
| Near-miss false alarms | **Zero** |
| False alarms during calm, healthy segments | **Zero** |
| BGP alarms with no real supporting evidence | **Zero** |

### The real story: FAIL, then PASS

The very first time we ran this exam, it **failed**: one false alarm
during a near-miss, and two false alarms during otherwise calm periods.
We responded, in order: first tightening the loom's patience settings
(Chapter 6), then running a targeted data campaign specifically aimed at
the exact failure patterns, then retraining and re-promoting. The next
time we ran the **exact same** playlist, it **passed cleanly**: zero
false alarms of every kind. We then deliberately built a second, *never
diagnosed against* playlist (`specificity_exam_v2.json`) with different
timings, specifically to prove the fix generalized and wasn't just an
answer memorized for the first specific test — it also passed cleanly.

---

## Level 4 — The all-healthy control run (the simplest, most brutal test)

Separate from both the blind test and the specificity exam, we also run
the simplest possible honesty check: a period with **zero** faults and
**zero** near-misses injected at all — just ordinary, real network
traffic, for a full hour. Every single alarm raised during a control run
is, by definition, a false alarm, with no ambiguity possible.

Our very first control run came back badly: **21 false alarms in one
hour** (told in full in Chapter 7, Problem 1). Our most recent control
runs have come back completely clean — zero false alarms, held steady
across several separate re-checks after later changes, specifically to
make sure later fixes for other problems hadn't quietly reopened this
one.

---

## Level 5 — Deliberately trying to break the system: compound and echo testing

Beyond the standard tests above, we ran a series of deliberately harder,
adversarial scenarios specifically designed to expose weaknesses — two
real, genuinely different problems were found and fixed this way, both
described in Chapter 7, Problem 5:

- **Compound faults** — two different faults happening at the same time,
  on purpose, to test whether a loud fault drowns out a quiet one.
- **Cross-host echo** — testing whether one station was mistakenly
  declaring its own, independent fault, when what it was actually seeing
  was just the downstream side effect of a *different* station's fault.

Both were found because we specifically went looking for them with
deliberately adversarial tests, rather than waiting to be surprised by
them later during a real live test or, worse, in a real deployment.

---

## A real detective story: the timezone trap

### The situation

At one point, we needed to confirm a specific, important sequence of
events really happened in the order we believed: had a particular model
promotion genuinely finished *before* a specific verification test ran
against it, or was there a chance the test had actually run against an
old, stale model, making its result meaningless?

### The trap

Every script in this project stamps its own internal records — run-ids,
log lines, backup folder names — using **UTC** (Coordinated Universal
Time, Chapter 1), a single, unchanging global time reference. But the
lab computer itself, when you ask it directly for the current time using
ordinary commands like `stat`, `ls -la`, or `date`, displays **local
Indian Standard Time (IST, UTC+5:30)** — five and a half hours ahead of
UTC.

If you compare a UTC-based folder name (like a backup directory literally
named with a UTC timestamp) against a `stat` command's locally-displayed
file modification time, without carefully converting between the two,
the same two real, related events can look like they happened **5.5
hours out of order** — when in fact nothing was ever out of order at
all; the numbers were just being read in two different clocks
simultaneously.

**Real-life comparison:** imagine two people on a video call, one in
London and one many hours ahead in a different time zone, both saying "I
finished my part at 3 o'clock" — if you don't ask *which* 3 o'clock each
of them means, you could easily, and wrongly, conclude one of them
finished before they even started.

### The fix

We resolved this the careful way: instead of trusting `stat`/`ls`-style
filesystem metadata (which is also separately unreliable for a different
reason — a backup copy operation can preserve an *original* file's old
modification time rather than stamping a fresh one), we specifically read
the actual UTC timestamps written *inside* the log files and JSON records
themselves — the timestamps a script had deliberately written into its
own content at the moment it ran, not metadata *about* the file after the
fact. Cross-checking these content-embedded UTC timestamps confirmed the
true, correct order of events, resolving the confusion entirely.

### Why we wrote this down permanently

This exact trap is easy to fall into again in the future, by us or by
anyone else working on this project, so we added a permanent, explicit
note about it directly into `docs/SCRIPTS.md`, right at the top, so that
anyone comparing timestamps in the future is warned before they make the
same mistake:

> *"Every script in this repo stamps `datetime.now(timezone.utc)`... The
> lab machine itself displays local IST (UTC+5:30) in `stat`/`ls -la`/
> `date`. Don't cross-compare a backup folder's name (UTC) against `stat`
> output on its contents (local IST) without converting... When you need
> to verify ordering of two events... prefer the UTC timestamp embedded
> in file content... over filesystem `stat` metadata."*

### The lesson

Verification is not just "did we run a test" — it's also "are we
correctly reading the results of the test we ran." A perfectly good test
result can still be *misinterpreted* into a false alarm about your own
system, purely through a small, easy-to-make mistake in how you read a
timestamp. Being this careful, and writing the lesson down permanently
rather than just quietly fixing it once, is part of what it means to
actually trust your own results.

---

## The golden rule of this whole chapter

**Keep the different kinds of claims separate, and never let a pass on
one type of test stand in for a different type of test.** Specifically:

- A passing specificity exam or a clean control run proves DECA is
  *calm* — it does **not** prove DECA successfully *detects* real
  faults.
- A successful blind test proves DECA *detects* real faults on the
  specific night it was tested — it does **not**, by itself, prove DECA
  is calm the rest of the time, and one night alone is not enough to
  trust as a stable long-term number.
- Both together, gathered across multiple nights and multiple test
  designs, are what actually build a trustworthy picture — and this
  project's own internal documentation says so explicitly, in exactly
  these words: *"Exam PASS does not mean the system detects real faults.
  Detection lives in the blind cumulative,"* and, in the other direction,
  *"Exam PASS ≠ blind success. Quote both."*

---

## Continue

Chapter 10 takes everything built and verified so far and asks the next
big question: what would it actually take to move this whole system onto
a different, real network — specifically, ISRO's. Continue to
[Chapter 10 — Portability to ISRO](10_portability_to_isro.md).
