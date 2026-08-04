# SOP: IPSec Tunnel Degradation
## Description
Detected via high jitter, packet loss, or abnormal rekey duration (IKE Phase 1/2 negotiation latency).

## Diagnostic Steps
1. Check IPSec SA status: `ipsec statusall`.
2. Verify MTU/MSS mismatch issues (ping with df-bit set).
3. Look for replay window drops or ESP sequence errors.

## Mitigation
1. **Immediate:** Force a manual SA rekey: `ipsec down <conn> && ipsec up <conn>`.
2. **Short-term:** Failover traffic to secondary VPN gateway if packet loss exceeds 5%.
3. **Rollback:** Revert to primary gateway during the next maintenance window.
