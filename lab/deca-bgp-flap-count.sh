#!/usr/bin/env bash
# Live FRR BGP route-refresh churn counter for Telegraf inputs.exec (Influx line protocol).
# Install: sudo install -m 0755 lab/deca-bgp-flap-count.sh /usr/local/bin/
set -euo pipefail

NEIGHBOR="${1:-10.1.3.1}"

count_refresh() {
  local neighbor="$1"
  # Telegraf's exec plugin runs as the unprivileged `_telegraf` user; the FRR
  # vty socket is root/frrvty-only, so this needs the sudoers NOPASSWD drop-in
  # installed alongside this script (see lab/deca-deploy.sh Tier 5b section).
  #
  # `inject_bgp_route_flap()` (deca_fault_campaign.py) runs `clear bgp <nbr>
  # soft`, which is a route-refresh, NOT a session reset -- verified live
  # 2026-07-21: connectionsEstablished/connectionsDropped never move on a soft
  # clear (that would have been a phantom signal, same trap as the pre-fix
  # VRF injector). What DOES move is the neighbor's own message counters:
  # routeRefreshSent/Recv jump immediately on every soft clear (verified +6
  # sent / +3 recv over 3 test clears), while keepalives/opens stay flat
  # outside of real session churn. Sum of Sent+Recv gives one monotonic
  # counter whose *rate* (rolling slope, via engineer_features) spikes only
  # during an actual flap burst -- the live control-plane analog of
  # vrf_route_count for VRF. No jq on the Pis; parse with python3 (present).
  sudo vtysh -c "show bgp neighbor ${neighbor} json" 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print(0)
    sys.exit(0)
n = d.get(sys.argv[1], {})
ms = n.get("messageStats", {})
print(int(ms.get("routeRefreshSent", 0)) + int(ms.get("routeRefreshRecv", 0)))
' "${neighbor}"
}

emit() {
  local neighbor="$1" val
  val="$(count_refresh "${neighbor}")"
  val="${val:-0}"
  printf 'bgp_flap_count,neighbor=%s value=%s\n' "${neighbor}" "${val}"
}

# station1's only VPNv4 peer relevant to inject_bgp_route_flap() today is
# station3 (10.1.3.1, its loopback) -- see docs/DECA_ROI_TIERS.md Tier 5.
emit "${NEIGHBOR}"
