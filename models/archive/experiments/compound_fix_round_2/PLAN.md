# Compound fix round 2 — plan (time-boxed)

## Failure modes (from compound_drowning_fix)

1. **tunnel+VRF / VRF@s2**: live-faithful max p(VRF)≈0.15 (near baseline) while tunnel≈0.98
2. **BGP+VRF / BGP@s1**: live-faithful max p(BGP)≈0.06 while VRF≈0.75

Root cause: compound-window class imbalance + feature interaction (not thresholds).

## Weighted schedule (smallest corrective counts)

```
--counts tunnel_degradation=6,bgp_route_flap=6,congestion_breach=0
```

| PE1 leg | Prior compound-camp rows | Est. rows / compound | This round | After (est.) | Why |
|---|---|---|---|---|---|
| tunnel_degradation | 57 | ~13 | **6** | ~135 (~2.4×) | Doubling+ the quiet leg without thousands of rows; 4 was tried in consolidate and still left 57 total |
| bgp_route_flap | 189 | ~16 | **6** | ~285 (~1.5×) | One more focus-sized block (matches prior `bgp_vrf_focus` unit of 6). Full double (~12) would be a second full focus campaign alone; out of this time-box with tunnel |
| congestion_breach | — | — | **0** | — | Not a diagnosed drowning failure |

Wall-clock: 12 compounds × ~20–26 min (rest+inject+settle) ≈ **4–5 hours**. Resume supported via same `--run-id`.

Each compound also adds ~90 VRF-labelled frames under overlap — that is intentional (teaches the co-occurrence), not "general volume" of isolated VRF.

## Pipeline (no promote)

1. Campaign → `data/rpi-net/runs/<run-id>/`
2. `rebuild_unified.py --all-rpi-runs` (regenerates `_z_*`)
3. Mixed retrain via `deca_school_exam_train` dry-run (full lake = old + new); artifacts only under this dir
4. Live-faithful replay on tunnel+VRF + BGP+VRF blinds; control + hit legs for regression
5. Hard stop if p(truth) stays near baseline — document limitation, no second round
