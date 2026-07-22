# Compound fix round 3 — continuation past hard-stop

Round 2 (6+6) completed with GATE PASS but **live-faithful p(truth) flat** (VRF 0.146→0.152, BGP 0.061→0.054). Hard-stop was documented; user asked to continue.

## Schedule

`--counts tunnel_degradation=12,bgp_route_flap=12,congestion_breach=0`

~2× round-2 injection count. Est. 8–9h. Resume via same `--run-id`.

## After campaign

1. `rebuild_unified.py --all-rpi-runs`
2. Isolated mixed retrain → `models/experiments/compound_fix_round_3/candidate/`
3. Live-faithful replay vs original drowning priors (and vs round-2)
4. No automatic promote
