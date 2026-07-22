# Compound fix round 2 — findings

**Isolated to** `models/experiments/compound_fix_round_2/` · **promoted untouched** (`5165d46d87ee135b`).

## What was tried

- Campaign `compound_fix_r2_20260722_0435` with `--counts tunnel_degradation=6,bgp_route_flap=6,congestion_breach=0`
- Rationale: {
  "tunnel_degradation": "6 compounds \u2248 +78 tunnel rows \u2192 ~135 (~2.4\u00d7 prior 57); doubles+ quiet leg without thousands of rows",
  "bgp_route_flap": "6 compounds \u2248 +96 BGP rows \u2192 ~285 (~1.5\u00d7 prior 189); one focus-sized block matching prior bgp_vrf_focus unit \u2014 full double (~12) exceeds this time-box with tunnel",
  "congestion_breach": "0 \u2014 not a diagnosed drowning failure"
}
- Logged fault types: `{'bgp_route_flap': 6, 'vrf_leakage': 12, 'tunnel_degradation': 6}`
- Lake fold after `rebuild_unified.py --all-rpi-runs`: **3210** rows; `_z_*` cols in lake: **56**; ortho `_z_*` present: `['bgp_flap_count_z_slope', 'bgp_flap_count_z_rolling_std', 'bgp_flap_count_z_rolling_mean', 'bgp_flap_count_z_accel', 'bgp_flap_count_w2m_z_slope', 'bgp_flap_count_w2m_z_rolling_std']`
- New-camp labels: `{'healthy': 2037, 'vrf_leakage': 1017, 'tunnel_degradation': 87, 'bgp_route_flap': 69}`
- Mixed retrain via `deca_school_exam_train` on the **full** lake (existing + new) — not new-rows-only.
- No promote; candidate under `candidate/`.

## Promotion gate (honest same-paper)

| Metric | Value |
|---|---|
| Candidate macro-F1 | 0.7610403726329684 |
| Bar (max champion same-paper, manifest 0.717) | 0.7563230659873174 |
| Champion same-paper macro-F1 | 0.7563230659873174 |
| Rare recall | 0.5967364674806175 |
| Family / β | wm / 1.0 |
| GATE | PASS |

## Live-faithful before/after (failing legs)

| Leg | Prior max p(truth) | Candidate max p(truth) | Δ | Diagnosis | Meaningful rise? |
|---|---|---|---|---|---|
| `tunnel_vrf__station2__vrf_leakage` | 0.146 | 0.15246973931789398 | 0.006469739317893991 | present_but_outvoted | False |
| `bgp_vrf__station1__bgp_route_flap` | 0.061 | 0.05377078801393509 | -0.0072292119860649096 | zeroed_out | False |

### Full replay snapshot (candidate)

- `tunnel_vrf__station2__vrf_leakage`: max_p=0.15246973931789398 mean_p=0.032736166436128165 diag=present_but_outvoted preds={'tunnel_degradation': 14, 'healthy(gate)': 10}
- `tunnel_vrf__station1__tunnel_degradation`: max_p=0.9619216322898865 mean_p=0.7637113634409616 diag=would_win_raw preds={'tunnel_degradation': 13, 'healthy': 2, 'healthy(gate)': 1}
- `bgp_vrf__station1__bgp_route_flap`: max_p=0.05377078801393509 mean_p=0.016283490320867195 diag=zeroed_out preds={'healthy(gate)': 14, 'vrf_leakage': 14}
- `bgp_vrf__station2__vrf_leakage`: max_p=0.923747181892395 mean_p=0.6134217272823056 diag=would_win_raw preds={'vrf_leakage': 17, 'healthy(gate)': 6, 'healthy': 1}

### Promoted (frozen) replay on same windows

- `tunnel_vrf__station2__vrf_leakage`: max_p=0.14631664752960205 mean_p=0.020813774049505202 diag=zeroed_out preds={'tunnel_degradation': 12, 'healthy(gate)': 11, 'healthy': 1}
- `tunnel_vrf__station1__tunnel_degradation`: max_p=0.941591203212738 mean_p=0.6518739405546512 diag=would_win_raw preds={'tunnel_degradation': 13, 'healthy(gate)': 2, 'healthy': 1}
- `bgp_vrf__station1__bgp_route_flap`: max_p=0.061477601528167725 mean_p=0.0153521795956684 diag=zeroed_out preds={'vrf_leakage': 13, 'healthy': 9, 'healthy(gate)': 6}
- `bgp_vrf__station2__vrf_leakage`: max_p=0.9148913621902466 mean_p=0.5739463516511023 diag=would_win_raw preds={'vrf_leakage': 16, 'healthy': 5, 'healthy(gate)': 3}

### Control FA rate (live-faithful)

- **promoted**: `{'station1': {'n': 39, 'fa_frac': 0.07692307692307693, 'pred_counts': {'healthy(gate)': 35, 'tunnel_degradation': 3, 'healthy': 1}}, 'station2': {'n': 39, 'fa_frac': 0.15384615384615385, 'pred_counts': {'healthy(gate)': 22, 'healthy': 11, 'bgp_route_flap': 4, 'tunnel_degradation': 2}}}`
- **candidate**: `{'station1': {'n': 39, 'fa_frac': 0.15384615384615385, 'pred_counts': {'healthy(gate)': 27, 'healthy': 6, 'tunnel_degradation': 6}}, 'station2': {'n': 39, 'fa_frac': 0.10256410256410256, 'pred_counts': {'healthy(gate)': 28, 'healthy': 7, 'tunnel_degradation': 3, 'bgp_route_flap': 1}}}`

## Verdict

**Hard stop.** After this one time-boxed round, neither failing leg’s live-faithful p(truth) rose meaningfully above baseline.

What was tried did not close the gap. This remains a documented, root-caused, time-boxed limitation: a compound class-imbalance / feature-interaction problem large enough that fully closing it would need more compound campaign volume than fits in the remaining timeline.

No second round and no alternate weighting scheme proposed.

## Blind scoreboard

| Window | Prior | This round |
|---|---|---|
| control | on record | see replay / notes |
| tunnel+VRF | VRF miss (p≈0.15) | see table above |
| BGP+VRF | BGP miss (p≈0.06) | see table above |

Promoted path unchanged: `{'sha16_before': '5165d46d87ee135b', 'sha16_after': '5165d46d87ee135b', 'unchanged': True}`.


---

## Continuation

User requested continue past hard-stop. Round 3 running: `compound_fix_r3_20260722_0958` with tunnel=12,bgp=12 → `models/experiments/compound_fix_round_3/`.
