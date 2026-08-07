# BGP session tips (generic)

**What it is:** Short checklist for unstable BGP peers. For the live demo / Q2 labels **3A/3B**, prefer `bgp_instability.md`.

**Keywords:** bgp_flap, show bgp summary, dampening, peer

## What to do
1. Find the unstable peer (`show bgp summary` / `vtysh`).
2. Check if the underlay link itself is flapping.
3. If the peer is wild: isolate it, then soft-clear after the transport is fixed.
4. In the DECA lab demo, stop the inject with  
   `bash scripts/inject_bgp_flap.sh --clear --host station1`  
   and Approve backup if Decide says timing is at risk.
