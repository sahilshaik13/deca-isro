import config


def create_runbooks():
    RUNBOOKS_DIR = config.RUNBOOKS_DIR
    RUNBOOKS_DIR.mkdir(parents=True, exist_ok=True)

    runbooks_data = {
        "congestion.md": """# SOP: Hub-and-Spoke Congestion Breach
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
""",
        
        "bgp_flap.md": """# SOP: BGP Route Flapping
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
""",

        "tunnel_degradation.md": """# SOP: IPSec Tunnel Degradation
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
""",

        "policy_drift.md": """# SOP: SD-WAN Policy Drift
## Description
Identified when localized router configurations diverge from the central controller intent, leading to unexpected path selection or SLA failures.

## Diagnostic Steps
1. Compare local running-config against controller template.
2. Verify OSPF/BGP metric manipulations that override controller logic.
3. Check application-aware routing (AAR) SLA thresholds.

## Mitigation
1. **Immediate:** Force a configuration sync from the central controller to the edge device.
2. **Short-term:** If sync fails, manually remove conflicting static routes or local route-map entries.
""",

        "vrf_leakage.md": """# SOP: VRF Route Leakage
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
"""
    }

    print(f"Generating RAG data in '{RUNBOOKS_DIR}'...\n")
    for filename, content in runbooks_data.items():
        filepath = RUNBOOKS_DIR / filename
        filepath.write_text(content, encoding="utf-8")
        print(f"Created {filename}")
        
    print("\n🎉 All runbooks generated successfully!")

if __name__ == "__main__":
    create_runbooks()