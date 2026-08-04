# SOP: Crypto / CPU Exhaustion (Q2 2A / 2B)

## Description
PE crypto or control-plane CPU saturates (lab: `stress-ng` / inject scripts on `station1`). IPsec ESP and FRR compete for cycles → latency and loss climb even when underlay RTT is healthy. Severity **2A** (early), **2B** (red-gate eligible with hot path).

## Telemetry signatures
- `cpu_usage_user` and/or `cpu_usage_system` on bridge metrics for `host="station1"` sustained high
- GRE **and** eth0 latency may both degrade (unlike pure rain fade)
- `mem_used_percent` may rise; BGP counters usually stable unless CPU starves FRR
- Q2 class / severity often `crypto_cpu_exhaustion` / **2B**

## Diagnostic Steps
1. Compare Prom CPU vs path latency: if eth0 and GRE both bad with high CPU → prefer this SOP over rain fade.
2. SSH PE1: `top` / `pidstat` — look for `charon`, `swanctl`, `stress-ng`, FRR spikes.
3. Confirm inject still active: `scripts/inject_cpu_stress.sh` state; clear if leftover from a failed campaign iter.
4. Check controller still scraping (`:9280/metrics`) so AAR can act after Approve.

## Mitigation
1. **Immediate:** Clear CPU inject if lab-owned (`inject_cpu_stress.sh --clear --host station1`).
2. **HITL:** If TT&C ETA ≤ 120 s, Approve steer to healthier underlay (often eth0) on **PE1**.
3. **Short-term:** Reduce non-mission load; avoid loading heavy LLM weights on brain during L0 capture.
4. **Rollback:** After CPU returns to baseline and path SLAs clear `exit_k`, `clear_force`.

## Notes
- Do not treat as rain fade alone when eth0 is equally hot.
- Protocol L2 iterations inject ~1 h CPU stress per iter — expect 2B signatures during those windows.
