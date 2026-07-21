# DECA Blind Live-Network Test

The ultimate test: let the models fly blind on the physical CE-PE-CE lab. The
network randomly creates circumstances with **no schedule the models can lean
on**; the models must predict *what* is forming, *when* it will breach (ETA),
and *how bad* it will get (severity) in real time. Afterwards we open the seal
and compare what the network actually did against what the models declared.

This is not the scheduled `deca_fault_campaign.py` (that runs a known quota for
data generation). This harness is adversarial and sealed.

## Pieces

| Script | Role |
| --- | --- |
| [`scripts/deca_blind_chaos.py`](../scripts/deca_blind_chaos.py) | The adversary. Randomly injects faults + benign near-misses via the proven `deca_fault_campaign` injectors, and seals the ground truth. |
| [`scripts/deca_live_operator.py`](../scripts/deca_live_operator.py) | The model, flying blind. Polls Prometheus, rebuilds training-identical features, runs gate -> classifier -> soft-streak loom -> LSTM ETA -> circumstance -> severity, streams a NOC feed. |
| [`scripts/deca_blind_scorecard.py`](../scripts/deca_blind_scorecard.py) | The judge. Reconciles declarations vs sealed truth; prints a scorecard, writes `scorecard.json`, renders a Cursor Canvas. Ships a `--selfcheck` that verifies its own logic against a fixture. |
| [`scripts/deca_blind_aggregate.py`](../scripts/deca_blind_aggregate.py) | Pools N graded runs into mean ± spread + a combined-sample estimate. One night is noise; quote a range. |
| [`scripts/deca_blind_ensemble_head.py`](../scripts/deca_blind_ensemble_head.py) | Trains the `wm` companion head so the operator can run the plain+wm agreement ensemble. |
| [`scripts/deca_blind_test.sh`](../scripts/deca_blind_test.sh) | Hands-off orchestrator (operator + chaos + scorecard). Forwards args after `--` to chaos (e.g. `--control`); `DECA_OP_ENSEMBLE=1` arms the ensemble operator. |
| [`scripts/deca_live_common.py`](../scripts/deca_live_common.py) | Shared PromQL, run layout, physical-severity definition. |

Everything for a run lives under `data/rpi-net/live/<run_id>/`:

- `ground_truth.sealed.jsonl` — what the network actually did. **The operator never reads this.**
- `declarations.jsonl` — every model state transition (class, ETA, severity, confidence).
- `bgp_update_samples.csv` — real BGP update-rate telemetry the chaos run stamps (a signal, not a label) so the operator can see flaps the lab Prometheus cannot scrape.
- `scorecard.json` — the graded result.
- `run_meta.json` — sealed seed + parameters for audit.

## What the models report per circumstance

- **What** — the fault class (`congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage`).
- **When (ETA)** — LSTM time-to-breach in minutes at the moment of declaration.
- **Severity** — physical impact from live telemetry (packet loss / jitter / throughput deviation vs a healthy baseline), bucketed low / medium / high — directly comparable to what actually happened.
- **Two tiers** — an early **advisory** ("may be forming", yellow) and a robust **confirmed** ("declared", red).

## Pre-flight (before 11pm)

```bash
bash lab/deca_diagnostic.sh               # expect all green (see STATION_NETWORK_SETUP.md)
curl -s localhost:9090/-/ready            # Prometheus healthy
```

Optional rehearsal of the harness software with no hardware:

```bash
python3 scripts/deca_blind_chaos.py   --run-id rehearsal --simulate --min-events 3 --max-events 3
python3 scripts/deca_live_operator.py --run-id rehearsal --simulate --sim-ticks 90
python3 scripts/deca_blind_scorecard.py --run-id rehearsal --no-prom
```

## Run it at 11pm

### Two terminals (recommended — watch the model think)

Terminal A (the model):

```bash
python3 scripts/deca_live_operator.py --run-id blind_2359 --start-at 23:00
```

Terminal B (the blind adversary):

```bash
python3 scripts/deca_blind_chaos.py --run-id blind_2359 --start-at 23:00 --minutes 90
```

Both hold until 23:00 local, then run. Watch Terminal A: links go yellow
(advisory) then red (confirmed) as faults build, with the ETA counting down and
severity climbing. When Terminal B prints `BLIND CHAOS COMPLETE`, stop the
operator with Ctrl-C.

### One command (hands-off)

```bash
scripts/deca_blind_test.sh blind_2359 23:00 90
# operator feed -> data/rpi-net/live/blind_2359/operator_feed.log  (tail -f to watch)
```

## Grade it

```bash
python3 scripts/deca_blind_scorecard.py --run-id blind_2359
```

Prints the scorecard and writes a Cursor Canvas you can open beside the chat:
`deca-blind-test.canvas.tsx`. The scorecard reports, per circumstance: detected
or missed, predicted vs actual class, advisory/confirmed lead time before
breach, LSTM ETA error, and severity agreement — plus false alarms (baited
near-misses and spurious) so early warnings aren't rewarded for crying wolf.

