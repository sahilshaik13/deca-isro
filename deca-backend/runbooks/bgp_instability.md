# BGP flap — routing unstable

**What it is:** Routes keep refreshing or shaking. The preferred path can briefly disappear or bounce.

**Keywords:** bgp_flap, bgp_route_flap, route_flap, 3A, 3B, bgp_flap_count, clear bgp soft, 10.1.3.1, gre-te-core

## Plain English
- Symptom: BGP soft-clears / peer resets toward the core neighbor (`10.1.3.1`).
- Prom shows `bgp_flap_count` rising (use the **rate**, not the raw counter alone).
- **3A** = mild flaps (watch). **3B** = severe (act if timing is at risk).
- Decide class is usually `bgp_route_flap`.

## What to look at
- Rising flap rate on station1.
- GRE may get bumpy; eth0 often steadier.
- If latency is high but flaps are flat → prefer rain fade runbook.

## What to do
1. When flaps stop, restore BGP neighbor and preferred path.  
   (ensures GRE is UP)
2. For **3B** with timing risk: **Approve backup** to eth0.
3. Do not hammer extra BGP clears during an active severe flap window.
4. Clear the override only after flaps quiet and the path is stable.

## Mild vs severe
- **3A only, latency calm** → observe; do not Approve just for mild flaps.
- **3B + latency toward 25 ms** → protect mission first (Approve), debug BGP second.
