# SOP: Compound / Chaos Faults (Held-out Validation)

## Description
Overlapping or sequenced faults (rain fade + CPU, tunnel + BGP, etc.) used in the 12 h chaos leg and blind rechecks. Single-class playbooks can mislead — treat classifier output as a **hypothesis**, not ground truth.

## Telemetry signatures
- Mixed Q2 probabilities / oscillating severity labels across windows
- GRE and eth0 both degraded, or BGP flaps coincident with latency spikes
- `bgp_flap_count` rising while CPU or loss also elevated
- Q1 ETA may chatter yellow↔red as compound effects interact

## Diagnostic Steps
1. List concurrent injects: rain fade, CPU stress, BGP flap scripts — clear leftovers first.
2. Snapshot Prom: latency gre/eth0, loss, CPU, BGP in one 30–60 s window.
3. Prefer **differential**: which signal moved first? Underlay-first → physical; CPU-first → crypto; UPDATE storms → BGP.
4. Do not auto-merge multiple Decide alerts into one Approve without reading severity.

## Mitigation
1. **Stabilize:** Clear non-essential injects; restore single-fault conditions if validating a class.
2. **HITL:** Steer to the underlay that still meets TT&C if any path is viable; else fail-closed (no cleartext).
3. **BGP compound:** If flaps dominate, follow `bgp_flap.md` (dampen / admin-down peer) **and** consider path steer.
4. **Document:** Note compound nature in operator note when Approving so postmortems stay honest.

## Notes
- Protocol chaos is **held-out** (`train: false`) — do not fold blindly into Q2 training labels.
- Q3 should cite multiple runbooks when retrieval returns mixed SOPs; say so explicitly.
