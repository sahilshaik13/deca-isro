# DECA repeated-holdout validation — rare-class stability

- **When:** `2026-07-15T12:56:35.761008+00:00`
- **Seeds:** 3 fresh stratified papers `[1646872011, 1793109396, 266670594]`
- **Families:** ['plain'] · β=[1.0]
- **Challenger (wm/moe) beat plain on:** 0/3 papers
- **Gate PASS:** 0/3 papers

Technique: **repeated holdout validation** with an automated **promotion gate** (demo name: "School Exam"). Ranges below are mean ± std [min, max] across seeds.

## Honest champion config (`plain`, retrained per paper)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.714 ± 0.012  [0.702, 0.730] |
| Mean rare recall | 0.625 ± 0.050  [0.554, 0.665] |
| vrf_leakage F1 | 0.466 ± 0.029  [0.436, 0.505] |
| bgp_route_flap F1 | 0.408 ± 0.024  [0.378, 0.435] |

## Best family per paper (challenger allowed)

| Metric | Range across seeds |
| --- | --- |
| Macro-F1 | 0.714 ± 0.012  [0.702, 0.730] |
| Mean rare recall | 0.625 ± 0.050  [0.554, 0.665] |
| vrf_leakage F1 | 0.466 ± 0.029  [0.436, 0.505] |
| bgp_route_flap F1 | 0.408 ± 0.024  [0.378, 0.435] |

## Per-seed detail

| Seed | Champion Macro | Best family | Best Macro | Gate |
| --- | ---: | --- | ---: | --- |
| 1646872011 | 0.702 | plain | 0.702 | FAIL |
| 1793109396 | 0.710 | plain | 0.710 | FAIL |
| 266670594 | 0.730 | plain | 0.730 | FAIL |

> Reading: a wide std or low min on a rare class means that class's F1 is **seed-sensitive (noise)**; a tight band means the number is **real**. Promote only when the challenger wins consistently, not on one lucky paper.
