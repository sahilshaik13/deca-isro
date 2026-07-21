# DECA — white paper draft

**Working title:** Closing Catch‑9 cry-wolf on a live CE–PE–CE lab without declaring detection solved  
**Status:** draft skeleton — fill after durability exam v2 + VRF recall loop  
**Audience:** technical reviewers / program judges who will confuse “exam PASS” with “system works” unless told otherwise

---

## Abstract *(one paragraph)*

DECA is a multi-head fault classifier with a soft-streak temporal loom, flown blind on a physical three-station CE–PE–CE lab. Over two days (17–18 Jul 2026) we closed the operational false-alarm failure mode (Catch‑9): a deterministic specificity exam and an all-healthy control both reached **zero** near-miss false alarms and **zero** calm spurious confirms, after a BGP densify/evidence gate and a targeted near-miss data campaign. The same window shows a **measured detection cost** — adversarial blind detection fell from 100% to 75% on a missed PE2 VRF leak — the expected precision–recall trade when aborted VRF onsets are taught to stay healthy. This paper reports both numbers, the verification pattern (test the fix, report what you found), and the remaining durability and recall work.

---

## 1. Problem

- NOC trust dies on false confirms under healthy conditions faster than on missed rare faults.
- Prior live control: **21 spurious confirms / hour** (18 invented BGP).
- Near-miss baits also confirmed — discrimination failure.

## 2. Method (short)

- Lab: CE–PE–CE Pi fabric; Prometheus telemetry; sealed chaos / playlist harness.
- Models: School Exam multiclass head + soft-streak loom + BGP evidence gate.
- Instruments: random control → BGP fix check → **specificity exam** (FP only) → adversarial blind (detection) → paired control.

## 3. Two-day arc (evidence)

| Step | Finding |
| --- | --- |
| BGP densify + evidence gate | Spurious 21 → 5; BGP invention **0**; near-miss FA **worse** (4/4) — reported plainly |
| Specificity exam v1 | FAIL (NM 1/3, spurious 2) — phase-pinned |
| Data campaign + retrain | Quotas met; promote Macro-F1 0.722; soft loom 0.840 |
| Exam v1 re-sit | **PASS** |
| Ultimate control | **0** NM FA, **0** spurious |
| Ultimate blind | Detect **3/4**; NM **0/2**; spurious **3**; miss = PE2 VRF |

**Framing sentence for any pitch:** we closed the false-alarm problem, independently verified; that came with a measured detection cost we are chasing.

## 4. Durability & anti-memorization

- Exam PASS is **n=2** on one fixed playlist — thinner than the three-night blind aggregate.
- Playlist **v2** (different timings / four baits) never informed a fix — durability check *(results TBD)*.
- Campaign duration WARN hand-checked: not a collapsed-timestamp bug.

## 5. Limits

- Severity: unusable on latest night (bucket 0%, Pearson −0.85) — out of ship claim.
- VRF recall vs specificity: any boundary move must re-pass exam + control.
- n=3 blinds: quote ranges, not a single point estimate.

## 6. Conclusion *(draft)*

Specificity on the defined trust instruments is real and independently verified. Detection remains strong in aggregate (**12/13**) with an explicit VRF sensitivity cost. Closing that cost without reopening cry-wolf is the remaining engineering question; severity is a separate unfinished product.

---

## Pointers

| Doc | Role |
| --- | --- |
| [`DECA_RESULTS_OVERVIEW.md`](DECA_RESULTS_OVERVIEW.md) | Cumulative scoreboard |
| [`results/BLIND_TEST_AGGREGATE_20260718.md`](results/BLIND_TEST_AGGREGATE_20260718.md) | Live aggregate + two-claim verdict |
| [`results/SPECIFICITY_EXAM_V1.md`](results/SPECIFICITY_EXAM_V1.md) | Exam FAIL→PASS |
| [`DECA_BLIND_TEST.md`](DECA_BLIND_TEST.md) | Harness runbook |
| [`DECA_TEST_SCORES.md`](DECA_TEST_SCORES.md) | Offline scores |
