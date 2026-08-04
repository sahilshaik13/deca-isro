# SOP: Rain Fade / Physical Path Degradation (Q2 1A / 1B / 1C)

## Description
GRE preferred underlay (`gre-te-core` via single CORE `10.1.3.1`) shows rising one-way latency, jitter, or loss while eth0 backup stays comparatively clean. Lab injection: stepped `netem` delay on the GRE path (Mauritius-distance / weather analogue). Maps to severity tiers **1A** (early), **1B** (actionable), **1C** (worst-case / red-gate eligible).

## Telemetry signatures
- `sdwan_path_latency_ms{path="gre",host="station1"}` climbing toward TT&C SLA **25 ms**
- `sdwan_path_jitter_ms{path="gre"}` and `sdwan_path_loss_pct{path="gre"}` elevated
- `sdwan_path_latency_ms{path="eth0"}` remains near baseline (differential diagnosis vs CPU/crypto)
- Q1 LSTM ETA ≤ **120 s** with hot GRE latency → Decide rail `seed-preemption`

## Diagnostic Steps
1. Confirm GRE vs eth0 split on Prom / Decide rail summary (not a single-path brownout of both).
2. On PE1 (`station1`): check IPsec SAs still up (`swanctl --list-sas`) — rain fade is underlay, not SA death.
3. Verify CORE reachability (`ping` / OSPF neighbors on `10.1.3.1`).
4. Rule out CPU class: `cpu_usage_user` / `cpu_usage_system` should not be the dominant spike.

## Mitigation
1. **Immediate (HITL):** Approve Decide rail → controller `force_path` to **eth0** (OSPF cost /32 steer on **PE1**).
2. **Short-term:** Keep human override until GRE latency recovers under `exit_k` stability (10 clean polls).
3. **Do not** clear force while ETA remains red or GRE loss ≥ mission thresholds.
4. **Rollback:** `clear_force` / `reset_autonomy` only after GRE ≤ SLA with hysteresis satisfied.

## Notes
- eth0 backup **bypasses CORE** (direct PE↔PE); preferred GRE uses single CORE P.
- Compound chaos may stack rain fade with BGP/CPU — see `chaos_compound.md`.
