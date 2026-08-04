# SOP: BGP Route Flapping
## Description
Triggered by rapid successive BGP UPDATE/WITHDRAW messages or hold-timer expirations, indicating unstable peer reachability.

## Diagnostic Steps
1. Identify the unstable peer: `show ip bgp summary`.
2. Check route dampening status: `show ip bgp dampening dampened-paths`.
3. Verify Layer 1/2 stability (interface flaps, optical signal degradation).

## Mitigation
1. **Immediate:** If the peer is wildly unstable, administratively shut down the session to allow network convergence.
2. **Configuration:** Enable BGP route dampening if not already active.
3. **Rollback:** `clear ip bgp <peer-ip>` once the underlying transport issue is resolved.
