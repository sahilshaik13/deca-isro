# SOP: SD-WAN Policy Drift
## Description
Identified when localized router configurations diverge from the central controller intent, leading to unexpected path selection or SLA failures.

Authoritative intent: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md).
Lab drift inject flag: `data/rpi-net/sdwan_policy_drift.flag` (controller forces misconfigured underlay).

## Diagnostic Steps
1. Compare local running-config against controller template / policy catalog.
2. Verify OSPF/BGP metric manipulations that override controller logic.
3. Check AAR SLA thresholds (TT&C ≤25/5/0.1%; Payload ≤80/15/2%; `enter_k=3` / `exit_k=10`).
4. Confirm `sdwan_human_override` / `reset_autonomy` state if a prior sim left a pin.

## Mitigation
1. **Immediate:** `POST /action` `{"op":"reset_autonomy"}` and clear leftover netem on `gre-te-core`.
2. **Short-term:** If sync fails, manually remove conflicting static routes or local route-map entries; remove drift flag.
3. Re-verify with `lab/deca_sdwan_verify.sh` / dashboard Mission policy panel.