### How to read the grade (two deliberate caveats)

- **Class is scored on the *first* confirmed declaration** (`class_accuracy`) —
  what an operator would actually act on. A softer `class_accuracy_eventually`
  reports whether the confirmed tier *ever* named the right class in-window, so
  you can see when the model self-corrected after an initial wrong call.
- **`advisory_lead` is class-agnostic** — it measures "something is forming",
  not "correct early warning". `advisory_class_correct` per event tells you
  whether that early advisory actually named the right class.
- **Severity** is reported two ways: coarse bucket agreement *and* a continuous
  `severity_pearson_r` between predicted and actual raw physical-impact scores —
  a stronger, more specific claim than "the bucket matched".

### Verify the judge

The grader is an automated judge; trust its aggregates only as far as its own
logic is verified. Before quoting numbers:

```bash
python3 scripts/deca_blind_scorecard.py --selfcheck   # asserts judge logic on a fixture
```

This builds a synthetic run with hand-computed answers (a clean hit, an
eventually-correct hit, a miss, a baited near-miss false alarm, a spurious
alarm) and asserts `grade()` reproduces every one.

## One run isn't enough — aggregate across nights

A single 60-minute run swings hard on which few circumstances happen to land in
it (the same statistical-noise problem the School Exam solved with
`--report-seeds 5`). Run several nights with **different seeds** and report a
range, not one scorecard, before putting any number in front of a judge.

```bash
# every archived run
python3 scripts/deca_blind_aggregate.py --glob 'data/rpi-net/blind-tests/*/scorecard.json'
# or specific run-ids
python3 scripts/deca_blind_aggregate.py --run-id blind_a blind_b blind_c
```

It prints per-metric mean ± sd and [min .. max] across runs, plus pooled
estimates recomputed on the combined event sample, and warns while `<3` runs.

## All-healthy control run (clean false-positive rate)

Mixing near-misses into runs that also contain real faults tests
discrimination, but doesn't give one unambiguous "how often does it cry wolf
when *nothing* is wrong" number. The control mode injects **zero real faults** —
only healthy baseline plus periodic near-miss baits — so every confirmed alarm
is a false positive.

```bash
scripts/deca_blind_test.sh control_2359 "" 60 -- --control --near-misses 4
# or directly:
python3 scripts/deca_blind_chaos.py --run-id control_2359 --minutes 60 --control --near-misses 4
```

## Deterministic specificity exam (preferred FP instrument)

Full design + runbook: [`DECA_SPECIFICITY_EXAM.md`](DECA_SPECIFICITY_EXAM.md).  
Live results: [`results/SPECIFICITY_EXAM_V1.md`](results/SPECIFICITY_EXAM_V1.md).

Random `--control` rests/holds make residual tunnel/congestion and near-miss
failures hard to examine. Prefer the fixed playlist exam:

```bash
source .venv/bin/activate
scripts/deca_blind_test.sh specificity_exam_v1 "" 40 -- \
  --playlist scripts/playlists/specificity_exam_v1.json
```

Phases: warm → calm → nm01 → calm → nm02 → calm → nm03 → calm (fixed holds).
Chaos stamps `exam_phases.jsonl`; after the scorecard,
`deca_blind_exam_report.py` enforces the pass bar (0 near-miss FA, 0 calm
spurious, 0 BGP confirms). See [`scripts/playlists/specificity_exam_v1.json`](../scripts/playlists/specificity_exam_v1.json).

## Notes and safety

- **Blindness** is enforced by discipline: the operator opens only Prometheus and the BGP pulse file, never the sealed truth.
- **Cleanup** is guaranteed: the chaos scheduler routes SIGINT/SIGTERM and its hard time budget through `clear_all_faults()`, and clears after every injection, so the lab is left clean.
- **Warm-up**: features need ~10 min of history before the loom is meaningful; the first ~10 min after arming is baseline.
- **BGP live gap**: the lab Prometheus has no FRR BGP counter, so flaps are only visible via the stamped `bgp_update_rate` pulses. Validate one flap end-to-end before arming. The operator always densifies a **zero** BGP grid when no pulses are stamped (calm/control), and refuses to *confirm* `bgp_route_flap` without pulse evidence — see control post-mortem in [`results/BLIND_TEST_CONTROL_20260716_1924_60m.md`](results/BLIND_TEST_CONTROL_20260716_1924_60m.md).
- **Timestamps** are UTC end-to-end; the operator and chaos must run against the same clock (they do, on the lab LAN).
- **Do not** run the laptop `lab/run_traffic.sh` and this test's baseline traffic at the same time (see STATION_NETWORK_SETUP.md §9).

## Archived test runs

Completed runs are copied under `data/rpi-net/blind-tests/<run_id>/` with a full write-up in [`docs/results/`](results/).

