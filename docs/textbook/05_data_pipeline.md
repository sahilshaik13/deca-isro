# Chapter 5 — The Data Pipeline

## The big question this chapter answers

Where do all the numbers DECA learns from actually come from, and how do
they turn into something a machine learning model can actually study?
This chapter follows that journey end to end: from real measurements on
our lab (and some genuinely public internet data), through a single
important script, into one final, clean table of numbers the model is
trained on.

---

## Two very different sources of data, blended together

DECA's training data comes from two genuinely different places, and it
is important to understand why both are needed and what each one is
actually for.

### Source 1 — Our own lab, the only source of real fault labels

Everything DECA knows about what `congestion_breach`, `tunnel_degradation`,
`bgp_route_flap`, and `vrf_leakage` actually look like comes **only**
from our own physical lab (Chapter 4). This makes sense once you think
about it: nobody publishes a public dataset of "here is exactly when a
real company's VRF accidentally leaked traffic into the wrong
department." That kind of specific, labeled fault information simply
doesn't exist anywhere else — we had to go create it ourselves, safely,
in a controlled lab, using deliberate fault injection (Chapter 3).

### Source 2 — Public internet data, only for "what does normal look like"

Separately, we also pulled in several genuinely public, real-world
internet datasets — but importantly, **only** to help teach DECA a
broader, less lab-specific idea of what "healthy" traffic looks like, not
to teach it about faults (since these public sources don't come with the
kind of specific fault labels we need).

| Public source | What it actually is | What we use it for |
| --- | --- | --- |
| RouteViews / RIPE RIS | Real, publicly archived BGP routing update records from the actual global internet | Building BGP update-rate and path-change features, as `healthy` context |
| RIPE Atlas | A real, public global network of measurement probes reporting real ping/latency data | A broad, real-world latency baseline, sampled down to about 188,000 rows so it doesn't overwhelm our lab's own data |
| Cisco DevNet sandbox | A publicly available Cisco network simulation/sandbox environment | An additional real, healthy-traffic sample from a genuinely different kind of network setup |
| MAWI Samplepoint-F | A well-known, long-running public internet traffic-monitoring project (manually sampled, since automated bulk downloading isn't permitted by the site's own rules) | A rough, real-world magnitude check — used only for calibration, not for training variance |
| IODA / BGP routing outage labels | Public records of real, large-scale internet outage events, tagged by network (ASN) | Currently kept only as "provenance" — held in reserve, not yet actually used as training labels, because their time window doesn't currently overlap with our other telemetry |

**Why we bother with this at all:** if DECA's entire idea of "what is
normal" came *only* from our one small lab, a reasonable critic could
argue the model has simply overfit to our lab's own particular quirks
and would have no idea what "normal" looks like on a different, real
network. Blending in genuinely public, real-world "healthy" traffic from
totally different networks is a real, verifiable step toward proving
DECA's sense of "normal" isn't narrowly overfit to one small lab.

### What we deliberately chose *not* to do: synthetic/fake data

We deliberately never generate fake, made-up telemetry rows just to
"pad out" the dataset artificially, and we deliberately never use SMOTE
(explained fully in Chapter 2) to invent synthetic examples of rare fault
classes. Both would risk breaking the real, physical, chronological
relationships (the slope, acceleration, and rolling statistics — Chapter
2) that our features actually depend on, in exchange for a cosmetically
higher-looking score that wouldn't reflect anything real. This refusal is
recorded directly and permanently in the model's own saved files
(`smote: false`), as a deliberate, standing policy — not an oversight.

---

## Step 1 — Generating real lab data: the campaign scripts

To get real, labeled examples of each fault, we run automated "campaign"
scripts that repeatedly and safely inject controlled faults into the lab,
on a schedule, while recording exactly when each one started and stopped.

