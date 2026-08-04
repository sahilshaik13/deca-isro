# SOP: VRF Route Leakage
## Description
Detected by sudden spikes in `vrf_route_count` or cross-VRF traffic anomalies. Indicates unauthorized route-target (RT) importing.

## Diagnostic Steps
1. Verify VRF routing tables: `show ip route vrf <name>`.
2. Inspect BGP VPNv4 import/export policies: `show running-config vrf <name>`.
3. Look for overlapping IP space causing blackholes.

## Mitigation
1. **Immediate:** Remove unauthorized `route-target import` statements from the affected VRF.
2. **Short-term:** Hard-clear the BGP VPNv4 session to flush leaked routes: `clear ip bgp * soft in`.
3. **Rollback:** Monitor `vrf_route_count` to ensure route isolation is re-established.