| Run | Type | Report |
| --- | --- | --- |
| `blind_20260716_1537_60m` (60 min, 16 Jul 2026) | Adversarial blind | [`BLIND_TEST_20260716_1537_60m.md`](results/BLIND_TEST_20260716_1537_60m.md) |
| `blind_20260716_1924_60m` (60 min, 16 Jul 2026) | Adversarial blind (ultimate) | [`BLIND_TEST_20260716_1924_60m.md`](results/BLIND_TEST_20260716_1924_60m.md) |
| `control_20260716_1924_60m` (60 min, 16 Jul 2026) | All-healthy control | [`BLIND_TEST_CONTROL_20260716_1924_60m.md`](results/BLIND_TEST_CONTROL_20260716_1924_60m.md) |
| `specificity_exam_v1` (17–18 Jul) | Exam FAIL → **PASS** | [`SPECIFICITY_EXAM_V1.md`](results/SPECIFICITY_EXAM_V1.md) |
| `blind_20260718_0848_60m` (60 min, 18 Jul 2026) | Adversarial blind (ultimate) | [`BLIND_TEST_20260718_0848_60m.md`](results/BLIND_TEST_20260718_0848_60m.md) |
| `control_20260718_0848_60m` (60 min, 18 Jul 2026) | All-healthy control (clean) | [`BLIND_TEST_CONTROL_20260718_0848_60m.md`](results/BLIND_TEST_CONTROL_20260718_0848_60m.md) |
| **Aggregate (through 18 Jul)** | Range across nights | [`BLIND_TEST_AGGREGATE_20260718.md`](results/BLIND_TEST_AGGREGATE_20260718.md) |

Index: [`data/rpi-net/blind-tests/README.md`](../data/rpi-net/blind-tests/README.md)

Canvas: `deca-blind-results.canvas.tsx`

## CLI reference

`deca_blind_chaos.py`: `--run-id --minutes --min-events --max-events --near-misses --rest-min --rest-max --compound-prob --seed --start-at HH:MM --simulate --time-scale --control`

`deca_live_operator.py`: `--run-id (required) --interval --lookback-min --start-at HH:MM --simulate --sim-ticks --hosts --ensemble`

`deca_blind_scorecard.py`: `--run-id --no-prom --selfcheck`

`deca_blind_aggregate.py`: `[scorecards...] --glob --run-id ... --out`

`deca_blind_ensemble_head.py`: `--boost --holdout-frac --exam-seed --holdout-policy --min-disagree --warn-disagree --out`

## Compound / overlapping faults (#3)

Real cascades rarely arrive in isolation. `--compound-prob P` makes each event
slot fire, with probability `P`, an **overlapping** pair instead of one isolated
fault: a PE1 fault (congestion / tunnel / bgp) **and** the PE2 `vrf_leakage` leak
injected concurrently in separate threads. Different hosts means no `tc qdisc`
collision, and the scorecard (which clips detection windows per host) grades each
leg cleanly. Both legs share a `compound_group` id in the sealed truth and are
flagged as `[cascade …]` in the scorecard.

```bash
python3 scripts/deca_blind_chaos.py --run-id blind_x --minutes 90 --compound-prob 0.4
```

## Ensemble: plain + wm agreement (#5)

The operator normally runs one classifier family (`plain`, the champion). With
`--ensemble` it also runs an independently-trained `wm` head (cluster + mildly
regularized booster) and **requires both heads to agree on the fault class
before a confirmed declaration** — disagreement holds the tier at advisory.

The companion is **not** fit on the full lake. `deca_blind_ensemble_head.py`
carves a stratified School Exam holdout, trains `wm` only on the study pool,
and scores both heads on the same paper. It records agreement / disagreement
and how many plain-alone false faults the agree gate would suppress, and
aborts if the heads are identical or agreement gating helps nothing.

Latest offline exam (seed 42, 6 330 held-out rows):

| | Macro-F1 | Rare recall |
| --- | --- | --- |
| plain (promoted) | 0.815 | 0.791 |
| wm (study-only) | 0.792 | 0.736 |

Agreement 96.6%, disagreement 3.4%. Agree gating suppressed **91 / 521**
(17%) of plain-alone false faults on that paper. Heads are highly correlated —
`--ensemble` is a **mild** false-alarm filter, not a strong independent second
opinion. Treat any blind-live gain as small until multi-night A/B confirms it.

```bash
python3 scripts/deca_blind_ensemble_head.py                 # train + exam-score (once)
python3 scripts/deca_live_operator.py --run-id blind_x --ensemble
# or hands-off:
DECA_OP_ENSEMBLE=1 scripts/deca_blind_test.sh blind_x "" 90 -- --compound-prob 0.4
```

Every declaration records `ensemble_wm_class` and `ensemble_agree`; the NOC feed
shows `[wm✓]` on agreement and `[wm≠:… → held]` when a confirm was suppressed.
Exam report lands at `models/fault_classifier/ensemble_exam_report.json`.
To quantify the live effect, run one blind seed with and without `--ensemble`
and compare `spurious_false_alarms` / `near_miss_false_alarms` in the two
scorecards.