| Script | What it does |
| --- | --- |
| `deca_fault_campaign.py` | The main workhorse — injects a controlled amount of each of the four faults, resting 15–25 minutes of normal traffic between each one, until a target quota (e.g. "10 of each fault type") is reached |
| `deca_specificity_data_campaign.py` | A more targeted campaign focused specifically on "near-miss" events (brief blips that look like the start of a fault but abort before anything actually breaks — see Chapter 2's discussion of overfitting-adjacent lessons and Chapter 7's mistake #2) |
| `deca_circumstance_campaign.py` | A carefully balanced campaign (5 events × 4 fault types = 20 total) that specifically records three distinct phases per event — the "circumstance" (run-up), the "breach" (the fault itself), and the "recovery" — used to teach a separate model about *when a fault's situation starts to exist*, not just when it fully happens |

Every one of these scripts is **resumable** — if the campaign gets
interrupted (Chapter 7's mistake #7 tells the story of a real power
outage doing exactly this), you can simply re-run the same command with
the same run-id, and it will pick up exactly where it left off, rather
than losing hours of already-completed work or, worse, silently
duplicating events.

Each finished campaign run produces its own folder under
`data/rpi-net/runs/<run_id>/`, containing:

| File | What it contains |
| --- | --- |
| `fault_injection_log.csv` | The exact start/stop time of every fault that was injected during this run |
| `network_telemetry.csv` | The raw, long-form measurements pulled from Prometheus during this run |
| `campaign_state.json` | The campaign's own progress/checkpoint bookkeeping, used for resuming |
| `campaign_run.log` | A full, timestamped, human-readable log of everything the campaign did |

---

## Step 2 — Turning raw runs into one trainable table: `rebuild_unified.py`

This is arguably the single most important script in the entire
project. Its job is to take every campaign run's raw data, plus all the
public data sources, and turn all of it into one single, clean,
consistent table of features and labels that the model can actually be
trained on.

### What it actually does, step by step

1. **Reads every campaign run's raw telemetry**, plus every public data
   source, one at a time.
2. **Cleans it** — this includes an important, deliberate step called
   `_clean_telemetry`, which keeps only a specific, known "allow-list" of
   trusted measurement columns, and discards anything unexpected. This is
   a safety net: if some measurement is broken, mislabeled, or simply not
   something the model is supposed to see, it gets filtered out here
   rather than silently leaking into training.
3. **Runs `engineer_features`** on every metric — this is the function
   that builds all of DECA's smart features (rolling mean, rolling
   standard deviation, slope, acceleration, at both the long 10-minute
   and short 2-minute window, plus, more recently, the baseline-relative
   z-score versions — all explained in full in Chapter 2). This turns
   roughly a dozen raw measurements into over a hundred engineered
   feature columns.
4. **Assigns the `unified_label`** — the single, final answer column the
   model is trained to predict. This step is described fully below.
5. **Writes two output files**: `deca_unified_raw.parquet` (a less
   processed, longer-form version, useful for the Prophet forecasting
   models, Chapter 2 and Chapter 6) and, most importantly,
   `deca_unified_dataset.parquet` — the final, fully feature-engineered
   table the classifier is actually trained on.

### The `unified_label` — turning many different logs into one consistent answer

Different data sources record "what happened" in slightly different raw
formats — a campaign log might say `fault_type = bgp_route_flap`, a
public dataset row might have no fault information at all. The
`unified_label` column is the one, single, consistent answer column that
every row in the final table gets, no matter which source it came from:

| Source | How `unified_label` gets decided |
| --- | --- |
| Lab campaign rows, inside a real fault's time window | The specific fault name (`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, or `vrf_leakage`) |
| Lab campaign rows, outside any fault window | `healthy` |
| All public data rows | `healthy` (since none of these public sources come with fault labels we can trust) |
| "Near-miss" / aborted fault attempts (`precursor_aborted`) | `healthy` (a brief blip that never actually became a real fault is correctly *not* labeled as one — see Chapter 7's mistake #2) |

A related column, `is_anomaly`, is simply `1` whenever `unified_label` is
anything other than `healthy`, and `0` otherwise — this is exactly the
target the binary anomaly gate (Chapter 2 and Chapter 6) is trained on.

### How to run it, and when

```bash
python scripts/rebuild_unified.py --rpi-run <new_run_id>
```

You run this after every new campaign finishes, to fold its data into the
existing lake. There's also an `--all-rpi-runs` option to rebuild
completely from scratch using every run ever recorded — used
occasionally to make sure nothing has drifted or gone stale.

---

## Step 3 — What the final table actually looks like

The final file, `deca_unified_dataset.parquet` (Chapter 1 explains the
Parquet file format), is a single large table where:

- **Each row** is one moment in time, on one specific station, with all
  of its measurements and engineered features.
- **Each column** is either a raw measurement, an engineered feature
  (slope, rolling mean, etc., including the newer z-score companions), or
  a label (`unified_label`, `is_anomaly`, and a few others used by
  specialized models like the circumstance existence head, Chapter 6).
- As of the writing of this book, this table has grown to **tens of
  thousands of rows** and roughly **112 feature columns** (after the
  baseline-relative feature expansion described in Chapter 7 doubled the
  original 56).

This single file is what every one of DECA's training scripts actually
reads from — it is the true, single source of truth the whole machine
learning side of the project is built on top of.

---

## Why we cannot skip any of these steps

It's worth being explicit about why this whole, fairly elaborate pipeline
exists rather than something simpler:

- **Skipping real lab data** would mean DECA never learns what a real
  fault genuinely looks like — public data alone has no fault labels to
  learn from.
- **Skipping public "healthy" data** would leave DECA's sense of normal
  narrowly tied to just our one small lab's own quirks.
- **Skipping feature engineering** and just handing the model raw numbers
  would leave DECA blind to *shape* and *change over time* — the single
  most important kind of clue for catching a developing fault early (see
  Chapter 2's explanation of slope and acceleration).
- **Skipping the cleaning/allow-list step** would risk silently letting
  broken or nonsensical data corrupt training without anyone noticing.
- **Skipping a consistent `unified_label`** would leave the model with no
  single, trustworthy answer key to learn from at all.

---

## Continue

Now that you understand where the data comes from and how it's shaped,
Chapter 6 explains what actually happens to that data once it reaches the
model itself — the full architecture of DECA's "brain." Continue to
[Chapter 6 — The Model Architecture](06_model_architecture.md).
