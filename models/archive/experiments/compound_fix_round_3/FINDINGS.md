# Compound fix round 3 — findings

**Isolated to** `models/experiments/compound_fix_round_3/` · **promoted untouched** (`5165d46d87ee135b`).

Continuation past round-2 hard-stop at user request (2× volume on the same pairings).

## What was tried

- Campaign `compound_fix_r3_20260722_0958` with `--counts tunnel_degradation=12,bgp_route_flap=12,congestion_breach=0`
- Rationale: {
  "tunnel_degradation": "12 compounds \u2248 +174 tunnel rows on top of r2 (~87) \u2192 ~260 from r2+r3 new camps; ~2\u00d7 the r2 quiet-leg add that failed to move p(VRF)",
  "bgp_route_flap": "12 compounds \u2248 +138 BGP rows on top of r2 (~69) \u2192 ~207 from new camps; double the r2 BGP block that left p(BGP) flat",
  "congestion_breach": "0 \u2014 not a diagnosed drowning failure"
}
- Logged fault types: `{'tunnel_degradation': 12, 'vrf_leakage': 24, 'bgp_route_flap': 12}`
- Lake fold after `rebuild_unified.py --all-rpi-runs`: **6165** rows; `_z_*` cols in lake: **56**; ortho `_z_*` present: `['bgp_flap_count_z_slope', 'bgp_flap_count_z_rolling_std', 'bgp_flap_count_z_rolling_mean', 'bgp_flap_count_z_accel', 'bgp_flap_count_w2m_z_slope', 'bgp_flap_count_w2m_z_rolling_std']`
- New-camp labels: `{'healthy': 3780, 'vrf_leakage': 1845, 'bgp_route_flap': 387, 'tunnel_degradation': 153}`
- Mixed retrain via `deca_school_exam_train` on the **full** lake (existing + new) — not new-rows-only.
- No promote; candidate under `candidate/`.

## Promotion gate (honest same-paper)

| Metric | Value |
|---|---|
| Candidate macro-F1 | 0.7642628596687526 |
| Bar (max champion same-paper, manifest 0.717) | 0.7611748461499295 |
| Champion same-paper macro-F1 | 0.7611748461499295 |
| Rare recall | 0.6107633097862922 |
| Family / β | wm / 1.0 |
| GATE | PASS |

## Live-faithful before/after (failing legs)

| Leg | Prior max p(truth) | Candidate max p(truth) | Δ | Diagnosis | Meaningful rise? |
|---|---|---|---|---|---|
| `tunnel_vrf__station2__vrf_leakage` | 0.146 | 0.09168339520692825 | -0.05431660479307174 | zeroed_out | False |
| `bgp_vrf__station1__bgp_route_flap` | 0.061 | 0.16986504197120667 | 0.10886504197120667 | present_but_outvoted | False |

### Full replay snapshot (candidate)

- `tunnel_vrf__station2__vrf_leakage`: max_p=0.09168339520692825 mean_p=0.015747458062833175 diag=zeroed_out preds={'tunnel_degradation': 13, 'healthy(gate)': 11}
- `tunnel_vrf__station1__tunnel_degradation`: max_p=0.9533407092094421 mean_p=0.7827973732601095 diag=would_win_raw preds={'tunnel_degradation': 14, 'healthy(gate)': 1, 'healthy': 1}
- `bgp_vrf__station1__bgp_route_flap`: max_p=0.16986504197120667 mean_p=0.02134430241130758 diag=present_but_outvoted preds={'vrf_leakage': 18, 'healthy(gate)': 9, 'healthy': 1}
- `bgp_vrf__station2__vrf_leakage`: max_p=0.9307633638381958 mean_p=0.593508556834422 diag=would_win_raw preds={'vrf_leakage': 17, 'healthy(gate)': 5, 'healthy': 2}

### Promoted (frozen) replay on same windows

- `tunnel_vrf__station2__vrf_leakage`: max_p=0.14631664752960205 mean_p=0.020813774049505202 diag=zeroed_out preds={'tunnel_degradation': 12, 'healthy(gate)': 11, 'healthy': 1}
- `tunnel_vrf__station1__tunnel_degradation`: max_p=0.941591203212738 mean_p=0.6518739405546512 diag=would_win_raw preds={'tunnel_degradation': 13, 'healthy(gate)': 2, 'healthy': 1}
- `bgp_vrf__station1__bgp_route_flap`: max_p=0.061477601528167725 mean_p=0.0153521795956684 diag=zeroed_out preds={'vrf_leakage': 13, 'healthy': 9, 'healthy(gate)': 6}
- `bgp_vrf__station2__vrf_leakage`: max_p=0.9148913621902466 mean_p=0.5739463516511023 diag=would_win_raw preds={'vrf_leakage': 16, 'healthy': 5, 'healthy(gate)': 3}

### Control FA rate (live-faithful)

- **promoted**: `{'station1': {'n': 39, 'fa_frac': 0.07692307692307693, 'pred_counts': {'healthy(gate)': 35, 'tunnel_degradation': 3, 'healthy': 1}}, 'station2': {'n': 39, 'fa_frac': 0.15384615384615385, 'pred_counts': {'healthy(gate)': 22, 'healthy': 11, 'bgp_route_flap': 4, 'tunnel_degradation': 2}}}`
- **candidate**: `{'station1': {'n': 39, 'fa_frac': 0.1794871794871795, 'pred_counts': {'healthy(gate)': 25, 'healthy': 7, 'tunnel_degradation': 7}}, 'station2': {'n': 39, 'fa_frac': 0.1794871794871795, 'pred_counts': {'healthy(gate)': 27, 'healthy': 5, 'tunnel_degradation': 5, 'bgp_route_flap': 2}}}`

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
