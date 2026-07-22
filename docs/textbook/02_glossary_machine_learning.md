# Chapter 2 — Machine Learning Glossary

## How to use this chapter

Same rules as Chapter 1: every word here is a real word used in this
project's code or documents. Each one gets a plain-English meaning, a
real-life comparison, where DECA uses it, and why it matters. Machine
learning has a reputation for being intimidating — this chapter is our
attempt to prove that reputation wrong. None of these ideas are actually
complicated once you see the everyday comparison behind them.

---

## Section 2.1 — What is "machine learning," really?

### Machine learning

**What it means:** Machine learning is a way of building a computer
program that learns to make decisions or predictions by looking at lots
of *examples*, instead of a human writing out every single rule by hand.

**Real-life comparison:** Think of how a child learns to recognize a dog.
No one hands a 3-year-old a rulebook that says "a dog has four legs, fur,
a tail, and barks." Instead, the child sees hundreds of real dogs (and
non-dogs) pointed out by a parent, and gradually their brain figures out
the pattern on its own. Machine learning does the same thing, but with a
computer and numbers instead of a child and pictures.

**Where DECA uses it:** DECA's whole "brain" — its ability to tell
`congestion_breach` apart from `bgp_route_flap` apart from a perfectly
healthy network — was built by showing it thousands of real examples of
each, not by a person writing "if jitter is above X, then Y" rules by
hand.

**Why it matters:** Hand-written rules break down quickly in networking
because real faults don't look identical every time — the pattern is
messy and can only really be learned by example, at scale, which is
exactly what machine learning is good at.

---

### Model

**What it means:** A "model" is the actual thing that results from the
learning process — a mathematical object that has learned patterns from
examples and can now be given a brand-new example (that it's never seen
before) and produce a prediction.

**Real-life comparison:** The "model" is the fully-grown, dog-recognizing
brain the child ends up with after seeing enough dogs — not the
individual dogs it learned from, but the general skill it now carries
around and can apply to any new dog it sees.

**Where DECA uses it:** `fault_classifier_xgb.pkl` is DECA's actual saved
model file — the "grown brain" that has learned from all our lab and
public data and can now look at brand-new telemetry and predict whether
something's wrong, and if so, what.

