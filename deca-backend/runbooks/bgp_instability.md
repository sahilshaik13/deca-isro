# SOP: BGP Instability / Route Flap (Q2 3A / 3B)

## Description
Control-plane instability on the preferred underlay: rapid BGP soft-clears, UPDATE/WITHDRAW storms, or GRE link bounce against the CORE neighbor. Lab injection: `scripts/inject_bgp_flap.sh` on **PE1** (`station1`) toward neighbor **`10.1.3.1`** (single CORE), optional `--link-bounce` on `gre-te-core`. Maps to severity **3A** (mild flap rate) and **3B** (severe — red-gate eligible with hot path).

Distinct from the shorter generic `bgp_flap.md`: this book is the **Q2 severity / Decide-rail** playbook for classifier labels `bgp_mild` / `bgp_severe` and alert class `bgp_route_flap`.

## Severity tiers (lab)
| Code | Rule (1 Hz `bgp_flap_count` delta) | HITL red? |
| --- | --- | --- |
| **3A** | Flap rate ≥ **0.2**/s and &lt; **1.0**/s | Advisory (yellow unless compounded) |
| **3B** | Flap rate ≥ **1.0**/s | **Yes** — with Q1 ETA ≤ 120 s + hot latency |

Prom counter: `bgp_flap_count{job="deca_kafka_telemetry_bridge",host="station1"}` on Prom `:9090` (Pi). GNS3 uses `job="deca_gns3_fabric",host="gns3-pe1"` on `:9091`.

## Telemetry signatures
- Rising `bgp_flap_count` (use **rate**, not raw level — counter is cumulative)
- Path latency/jitter may spike during soft-clear or link-bounce cycles; eth0 often steadier if only GRE BGP is hit
- CPU usually **not** the dominant signal (vs 2A/2B)
- Q2 root → Decide `alert_class=bgp_route_flap`; Q1 may still seed preemption when ETA red + **3B**

## Diagnostic Steps
1. Confirm Prom flap **rate** and Q2 severity (`3A` vs `3B`) on the Decide summary / `q3_prom_snapshot`.
2. On PE1: `vtysh -c "show bgp summary"` — which neighbor is bouncing (`10.1.3.1` CORE).
3. Check whether inject is still running; clear leftovers: `bash scripts/inject_bgp_flap.sh --clear --host station1`.
4. Differentiate from rain fade: if GRE latency is high but `bgp_flap_count` rate is flat → prefer `rain_fade.md`.
5. If GRE link was bounced: `ip -br link show gre-te-core` must be **UP** after clear (script trap restores UP).

## Mitigation
1. **Immediate (lab):** Stop flap inject (`--clear`); ensure `gre-te-core` UP.
2. **HITL (3B + TT&C threat):** Approve Decide rail → `force_path` to **eth0** on **PE1** (OSPF cost `/32` steer) so mission traffic leaves the flapping GRE/BGP path.
3. **Control-plane (ops):** Soft-clear is already the inject — do **not** hammer additional `clear bgp` during an active 3B window unless isolating a stuck peer; prefer dampening / admin-down only if peer is permanently bad.
4. **Short-term:** Hold human override until flap rate returns to ~0 and GRE meets `exit_k` stability.
5. **Rollback:** `clear_force` / `reset_autonomy` only after BGP quiet **and** path SLA recovered.

## Prioritization (vs other classes)
- **3B + rising GRE latency toward 25 ms** → treat as TT&C preemption (`ttc_sla_preempt.md`); steer first, debug BGP second.
- **3A alone, latency cold** → observe / clear inject; do not Approve solely on mild flaps.
- **BGP + CPU compound** → see `chaos_compound.md`; still protect TT&C latency before chasing FRR CPU.

## Notes
- Protocol L3 iterations are ~1 h BGP inject each; expect 3A/3B labels in those windows.
- eth0 backup bypasses CORE; steering there isolates mission from GRE BGP churn without fixing the peer.
- Generic FRR CLI tips remain in `bgp_flap.md`; use **this** book when Q2 says `bgp_mild` / `bgp_severe` / `3A` / `3B`.
