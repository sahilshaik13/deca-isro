# DECA repeated-holdout validation — rare-class stability

- **When:** `2026-07-15T15:40:30.626898+00:00`
- **Seeds:** 5 fresh stratified papers `[805253982, 506096788, 1920538996, 1237983757, 1940647057]`
- **Families:** ['plain'] · β=[1.0, 1.5]
- **Challenger (wm/moe) beat plain on:** 0/5 papers
- **Gate PASS:** 0/5 papers

Technique: **repeated holdout validation** with an automated **promotion gate** (demo name: "School Exam"). Ranges below are mean ± std [min, max] across seeds.

## Honest champion config (`plain`, retrained per paper)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.727 ± 0.010  [0.713, 0.742] |
| Mean rare recall | 0.649 ± 0.064  [0.529, 0.719] |
| bgp_route_flap F1 | 0.468 ± 0.022  [0.427, 0.487] |
| vrf_leakage F1 | 0.470 ± 0.041  [0.436, 0.541] |

## Best family per paper (challenger allowed)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.727 ± 0.010  [0.713, 0.742] |
| Mean rare recall | 0.649 ± 0.064  [0.529, 0.719] |
| bgp_route_flap F1 | 0.468 ± 0.022  [0.427, 0.487] |
| vrf_leakage F1 | 0.470 ± 0.041  [0.436, 0.541] |

## Per-seed detail

| Seed | Champion Macro | Best family | Best Macro | Gate |
| --- | ---: | --- | ---: | --- |
| 805253982 | 0.724 | plain | 0.724 | FAIL |
| 506096788 | 0.713 | plain | 0.713 | FAIL |
| 1920538996 | 0.723 | plain | 0.723 | FAIL |
| 1237983757 | 0.742 | plain | 0.742 | FAIL |
| 1940647057 | 0.735 | plain | 0.735 | FAIL |

> Reading: a wide std or low min on a rare class means that class's F1 is **seed-sensitive (noise)**; a tight band means the number is **real**. Promote only when the challenger wins consistently, not on one lucky paper.
