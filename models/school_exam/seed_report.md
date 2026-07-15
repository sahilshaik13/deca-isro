# DECA repeated-holdout validation — rare-class stability

- **When:** `2026-07-15T16:38:31.104894+00:00`
- **Seeds:** 3 fresh stratified papers `[944499042, 1688123164, 1768569819]`
- **Families:** ['plain'] · β=[1.0]
- **Challenger (wm/moe) beat plain on:** 0/3 papers
- **Gate PASS:** 2/3 papers

Technique: **repeated holdout validation** with an automated **promotion gate** (demo name: "School Exam"). Ranges below are mean ± std [min, max] across seeds.

## Honest champion config (`plain`, retrained per paper)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.748 ± 0.008  [0.737, 0.756] |
| Mean rare recall | 0.621 ± 0.136  [0.507, 0.813] |
| vrf_leakage F1 | 0.472 ± 0.022  [0.442, 0.495] |
| bgp_route_flap F1 | 0.522 ± 0.029  [0.482, 0.549] |

## Best family per paper (challenger allowed)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.748 ± 0.008  [0.737, 0.756] |
| Mean rare recall | 0.621 ± 0.136  [0.507, 0.813] |
| vrf_leakage F1 | 0.472 ± 0.022  [0.442, 0.495] |
| bgp_route_flap F1 | 0.522 ± 0.029  [0.482, 0.549] |

## Per-seed detail

| Seed | Champion Macro | Best family | Best Macro | Gate |
| --- | ---: | --- | ---: | --- |
| 944499042 | 0.737 | plain | 0.737 | FAIL |
| 1688123164 | 0.752 | plain | 0.752 | PASS |
| 1768569819 | 0.756 | plain | 0.756 | PASS |

> Reading: a wide std or low min on a rare class means that class's F1 is **seed-sensitive (noise)**; a tight band means the number is **real**. Promote only when the challenger wins consistently, not on one lucky paper.