**Why it matters:** Once a model exists, using it (asking it "what do you
think this is?") is very fast — the slow, expensive part is the training
(the "learning by example") that happens beforehand.

---

### Training

**What it means:** Training is the actual process of showing a model many
examples and letting it adjust itself, step by step, until it gets good
at telling those examples apart.

**Real-life comparison:** Exactly the process of that 3-year-old being
shown dog after dog after dog, sometimes being told "yes, that's a dog"
and sometimes "no, that's a cat," until they get reliably good at telling
the two apart.

**Where DECA uses it:** `scripts/deca_school_exam_train.py` is the main
script that runs this whole training process for DECA's fault classifier.

**Why it matters:** Training is where all the real "learning" happens —
it's also the slowest and most resource-intensive step, which is why we
don't retrain from scratch every single time; instead (Chapter 10) we
often just "recalibrate" a few settings on an already-trained model.

---

### Prediction / inference

**What it means:** "Prediction" (also called "inference" in machine
learning language) is what happens *after* training is done — you hand
the trained model a brand-new example it has never seen, and it tells you
its best guess about what that example is.

**Real-life comparison:** That grown-up dog-recognizing brain, now being
shown a completely new dog it's never personally met before, and
correctly saying "dog" anyway, because it learned the *pattern*, not just
memorized the specific dogs it originally saw.

**Where DECA uses it:** Every time DECA looks at a fresh, live window of
telemetry from our lab and decides "this looks healthy" or "this looks
like `vrf_leakage`," that is a prediction/inference happening in real
time.

**Why it matters:** The entire point of building the model in the first
place is to eventually get to this step — a model that can only repeat
examples it already memorized (see **Overfitting** below) but can't
handle anything new is useless in the real world, where every real fault
looks at least slightly different from the last one.

---

### Feature

**What it means:** A "feature" is one single, specific piece of
information the model is allowed to look at when making its decision.
Instead of handing the model raw, messy measurements, we first compute a
carefully chosen set of features from those measurements.

**Real-life comparison:** If a doctor is trying to diagnose a patient,
they don't just stare blankly at a patient's whole medical history. They
look at specific, chosen pieces of information: "current temperature,"
"resting heart rate," "blood pressure" — each one of those chosen,
specific numbers is a "feature" the doctor's own mental model uses to
reach a diagnosis.

**Where DECA uses it:** DECA does not just hand the model raw numbers
like "packet loss was 4% at this exact second." Instead, it builds
carefully designed features like "how fast is packet loss *changing*
right now" — described fully under **Feature engineering** below.

**Why it matters:** The quality of a model's features is often more
important than which specific algorithm you use — this project's single
biggest breakthrough (Chapter 7, mistake #8, and Chapter 8's Tier 5c) was
entirely about *improving the features*, not changing the underlying
model at all, and it produced by far the biggest single jump in accuracy
of the whole project.

---

### Feature engineering

**What it means:** Feature engineering is the deliberate, human-designed
process of turning raw measurements into the smarter, more useful
features a model will actually learn from. This is a creative,
judgment-based step — a human decides what patterns are likely to matter
and builds features to capture them.

**Real-life comparison:** Rather than handing that doctor a raw stream of
"heartbeat, heartbeat, heartbeat, heartbeat..." sounds, feature
engineering is like a nurse first computing "average heart rate over the
last minute" and "how much did heart rate change in the last 5 minutes"
before handing those two smarter numbers to the doctor. The raw sound
recording is real data, but it's not yet in the shape a diagnosis
decision actually needs.

**Where DECA uses it:** `scripts/rebuild_unified.py` → `engineer_features`
is the exact function that does this for DECA. For every raw measurement
(like `packet_loss_pct`), it computes several smarter features: how fast
it's currently changing (**slope**), how bumpy it's been recently
(**rolling standard deviation**), what its recent average has been
(**rolling mean**), and whether its rate of change is itself speeding up
or slowing down (**acceleration**) — all explained individually below.

**Why it matters:** This single function is arguably the most important
piece of code in the whole project — every meaningful improvement we made
to DECA's actual understanding of faults (as opposed to just retraining
on more data) came from improving this function.

---

## Section 2.2 — The building blocks of feature engineering

### Rolling window

**What it means:** A "rolling window" is a fixed-size slice of the most
recent time — for example "the last 10 minutes" — that continuously
slides forward as time passes, always representing "recently," not one
fixed moment in the past.

**Real-life comparison:** Like a car's rearview mirror. It doesn't show
you one single frozen photo from an hour ago — it constantly shows you
"what's directly behind me right now," which changes moment to moment as
you keep driving.

**Where DECA uses it:** DECA computes its features over two different
rolling windows at once: a long one (about 10 minutes, for catching
slow-building problems like congestion) and a short one (about 2
minutes, for catching sudden problems like a route flap).

**Why it matters:** Different faults happen at different speeds — a
single rolling window size would either be too slow to catch a sudden
flap, or too jumpy/noisy to reliably catch a slow-building congestion
problem. Using two window sizes at once lets DECA catch both kinds.

---

### Slope

**What it means:** In this project, "slope" means "how fast is this
number currently rising or falling" — the rate of change, not the
number's actual current value.

**Real-life comparison:** Think of a car's speedometer versus its
odometer. The odometer shows the raw distance traveled (like a raw
measurement); the speedometer shows how fast that distance is currently
increasing (the slope) — and the speedometer is often far more useful for
noticing "something's changing right now" than staring at the raw
odometer number.

**Where DECA uses it:** `{metric}_slope` (for example `jitter_ms_slope`)
is one of the four core feature types computed for every metric, at both
the long and short rolling window.

**Why it matters:** A sudden, sharp slope — packet loss suddenly climbing
fast — is often a much stronger and earlier warning sign than the raw
loss number itself, especially before that number has even become
"high" in absolute terms.

---

### Rolling standard deviation

**What it means:** Standard deviation is a measure of how spread out (how
bumpy or inconsistent) a group of numbers is. "Rolling" standard
deviation means computing this bumpiness measurement over the recent
rolling window, continuously.

**Real-life comparison:** Going back to the jitter/bus-schedule
comparison from Chapter 1: standard deviation is basically a mathematical
way of measuring exactly how unpredictable that bus schedule has been
recently — a bus that reliably arrives every 10 minutes has low standard
deviation; a bus that sometimes comes in 2 minutes and sometimes in 25
has high standard deviation.

**Where DECA uses it:** `{metric}_rolling_std` is one of the four core
feature types for every metric.

**Why it matters:** Some faults show up mainly as *increased chaos/noise*
in a metric, even before its average value has clearly risen — rolling
standard deviation is what lets DECA catch that kind of "getting shakier"
signal.

---

### Rolling mean

**What it means:** The mean is the everyday "average." Rolling mean means
the average value of a metric over the recent rolling window,
continuously updated.

**Real-life comparison:** Like asking "what has this bus's *typical*
arrival gap been over the last hour?" rather than looking at any single
arrival.

**Where DECA uses it:** `{metric}_rolling_mean` is one of the four core
feature types for every metric.

**Why it matters:** This smooths out short-term noise so the model can
see the underlying, more stable trend, rather than reacting to every tiny
random wiggle in a single raw measurement.

---

### Acceleration (in this project)

**What it means:** If slope tells you "how fast is this number currently
changing," acceleration tells you "is that rate of change itself
speeding up or slowing down." It's the slope of the slope.

**Real-life comparison:** Back to the car comparison: if slope is your
current speed, acceleration is how hard you're currently pressing the gas
pedal — are you speeding up faster and faster, or leveling off at a
steady speed?

**Where DECA uses it:** `{metric}_accel` is the fourth and final core
feature type computed for every metric, at both rolling windows.

**Why it matters:** A number that is not just rising, but rising *faster
and faster*, is a much more urgent warning sign than one rising at a
steady, predictable pace — acceleration is how DECA distinguishes those
two very different situations.

---

### Median

**What it means:** The median is the exact middle value of a group of
numbers, once you've sorted them from smallest to largest — different
from the mean (average), because the median isn't dragged around by a
few extremely large or small outlier values.

**Real-life comparison:** If you lined up 9 people by height and picked
the person standing exactly in the middle, that person's height is the
median. If one of those 9 people happened to be an NBA player who's much
taller than everyone else, the *average* height of the group would get
pulled upward noticeably — but the *median* (middle person) barely
changes at all, because it doesn't care how extreme the outlier is, only
that it's on one side or the other.

**Where DECA uses it:** DECA's biggest recent improvement (Chapter 7,
mistake #8) computes a "median" value for each metric, per network run,
as a stable, honest estimate of "what's normal for this specific
network," deliberately choosing median over mean for the reason described
below.

**Why it matters:** Because a small fraction of DECA's own training data
inside any given network run *is* an actual fault (an outlier, by
definition), using the mean to estimate "what's normal" would get subtly
dragged toward the fault itself. The median mostly ignores those
outliers and gives a much more honest "normal" estimate.

---

### MAD (Median Absolute Deviation)

**What it means:** MAD is a way of measuring how spread out a group of
numbers is — similar in purpose to standard deviation, but built using
the median instead of the mean, making it much less thrown off by a few
extreme outlier values.

**Real-life comparison:** Continuing the height example: instead of
measuring "how far, on average, is everyone from the average height"
(which the one very tall outlier would distort), MAD measures "how far,
typically, is everyone from the *middle* height" — a measurement that the
one unusually tall person barely affects.

**Where DECA uses it:** MAD is the "spread" half of DECA's new
baseline-relative features (Chapter 7, mistake #8) — for each metric, in
each network run, DECA computes a median (the center) and a MAD (the
spread), and uses both together to figure out "how unusual is this
current reading, compared to this network's own normal."

**Why it matters:** Just like with the median above, using MAD instead of
standard deviation means the small handful of genuine fault rows mixed
into the data don't get to distort DECA's own definition of "normal
variation" for that network.

---

### Robust statistics

**What it means:** "Robust" statistics is the general name for any
statistical method (like median and MAD) that is deliberately designed to
resist being thrown off by a small number of extreme, unusual values
("outliers") mixed into the data.

**Real-life comparison:** Think of the difference between a fragile glass
figurine (easily broken/distorted by a small bump) and a rugged, durable
tool (barely affected by rough handling). "Robust" statistics are the
rugged, durable version of ordinary averages and spreads.

**Where DECA uses it:** DECA's entire baseline-relative feature system
(Chapter 7's mistake #8) is deliberately built entirely from robust
statistics (median and MAD) rather than ordinary mean and standard
deviation, specifically because the training data legitimately contains
outliers (the fault windows themselves) that we don't want silently
corrupting DECA's idea of "normal."

**Why it matters:** This is exactly the kind of careful, deliberate
engineering decision that separates a system that will hold up to
scrutiny from one that would quietly break the moment someone looked
closely at how "normal" was actually being computed.

---

### Z-score

**What it means:** A z-score answers the question "how many typical
spreads away from normal is this specific value?" It's computed by
taking a value, subtracting the "normal" center (median, in DECA's case),
and dividing by the "typical spread" (MAD, in DECA's case). A z-score of
0 means "exactly normal." A z-score of +3 means "quite far above normal";
-3 means "quite far below normal."

**Real-life comparison:** Imagine a nurse saying "this patient's fever is
3 degrees above what's typical for them personally" rather than just
saying the raw number "101°F" — the z-score-like statement ("3 above their
own normal") is more meaningful than the raw number alone, because
different patients naturally run at slightly different baseline
temperatures.

**Where DECA uses it:** This is the very core of DECA's biggest single
improvement (Chapter 7, mistake #8, and Chapter 8's Tier 5c). Every
metric now gets a z-score version computed alongside its raw value, so
DECA can learn things like "3 MAD above this specific network's own
normal traffic level" instead of only "above 40 megabits per second" —
a fixed number that would mean something completely different on a
different, busier or quieter, real network.

**Why it matters:** This single change is *why* DECA can realistically
be handed over to a different network (like ISRO's) without a full
retrain — a rule stated in "how far above your own normal" terms
naturally works the same way on any network, while a rule stated in fixed
absolute numbers (like "40 megabits per second") is specific to our one
particular lab's traffic scale and would need to be re-learned from
scratch on a different network.

---

## Section 2.3 — Making a decision: classification

### Classification

**What it means:** Classification is the general machine learning task of
sorting something into one of several known categories (called
"classes"), based on its features.

**Real-life comparison:** Like a librarian who sorts every returned book
into one of several shelves — fiction, non-fiction, children's,
reference — based on looking at each book's cover and contents.

**Where DECA uses it:** DECA's central job is a classification task: for
every window of telemetry, sort it into one of five categories: `healthy`,
`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, or
`vrf_leakage`.

**Why it matters:** This framing — "which of a known, fixed list of
categories does this belong to" — is exactly the right shape for DECA's
job, since our fault taxonomy really is a small, fixed, well-understood
list (as opposed to, say, an open-ended task like "write a summary").

---

### Class

**What it means:** A "class" is one single category in a classification
task — one of the possible answers the model can choose from.

**Where DECA uses it / why it matters:** DECA has exactly five classes:
`healthy` and the four fault types. This word shows up constantly
throughout the code and documentation (for example, "per-class F1," "rare
class," "class threshold").

---

### Binary classifier

**What it means:** A binary classifier is a classification model that
only ever has two possible answers — yes/no, on/off, this-or-that.

**Real-life comparison:** Like a simple metal detector at an airport
security checkpoint: it doesn't try to say *what kind* of metal object it
found, it just says "beep" (metal detected) or silence (nothing detected).

**Where DECA uses it:** DECA's "anomaly gate" (fully explained in Chapter
6) is a binary classifier: its only job is to decide "is this window
`healthy`, or is it *any* kind of fault?" — a simple yes/no question,
before the more detailed multiclass decision below even gets asked.

**Why it matters:** Splitting the harder five-way decision into "first, a
simple yes/no gate, then, if 'no,' a more detailed decision" turned out
to be a major, deliberate design choice (Chapter 6 explains exactly why)
that helps prevent the overwhelming majority of "healthy" examples from
drowning out the much rarer fault examples.

---

### Multiclass classifier

**What it means:** A multiclass classifier is a classification model that
can choose between *more than two* possible categories.

**Real-life comparison:** Like a more detailed airport scanner that
doesn't just say "beep," but actually says "this is a metal water bottle"
versus "this is a pocketknife" versus "this is a phone" — distinguishing
between several specific categories, not just yes/no.

**Where DECA uses it:** DECA's "multiclass head" (Chapter 6) is what
decides *which* of the four specific fault types is happening, once the
binary gate above has already said "yes, something is wrong."

**Why it matters:** This is the piece of DECA that actually gives an
operator useful, actionable information — not just "something is wrong,"
but specifically "this looks like a BGP route flap," which tells the
right team exactly what to go investigate.

---

### Anomaly detection

**What it means:** Anomaly detection is the specific task of spotting
"something unusual is happening here," often without necessarily knowing
in advance exactly *what* kind of unusual thing to expect.

**Real-life comparison:** Like a security guard who has never seen a
specific type of crime before, but has spent years learning what
"ordinary, calm" looks like around the building — the moment something
deviates from that calm baseline, they notice, even if they can't
immediately name exactly what's wrong.

**Where DECA uses it:** DECA's "anomaly gate" is fundamentally an anomaly
detector — a binary classifier trained specifically to recognize
"deviation from the healthy pattern." One of DECA's companion models,
the **Isolation Forest** (below), is an even purer example — it never
even looks at fault labels at all, only at what "normal" traffic looks
like.

**Why it matters:** Anomaly detection is valuable specifically because it
can, in principle, flag something is wrong even for a kind of problem the
system was never explicitly trained to recognize by name — a useful
safety net alongside the more specific fault classifier.

---

### Gate

**What it means:** In DECA specifically, "the gate" refers to the binary
anomaly classifier that runs first, before the more detailed multiclass
decision. If the gate says "this looks healthy," DECA stops there and
reports healthy. Only if the gate says "this looks anomalous" does DECA
go on to ask the more detailed "which specific fault is this" question.

**Real-life comparison:** Like a hospital's emergency room triage nurse.
The triage nurse's whole job is a simple first filter: "is this patient
urgent, or can they wait in the regular queue?" Only the urgent patients
get sent on to a specialist doctor for a detailed diagnosis — the triage
nurse doesn't try to diagnose every single ache and pain themselves.

**Where DECA uses it / why it matters:** See **Binary classifier** above
— this is DECA's own specific name for that concept, and it's explained
in full architectural detail in Chapter 6.

---

### Threshold

**What it means:** A threshold is a specific cutoff number used to turn a
model's raw confidence score (usually a number between 0 and 1,
representing "how sure am I") into an actual yes/no decision.

**Real-life comparison:** Like a doctor's rule: "if a patient's fever is
above 100.4°F, I officially call it a fever; below that, I don't." The
number 100.4 is the threshold — the exact line that turns a continuous
measurement into a clear decision.

**Where DECA uses it:** DECA has a `gate_thr` (the anomaly gate's
threshold — how confident must the gate be before it calls something
anomalous) and a separate `class_thr` for each of the four fault types
(explained further under **Decision threshold tuning** below). These
exact numbers are stored, in plain readable text, in
`decision_thresholds.json`.

**Why it matters:** Thresholds are one of the main "knobs" that can be
adjusted to fine-tune DECA's behavior — raising a threshold makes DECA
more cautious (fewer false alarms, but slower to catch real problems);
lowering it makes DECA more sensitive (catches real problems faster, but
more prone to false alarms). Chapter 10 explains how adjusting just these
thresholds (without retraining anything) is DECA's fastest way to adapt
to a brand-new network.

---

## Section 2.4 — How good is the model, actually? Measuring performance

### Precision

**What it means:** Precision answers the question: "Of all the times the
model said 'yes, this is class X,' how often was it actually right?" A
model with low precision cries out "fault!" a lot, but is often wrong
when it does.

**Real-life comparison:** Imagine a fire alarm that goes off 10 times a
month, but only 2 of those 10 times was there an actual fire. Its
precision is low (2 out of 10 = 20%) — most of its alarms were false
alarms.

**Where DECA uses it:** Precision is calculated separately for every one
of DECA's five classes, and is a core ingredient of the F1 score (below).

**Why it matters:** Low precision is exactly the "cried wolf too much"
problem described in Chapter 7's very first mistake — a model that
constantly raises false alarms quickly loses an operator's trust, even
if it does eventually catch every real fault.

---

### Recall

**What it means:** Recall answers a different question: "Of all the times
something actually *was* class X, how often did the model correctly catch
it?" A model with low recall misses a lot of real cases, even if it's
usually right when it does speak up.

**Real-life comparison:** Using that same fire alarm: imagine there were
actually 10 real fires in the building this year, but the alarm only ever
went off during 3 of them. Its recall is low (3 out of 10 = 30%) — it
missed most of the real fires.

**Where DECA uses it:** Recall is also calculated separately for every
class. There's a natural, unavoidable tension between precision and
recall — you can often boost one by sacrificing some of the other, which
is exactly what the threshold-tuning process (below) is trying to
balance sensibly.

**Why it matters:** Missing a real fault (low recall) can be just as
dangerous as too many false alarms (low precision) — a good fault
detector needs both, not just one.

---

### F1 score

**What it means:** F1 score is a single number that combines precision and
recall into one balanced measurement, so you don't have to look at two
separate numbers and guess how to weigh them against each other. A model
can only get a high F1 score if it's doing reasonably well on *both*
precision and recall — being extremely good at only one of the two isn't
enough.

**Real-life comparison:** Imagine grading a student not just on "how
often were they right when they answered" (precision) or "how many
questions did they actually attempt" (recall) alone, but requiring them
to be reasonably strong at *both* to earn a good overall grade — someone
who only ever answers the 2 easiest questions perfectly, while leaving
everything else blank, shouldn't get the same grade as someone who
attempts and gets most of the exam right.

**Where DECA uses it:** F1 score, computed separately for each of DECA's
five classes ("`bgp_route_flap` F1 is 0.48," for example), is the main
number reported throughout this entire project's results and documents.

**Why it matters:** F1 score is the single most-quoted number in this
whole project's history — nearly every improvement or setback described
in Chapter 8 is measured in terms of how a class's F1 score moved up or
down.

---

### Macro-F1

**What it means:** Macro-F1 is the *average* of the individual F1 scores
across all classes, treating every class equally regardless of how
common or rare it is in the data.

**Real-life comparison:** Imagine a school report card that averages a
student's grades across all subjects *equally* — Math, Art, and Gym all
count the same toward the final average — rather than weighting it by how
many hours were spent on each subject. This deliberately prevents one
huge, easy subject from hiding poor performance in a smaller, harder one.

**Where DECA uses it:** Macro-F1 is DECA's single headline "how good is
the whole model" number, and it's exactly the number the promotion gate
(Chapter 8) compares against a fixed bar (**0.717**) before deciding
whether to accept a newly trained model as the new champion.

**Why it matters:** Because `healthy` massively outnumbers the four fault
classes in our data, a model could get a deceptively high *overall*
accuracy just by being great at recognizing `healthy` and mediocre at
everything else. Macro-F1 specifically prevents that trick from hiding a
model's weaknesses on the rarer, more important fault classes.

---

### Confusion matrix

**What it means:** A confusion matrix is a table that shows exactly how
often the model's predictions matched or didn't match the true answer,
broken down by every possible combination — for example, "how many
actual `vrf_leakage` rows did the model correctly call `vrf_leakage`, and
how many did it incorrectly call `bgp_route_flap` instead?"

**Real-life comparison:** Like a teacher going through a graded multiple-
choice exam and building a table: "of all the students who should have
answered 'B,' how many actually chose A, B, C, or D?" — showing not just
"how many got it right," but exactly *which* wrong answer people tended
to pick instead.

**Where DECA uses it:** A confusion matrix was the key diagnostic tool
used in Chapter 7's mistake #4 investigation (`scripts/deca_bgp_diagnose.py`)
— it's how we discovered that `bgp_route_flap` mistakes were mostly being
labeled `healthy` (missed entirely by the very first gate step), rather
than being confused with a different, similar-looking fault.

**Why it matters:** Overall accuracy or even F1 alone can't tell you
*where* a model's mistakes are landing. A confusion matrix is what let us
correctly diagnose that a problem was upstream (at the gate) rather than
downstream (at the fault-naming step) — a genuinely different fix,
depending on the answer.

---

### Support

**What it means:** In this project, "support" means simply "how many real
examples of this class exist in this particular batch of data." It's not
a performance score itself — it's context needed to interpret one.

**Real-life comparison:** If a teacher says "80% of students who took
question 7 got it right," you'd want to know: was that out of 200
students, or out of only 3? "Support" is that "out of how many" number.

**Where DECA uses it:** Support numbers (like "`bgp_route_flap`: 75
examples" in an early evaluation) show up constantly alongside precision/
recall/F1 tables throughout the documentation.

**Why it matters:** A rare class with very small support (like 52 or 75
examples) is inherently harder to measure reliably and harder for the
model to learn well — this is a big part of *why* the rare fault classes
were consistently the hardest ones for DECA to master, and why we ran
entire extra data-collection campaigns (Chapter 8) specifically targeting
them.

---

### Class imbalance

**What it means:** Class imbalance is when some categories in your
training data are much more common than others — in DECA's case,
`healthy` examples vastly outnumber examples of any single fault type.

**Real-life comparison:** Imagine trying to teach someone to recognize
rare bird species, but 95% of every photo you ever show them is a common
pigeon, and the rare species only show up once in a while, scattered
thinly among thousands of pigeon photos. It's easy to get "good at
pigeons" almost by accident, while never really learning the rare birds
well.

**Where DECA uses it / why it matters:** This is one of the most
persistent, foundational challenges of the entire project. Nearly every
major technique described in this book — the binary gate, inverse-
frequency weighting, targeted fault campaigns, and even the promotion
gate's use of macro-F1 instead of plain accuracy — exists specifically
to fight this one underlying problem.

---

### Inverse frequency weighting

**What it means:** This is a technique where, during training, mistakes on
*rare* classes are deliberately made to "count for more" than mistakes on
*common* classes — specifically, a class that appears half as often gets
roughly twice the weight, so that getting it wrong is treated as twice as
costly during learning.

**Real-life comparison:** Imagine a teacher grading an exam where a rare,
harder bonus question is deliberately worth 10 points, while an easy,
common warm-up question is only worth 1 point — because the teacher
wants to make sure students can't get a great grade purely by acing the
easy stuff while ignoring the hard, rare question entirely.

**Where DECA uses it:** DECA's training process (in
`scripts/deca_school_exam_train.py`) applies inverse-frequency weighting
so that mistakes on `bgp_route_flap` and `vrf_leakage` (the rarer
classes) matter more to the model during learning than an equivalent
mistake on the much more common `healthy` or `congestion_breach` classes.

**Why it matters:** Without this, a model could get a great-looking
overall score just by nailing the common classes while quietly giving up
on the rare, harder-to-learn ones — this technique is one of the
project's earliest and most fundamental fixes for that problem.

---

### Rare class / rare boost

**What it means:** A "rare class" is simply one of the categories with
relatively few training examples — in DECA's history, `bgp_route_flap`
and `vrf_leakage` were consistently the rare classes. "Rare boost" (also
called β, the Greek letter "beta," in our documentation) is a tunable
setting that controls exactly *how much extra* weight rare classes get
during training — a stronger version of inverse-frequency weighting that
can be turned up or down and tested.

**Where DECA uses it / why it matters:** DECA's training process
automatically tries several different "β" (rare-boost) settings and picks
whichever one performs best — this is called a "β sweep," and it shows up
throughout Chapter 8's history as one of the main levers we experimented
with while trying to improve the rare classes.

---

## Section 2.5 — Testing honestly: splits, holdouts, and exams

### Train/test split

**What it means:** Before training a model, you deliberately hold back
some of your data and don't let the model see it during training at all
— that held-back portion is only used *afterward*, to honestly test how
well the model performs on examples it's never seen before.

**Real-life comparison:** Like a teacher who prepares two separate sets
of practice questions: one set the students get to study from ahead of
time (the "training set"), and a second, completely different set of
questions — never shown to the students in advance — used only on the
actual final exam (the "test set"). This is the only fair way to measure
whether students actually *learned the subject*, rather than just
memorized the specific practice questions.

**Where DECA uses it:** DECA never reports a score based on data the
model was trained on — every single reported number in this project's
history came from a held-back portion of data the model never got to
study during training.

**Why it matters:** Without this split, you could build a completely
useless model that has simply memorized every single training example
by heart, and it would look "perfect" on paper while being worthless on
any brand-new, real-world telemetry it's never seen before — this split
is what protects against that trap.

---

### Overfitting

**What it means:** Overfitting is exactly that trap — when a model learns
to "memorize" the specific quirks of its training examples too closely,
instead of learning the *general pattern* that would also apply to new,
never-before-seen examples. An overfit model looks great on its training
data but performs poorly on anything new.

**Real-life comparison:** Like a student who memorizes the exact answers
to last year's specific exam questions, word for word, instead of
actually understanding the underlying subject — they'd do great if given
that exact same exam again, but fall apart the moment even slightly
different questions are asked.

**Where DECA uses it:** Overfitting is exactly why our "mixture of
experts" model architecture (`moe`, fully explained in Chapter 6) failed
during testing — with so few real examples of the rare fault classes, a
model with too many adjustable internal parts ended up "memorizing" the
handful of specific rare examples it saw, rather than learning a pattern
general enough to work on new ones.

**Why it matters:** This is a foundational risk in all of machine
learning, and a big part of why "just build a bigger, more complicated
model" is not automatically the right answer, especially when you don't
have very much data for some categories — as Chapter 6 explains, "more
complicated" architectures were specifically tested and rejected by our
own honest evaluation process because of exactly this risk.

---

### Holdout

**What it means:** "Holdout" is another common word for the test-set idea
above — data that is deliberately "held out" (kept aside, unseen) from
training, specifically so it can be used afterward for an honest
evaluation.

**Where DECA uses it / why it matters:** See **Train/test split** above
— it's the same idea, and the words are used interchangeably throughout
DECA's code and documentation (for example, `--holdout-frac`,
`--holdout-policy`).

---

### Stratified sampling

**What it means:** Stratified sampling is a careful way of splitting data
into training and test sets that makes sure each class (including the
rare ones!) is fairly represented in *both* the training data and the
test data, in roughly the same proportion as in the whole dataset — rather
than leaving it up to random chance, which could accidentally put almost
all of a rare class into just one side of the split.

**Real-life comparison:** Imagine dividing a class of students into two
groups for a fairness study, and making sure both groups end up with a
similar mix of different grade levels, rather than randomly risking one
group accidentally ending up with almost all the 5th graders and the
other group with almost all the 3rd graders.

**Where DECA uses it:** DECA's training process specifically uses
stratified splits so that its already-rare fault classes (`bgp_route_flap`,
`vrf_leakage`) don't accidentally get almost entirely swept into only the
training set or only the test set by random chance.

**Why it matters:** With classes as rare as ours, an unlucky ordinary
random split could easily leave the test set with almost no real
examples of a rare class at all, making any reported score on that class
essentially meaningless — stratified sampling protects against that.

---

### Exam / exam paper / exam seed

**What it means:** Throughout this project's documentation, "the exam" is
our own friendly nickname for the held-out test data described above,
and "exam paper" specifically means one particular random draw of which
rows ended up in that held-out set. An "exam seed" is a specific starting
number that controls exactly which random draw happens — using the same
seed twice will always produce the exact same "exam paper" both times,
which is useful when you want to fairly compare two different models on
the *identical* test.

**Real-life comparison:** Imagine a teacher who can print out a
"randomly shuffled" version of an exam, but has a special setting that
lets them reprint the *exact same* random shuffle again later, whenever
they want a completely fair rematch between two different students (or
two different versions of the same student's own knowledge).

**Where DECA uses it:** `--exam-seed 42` is a flag used throughout the
project's scripts specifically so that two models (say, the old champion
and a brand-new candidate) can be honestly compared on the exact same
held-out data, rather than each getting a different, potentially easier
or harder, random draw.

**Why it matters:** Chapter 9 tells a whole story about how *not* using a
fixed seed (drawing a fresh random exam paper every single run, which is
DECA's actual default behavior for promotion decisions) creates a small,
expected amount of run-to-run noise in the reported scores — an important
thing to understand so you don't over-read a small score change as a
real trend when it might just be normal random variation between two
different exam papers.

---

### Champion / challenger / promotion gate

**What it means:** "Champion" is DECA's nickname for whichever model is
currently actively deployed and trusted. "Challenger" is a newly trained
candidate model being considered to replace it. The "promotion gate" is
the rule that decides whether a challenger is actually allowed to become
the new champion — in DECA's case, the challenger must score *at least as
well* as the champion on the exact same held-out exam, and must clear an
overall minimum bar (macro-F1 of at least **0.717**).

**Real-life comparison:** Like a martial arts gym that has one current
reigning champion, and any student who wants to take that title has to
actually beat the champion in a real, fair, judged match — not just claim
they're better, and not just because they trained really hard.

**Where DECA uses it:** This concept runs through nearly the entire
project's history (Chapter 8). Several rounds of DECA's own effort (extra
training campaigns, deeper model architectures) were specifically
*rejected* by this promotion gate because they failed to actually beat
the existing champion on a fair, honest test — which the project treated
as valuable, honest information, not as a failure to hide.

**Why it matters:** Without a promotion gate, it would be very easy to
accidentally deploy a model that's actually *worse* than what's already
running, just because it happened to look good on paper in one specific
test. The gate enforces real, disciplined, apples-to-apples comparison
every single time.

---

## Section 2.6 — The actual "brains": model architectures used

### Decision tree

**What it means:** A decision tree is one of the simplest kinds of
machine-learned models — it makes a decision by asking a sequence of
simple yes/no questions, one after another, like a flowchart, until it
reaches a final answer.

**Real-life comparison:** Like the classic "20 Questions" game, or a
doctor's simple triage flowchart: "Is temperature above 100.4°F? If yes,
is cough present? If yes, ..." — a series of simple branching questions
that eventually leads to a conclusion.

**Where DECA uses it:** A single decision tree, by itself, is rarely
strong enough on its own — DECA instead uses many trees *together* (see
**Gradient boosting** and **XGBoost** below).

**Why it matters:** Understanding a single tree is the foundation for
understanding the more powerful "ensemble" methods (below) that DECA
actually uses — those are really just smart ways of combining many simple
trees.

---

### Ensemble

**What it means:** An "ensemble" is a model made up of *many* smaller
models working together, whose combined answer is usually more reliable
than any single one of them alone.

**Real-life comparison:** Like a team of doctors all independently
reviewing the same patient's chart and then combining their opinions,
rather than trusting the diagnosis of just one single doctor — a team
opinion tends to catch more mistakes and be more reliable than any one
person's opinion alone.

**Where DECA uses it:** DECA's core classifier (built with **XGBoost**,
below) is fundamentally an ensemble of many decision trees.

**Why it matters:** Ensembles are one of the most reliable, well-proven
techniques in all of machine learning for exactly this kind of structured
data (a table of numeric features) — which is a big part of why DECA is
built on trees rather than something more exotic.

---

### Gradient boosting

**What it means:** Gradient boosting is a specific, clever way of building
an ensemble of decision trees, one at a time, where *each new tree is
specifically trained to fix the mistakes the previous trees were still
making* — rather than all trees being trained independently and blindly
from scratch.

**Real-life comparison:** Imagine a team of tutors working with one
student, one after another. The first tutor teaches the basics. The
second tutor doesn't repeat the basics — they specifically focus only on
whatever mistakes the student is *still* making after the first tutor's
lesson. The third tutor focuses only on whatever's *still* wrong after
that. Each new tutor's whole job is to specifically patch the team's
remaining weak spots.

**Where DECA uses it:** This is exactly how **XGBoost** (below), DECA's
core modeling technology, works.

**Why it matters:** This "each new piece fixes the remaining mistakes"
approach tends to produce very strong, accurate models, especially on
exactly the kind of numeric, tabular feature data (rolling means, slopes,
etc.) that DECA is built from.

---

### XGBoost

**What it means:** XGBoost ("Extreme Gradient Boosting") is a specific,
extremely popular, and highly optimized software package that implements
the gradient boosting idea above. It's widely used across the machine
learning industry for exactly this kind of structured, numeric data
problem.

**Real-life comparison:** If gradient boosting is the *idea* of a relay
team of specialist tutors each fixing the remaining mistakes, XGBoost is
a specific, professionally-trained, extremely well-drilled team that's
known for being both very good and very fast at running this exact
relay.

**Where DECA uses it:** XGBoost is the actual underlying technology behind
both DECA's binary anomaly gate and its multiclass fault classifier.

**Why it matters:** We deliberately chose XGBoost over a more exotic
option like a deep neural network, because tree-based methods like
XGBoost are known to generalize better than a "deep learning" approach on
a dataset of this size (tens of thousands of rows, roughly a hundred
columns) — a large neural network typically needs vastly more data than
that to outperform trees.

---

### KMeans clustering

**What it means:** KMeans is a technique that automatically groups similar
data points together into a fixed number of "clusters," without being
told in advance what the groups should look like — it discovers the
groupings on its own, purely from how close together points are.

**Real-life comparison:** Imagine dropping a large box of mixed buttons
onto a table and asking someone to sort them into, say, 5 piles based
purely on how similar they look to each other, without telling them in
advance what those 5 categories should specifically be (by color? by
size? by shape?) — they'd naturally group visually similar buttons
together.

**Where DECA uses it:** DECA's `wm` model architecture (Chapter 6) adds a
KMeans clustering step as an extra input to help the main model — the
idea being that "which general neighborhood of behavior does this
telemetry window fall into" might be a useful extra clue.

**Why it matters:** It's a genuinely reasonable idea to try — but our own
honest testing (Chapter 6 and Chapter 8, Tier 5.5) found this extra step
provided essentially no real improvement on our specific data, which is
exactly the kind of honest negative result worth reporting rather than
hiding.

---

### Mixture of experts

**What it means:** A "mixture of experts" model architecture trains
several separate specialist sub-models (each one focused on a particular
class or situation), plus one additional "gating" model whose job is to
decide how much to trust each specialist for any given new example, then
blends their opinions together.

**Real-life comparison:** Like a hospital that, instead of relying on one
general doctor for everything, has several specialists (a heart
specialist, a lung specialist, a bone specialist) plus a head doctor
whose job is to decide "for this specific patient, how much weight should
I give each specialist's opinion" and combine them into one final
recommendation.

**Where DECA uses it:** DECA's `moe` model architecture (Chapter 6) is
exactly this — a specialist sub-model per fault class, blended by a
gating model.

**Why it matters:** This architecture sounds powerful in theory, but our
honest testing found it performed clearly *worse* than the simpler
approach on our data — specifically because, with as few rare-class
examples as we had, this many extra adjustable parts led to overfitting
(explained above), not better learning. This is one of the clearest
"more complexity isn't automatically better" lessons of the whole
project.

---

### Isolation Forest

**What it means:** An Isolation Forest is a different kind of model, used
for anomaly detection, that never looks at any fault labels at all. It
works by trying to "isolate" (separate out) each data point using random
splits — and the key insight is that truly unusual points tend to get
isolated in far *fewer* random splits than ordinary points do, because
they're already sitting apart from the crowd.

**Real-life comparison:** Imagine trying to single out one specific person
in a huge, packed crowd by asking a series of quick, random yes/no
questions ("are you wearing red? are you taller than average?"). A
person who's genuinely unusual in several ways gets singled out from the
crowd very quickly, in just a few questions. An ordinary, typical person
takes many more questions to separate from everyone else who's similar to
them.

**Where DECA uses it:** DECA has a companion Isolation Forest model,
trained only on healthy examples, that provides an extra, independent
"how unusual does this look" confidence signal, separate from the main
fault classifier.

**Why it matters:** Because it never looks at fault labels at all, an
Isolation Forest can, in principle, flag something as unusual even if
it's a completely new kind of problem the main classifier was never
specifically trained to recognize by name — a useful extra safety net.

---

### Platt calibration

**What it means:** Platt calibration is a technique for turning a model's
raw internal score into an honest, well-calibrated probability — so that
when the model says "I'm 80% confident," that 80% actually means
something close to "in similar cases, I've been right about 80% of the
time," rather than being an arbitrary number.

**Real-life comparison:** Like a weather forecaster who, when they say
"70% chance of rain," has actually checked their own historical track
record and confirmed that, of all the days they said 70%, it really did
rain about 70% of the time — rather than just picking a number that
sounds roughly right.

**Where DECA uses it:** DECA's Isolation Forest model uses Platt
calibration to turn its raw internal anomaly score into a genuinely
meaningful "probability of anomaly" number that an operator can trust as
an actual confidence level.

**Why it matters:** An uncalibrated confidence number can be actively
misleading — Platt calibration is what makes DECA's reported confidence
levels trustworthy rather than just decorative.

---

### LSTM (Long Short-Term Memory)

**What it means:** An LSTM is a type of neural network specifically
designed to understand *sequences* — data where the order things happen
in matters, like a sentence, a song, or a series of network measurements
over time. It has a kind of internal "memory" that lets it carry
information forward from earlier in a sequence to help interpret later
parts.

**Real-life comparison:** Like a person reading a mystery novel who
remembers earlier clues from chapter 1 while reading chapter 10, and uses
that memory to understand what's happening now — rather than only ever
being able to look at one single sentence in total isolation, with no
memory of anything that came before it.

**Where DECA uses it:** DECA has a companion LSTM model whose specific job
is not to name the fault, but to estimate "time to breach" — roughly how
many minutes remain before a developing problem is likely to fully
"break," based on the recent sequence of measurements leading up to now.

**Why it matters:** This is a genuinely different, complementary question
from "what fault is this" — it's the "when" question, which the main
fault classifier doesn't try to answer at all, making the LSTM a useful
extra piece of the whole picture (Chapter 6 covers exactly how it fits
in, and how the project honestly tested — and rejected — tightly coupling
it to the main classifier's decision-making).

---

### Prophet

**What it means:** Prophet is a well-known, publicly available tool
(originally built by Facebook/Meta) for forecasting a time series into
the future, specifically designed to handle everyday patterns like "this
number is usually higher on weekdays than weekends" (seasonality,
below) automatically.

**Real-life comparison:** Like a tool built specifically to say "based on
this store's sales history, weekdays are always a bit quieter than
weekends, and this whole month tends to trend upward" — automatically
picking up on repeating calendar patterns without a human manually
pointing them out.

**Where DECA uses it:** DECA runs three separate Prophet models, one each
for traffic volume, jitter, and BGP update rate, to build a general
"what does a normal day/week usually look like for this metric" baseline
envelope.

**Why it matters:** This is a different kind of "normal" than the anomaly
gate's — Prophet's baseline is about *expected calendar patterns*, useful
context for questions like "is an SLA breach structurally likely given
how this metric is trending," separate from moment-to-moment fault
detection.

---

### Seasonality

**What it means:** In time series analysis, "seasonality" means any
regularly repeating pattern tied to a calendar cycle — daily patterns
(busier in the day, quieter at night), weekly patterns (busier on
weekdays), or yearly patterns (busier during a particular season).

**Real-life comparison:** Like a coffee shop that reliably gets busier
every morning around 8 AM and quieter every night — a predictable,
repeating rhythm tied to the clock and calendar, not a random fluctuation.

**Where DECA uses it / why it matters:** See **Prophet** above — this is
exactly the kind of pattern Prophet is specifically built to model and
separate out from genuine unusual events.

---

### Topology graph

**What it means:** A topology graph is simply a map, represented as data a
computer can use, of which network devices are connected to which other
devices.

**Real-life comparison:** Like a subway map showing which stations
connect directly to which other stations — not the geography of the
city, just the connections.

**Where DECA uses it:** DECA has a small topology graph representing our
three stations (PE1 ↔ CORE ↔ PE2), used for an experimental feature that
checks whether *neighboring* stations agree before declaring a fault
(explained fully in Chapter 6 — and, in our honest testing, ultimately
not switched on, because it didn't actually improve results).

**Why it matters:** In principle, correlated evidence from a device's
network neighbors could help confirm or deny a suspected fault — this is
a reasonable idea that we specifically tested and are honest about not
having found a net benefit from yet on our current data.

---

## Section 2.7 — Reading a fault over time, not just one frame at a time

### Frame

**What it means:** In this project, a "frame" is one single window of
telemetry at one moment — essentially one row of DECA's feature table,
representing "here's what things looked like at this specific moment."

**Real-life comparison:** Like one single photo out of a whole video —
one snapshot moment, not the whole moving picture.

**Where DECA uses it / why it matters:** DECA's basic classifier makes a
decision one frame at a time. The next several terms below (hysteresis,
persistence, the "loom") are all about smartly combining a *sequence* of
these individual frame-by-frame decisions into a more stable, trustworthy
final answer — because looking at just one single frame in isolation
turns out to be too jumpy and unreliable on its own.

---

### Hysteresis

**What it means:** Hysteresis is a general engineering concept: a system
deliberately resists changing its current state too quickly, requiring a
consistent signal for a while before actually flipping its decision —
which prevents rapid, unstable flip-flopping caused by brief noise.

**Real-life comparison:** Think of a home thermostat. It doesn't turn the
heater on and off every single time the temperature wobbles by half a
degree — it waits until the temperature has genuinely drifted past a
clear line, and even then, it typically waits for the temperature to
drop meaningfully below *that* line again (not just barely back above it)
before turning back off. This deliberate "stickiness" prevents the
heater from clicking on and off constantly over tiny wobbles.

**Where DECA uses it:** DECA's "temporal loom" (below) is built entirely
around this idea — it requires a fault prediction to repeat for several
frames in a row before officially "declaring" it, and similarly requires
several healthy frames in a row before officially "clearing" a declared
fault.

**Why it matters:** Without hysteresis, a single noisy, wrong frame-level
prediction could trigger (or clear) a fault alarm on its own — hysteresis
is what makes DECA's live, moment-to-moment alerting stable and
trustworthy, rather than flickering unpredictably.

---

### Temporal persistence / the "loom"

**What it means:** "Temporal persistence" (nicknamed "the loom" in this
project's own documentation) is DECA's whole system for applying
hysteresis over a live, ongoing stream of frame-by-frame predictions —
deciding, frame after frame, whether the streak of predictions has been
consistent enough for long enough to "enter" a declared fault state, or
"exit" back to healthy.

**Real-life comparison:** Imagine a jury that doesn't convict someone
based on a single, possibly-mistaken witness statement — they wait to
hear the same story repeated and confirmed by multiple pieces of
consistent evidence before reaching a "guilty" verdict, and similarly
wouldn't reverse that verdict over one contradicting comment either.

**Where DECA uses it:** `scripts/deca_inference.py` implements this
"loom" logic for DECA's live, chronological (not shuffled) telemetry
streams. It measurably improved DECA's real-world reliability by a large
margin — one measured result showed macro-F1 climbing from 0.841 (raw,
frame by frame) to 0.912 (with the loom's sticky persistence applied) on
the exact same underlying predictions, just organized more sensibly over
time.

**Why it matters:** This is one of the single biggest "free" improvements
in the whole project — it required no new data and no new model, just a
smarter way of reading a sequence of predictions that already existed.

---

### Enter_k / exit_k

**What it means:** These are the two specific tunable numbers that
control DECA's hysteresis: `enter_k` is how many consecutive matching
fault predictions in a row are required before officially declaring a
fault; `exit_k` is how many consecutive healthy predictions in a row are
required before officially clearing a declared fault.

**Where DECA uses it / why it matters:** DECA's default is `enter_k=3` /
`exit_k=2` (with some fault classes given their own custom, individually
tuned values — see Chapter 6). Chapter 8 documents real experiments
adjusting these numbers and carefully measuring the resulting tradeoffs
between "catches faults faster" and "avoids false starts."

---

### Advisory tier / confirmed tier

**What it means:** DECA runs the exact same hysteresis logic *twice* at
once, with two different sets of settings: a fast, looser "advisory" tier
("something may be forming — heads up") and a slower, stricter
"confirmed" tier ("this is now officially declared"). Both run
simultaneously on the same live data.

**Real-life comparison:** Like a hospital that has both an early "keep an
eye on this patient" flag from a nurse's quick, less-certain observation,
and a slower, more thorough "confirmed diagnosis" from a specialist —
both are genuinely useful, at different levels of certainty and urgency.

**Where DECA uses it / why it matters:** This gives a human operator both
an early, if noisier, heads-up and a slower, more trustworthy final
alarm, rather than being forced to pick only one or the other. Chapter 6
covers the measured tradeoff in detail (the advisory tier gives roughly
3.8 frames of extra early warning on average, at the honest cost of being
right only about 27% of the time during that early-only window).

---

### Confidence / soft streak

**What it means:** "Confidence" is how strongly the model believes its own
prediction for a given frame (a number, not just a yes/no). "Soft
streak" is an upgrade to the basic hysteresis idea above: instead of
counting consecutive frames equally (three weak, uncertain frames counts
the same as three strong, confident ones), soft streak adds up the actual
confidence scores — so a few very confident frames can satisfy the
entry requirement faster than several weak, uncertain ones.

**Real-life comparison:** Imagine a hysteresis rule that needs "three
pieces of evidence" to convict, but a soft-streak version instead needs
"enough total conviction," where one extremely strong, rock-solid piece
of evidence might count as much as three weaker, shakier ones combined.

**Where DECA uses it:** DECA's live, promoted configuration uses soft
streak, and it measurably helped specifically the `bgp_route_flap` class
— its F1 score under the loom jumped from 0.790 to 0.874 once soft
streak was turned on, because a strong, confident BGP flap signal no
longer had to sit around waiting for two extra, weaker frames just to
satisfy a rigid frame *count*.

**Why it matters:** This is a great example of a genuinely measured,
honest improvement — the project didn't just guess that this would help
and ship it; it tried the idea, measured a clear before/after difference,
and only then made it the default.

---

## Section 2.8 — Making the model portable and honest

### Schema drift

**What it means:** "Schema" refers to the exact list and names of columns
(features) a model expects to receive. "Schema drift" is what happens
when the data you're trying to feed into an already-trained model has a
*different* set of columns than what the model originally learned from —
for example, because new features were added to the data pipeline after
the model was already trained.

**Real-life comparison:** Imagine handing someone a printed form to fill
out, but the form's questions have since been updated with a few new
extra questions added — an old, already-trained clerk who memorized the
exact old form layout might get confused or crash entirely when handed
the new, slightly different version.

**Where DECA uses it:** This actually caused a real crash in our
pipeline (Chapter 7 mentions this as error #7): after we added the
`vrf_route_count` feature, an already-trained older model, expecting the
old, smaller list of columns, crashed when asked to score data built with
the new, larger list. We fixed this by writing a small helper
(`_align_to_estimator_features`) that automatically fills in any missing
columns a specific saved model still expects, so old and new models can
both keep working side by side against an evolving data pipeline.

**Why it matters:** As a project evolves and adds new features over time,
this kind of mismatch becomes inevitable — planning for it, rather than
being surprised by it, is a sign of a maturing, production-minded
codebase.

---

### SMOTE

**What it means:** SMOTE is a well-known technique for fixing class
imbalance by artificially generating brand-new, synthetic (fake, made-up,
but statistically plausible) examples of a rare class, to balance out the
data before training.

**Real-life comparison:** Imagine, instead of finding more real examples
of a rare bird species to study, someone tries to "pad out" the
collection by digitally blending together features of the few real
photos to invent entirely new, fake bird photos that never actually
existed in nature.

**Where DECA uses it / why it matters:** DECA deliberately **refuses** to
use SMOTE, and this refusal is recorded directly in the project's saved
model files (`smote: false`,
`smote_policy: refused_tier4_temporal_integrity`). The reason: DECA's
features are built from rolling windows over real, chronological time
(slope, acceleration, and so on) — artificially blending fake rows
together would break the real physical relationship between
consecutive time steps that those rolling features depend on, producing
a cosmetically higher score built on dishonest, physically impossible
data. This is one of the project's clearest examples of choosing
integrity over an easy score boost.

---

### Feature attribution / feature importance

**What it means:** Feature attribution is a way of asking a trained model
"of everything you looked at, which specific features mattered most to
your decisions?" — helping humans understand *what the model is actually
paying attention to*, not just what its final answer was.

**Real-life comparison:** Like asking a doctor, after they've made a
diagnosis, "which specific symptoms mattered most to you in reaching that
conclusion?" — useful both for double-checking their reasoning and for
building trust in the diagnosis.

**Where DECA uses it:** `models/fault_classifier/feature_attribution.json`
records exactly this for DECA's classifier — for example, showing that
BGP update-rate rolling statistics and octets slope were among the most
influential features in an earlier version of the model.

**Why it matters:** This kind of transparency is valuable both for
debugging (if a model is paying attention to something that doesn't make
physical sense, that's a red flag worth investigating) and for building
an operator's trust that the model's decisions are grounded in sensible,
explainable evidence.

---

### Recalibration (as distinct from retraining)

**What it means:** "Recalibration," in this project's specific vocabulary,
means only adjusting DECA's decision *thresholds* (Section 2.3, above)
against new data, without retraining any of the underlying trees at all.
This is a much faster, cheaper operation than full retraining.

**Real-life comparison:** Like adjusting a thermostat's target
temperature setting for a new house, without rebuilding the entire
heating system from scratch — the underlying furnace (the trained model)
stays exactly the same; only the specific number it's aiming for
changes.

**Where DECA uses it:** `scripts/deca_recalibrate.py` is DECA's dedicated
tool for exactly this — it's the core mechanism behind Chapter 10's whole
"can this move to ISRO's network quickly" story.

**Why it matters:** This is the fastest, cheapest possible way to try to
adapt DECA to a new environment — worth trying before committing to a
full, much slower retrain.

---

## End of Chapter 2

You've now covered the second major vocabulary this project depends on.
With both glossaries behind you, every later chapter should read far more
smoothly — continue to
[Chapter 3 — The Four Faults We Detect](03_the_four_faults.md).
