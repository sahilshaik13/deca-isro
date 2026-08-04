# SOP: Hub-and-Spoke Congestion Breach
## Description
Triggered when ifInOctets/ifOutOctets exhibit sustained acceleration above rolling baseline, typically indicating QoS queue saturation or microbursts.

## Diagnostic Steps
1. Verify interface utilization on the affected PE router.
2. Check QoS drops: `show policy-map interface`.
3. Identify top talkers using NetFlow/IPFIX data.

## Mitigation
1. **Immediate:** Apply temporary rate-limiting (policing) to the offending VRF or source IP.
2. **Short-term:** Re-route non-critical traffic over alternate SD-WAN underlays (e.g., Broadband/LTE).
3. **Rollback:** Remove rate-limit once the microburst subsides.
