# Compound drowning — dry-run findings

**Isolated to** `models/experiments/compound_drowning_fix/` · **promoted model untouched** (`5165d46d87ee135b`).

## Verdict

Both scorecard misses on the Tier-5c compound blinds are **zeroed-out / feature-interaction** failures under a **live-faithful** (sliding 25-min lookback) replay — **not** “present but outvoted.”

That **disqualifies** step 2 (per-class score normalization / inverse-frequency reweight via existing `tune_thresholds` / class-weight machinery). Raising a near-baseline probability with thresholds cannot recover a class the head is not scoring.

## Evidence (live-faithful)

| Blind | Leg | Scorecard | max p(truth) | Winning live class | Orthogonal metric |
|---|---|---|---|---|---|
| tunnel+VRF | VRF @ station2 | MISS | 0.15 (mean 0.02) | `tunnel_degradation` (max p≈0.98) | `vrf_route_count` rolling mean 0→4 while p(VRF) stays ~0.01 |
| tunnel+VRF | tunnel @ station1 | HIT | 0.94 | tunnel | — |
| BGP+VRF | BGP @ station1 | MISS | 0.06 (mean 0.02) | `vrf_leakage` (max p≈0.75) | `bgp_flap_count` 100% populated & moving; p(BGP) never rises |
| BGP+VRF | VRF @ station2 | HIT | 0.91 | VRF | — |

Live `operator_feed.log` matches: station2 never advisories VRF during tunnel compound (tunnel only + echo-hold); station1 never advisories BGP during BGP+VRF (VRF only).

**Batch full-window replay is misleading** for the tunnel+VRF VRF leg (batch max p(VRF)≈0.99). Prefer `live_faithful_*` artifacts.

## Training support (post-exporter compound camps)

From `diagnosis_report.json`:

- tunnel/cong+VRF: **57** `tunnel_degradation` vs **1224** `vrf_leakage` (4259 rows)
- bgp+VRF: **189** `bgp_route_flap` vs **1104** `vrf_leakage` (3147 rows)

Thin co-occurrence volume for the quieter leg under simultaneous loud traffic features is the plausible root — trees never learned to condition on the orthogonal metric when tunnel/VRF-like traffic features are elevated.

## Sensor placement

`bgp_flap_count` is **station1-only by design**. Current blinds put `bgp_route_flap` on **station1**, so the BGP miss is **not** a sensor gap. A station2 BGP secondary leg **would** be structurally undetectable without a mirrored station2 exporter — report as instrumentation if that topology appears; do not model around a missing sensor.

## Blind scoreboard (comparable to prior rounds)

No candidate fix was scored — step 2 disqualified; no promote.

| Window | Prior result | This experiment |
|---|---|---|
| control | on record | unchanged (no fix) |
| tunnel+VRF | 1/2 detected (VRF miss) | unchanged — miss explained as zeroed-out |
| BGP+VRF | 1/2 detected (BGP miss) | unchanged — miss explained as zeroed-out |

## What would actually move the needle

1. Small dedicated compound campaign for the still-failing pairings (tunnel↔VRF and BGP↔VRF with co-moving orthogonal + traffic features).
2. Mixed retrain (Tier-B style) after that data exists.
3. Optional: station2 BGP flap exporter **only if** injections move to station2.

**Honest:** threshold/class-weight dry-runs would not have moved these blinds. That negative result is the useful deadline signal.
