# Compound series rollup — 2026-07-19

Forced dual-fault: PE1 leg + `vrf_leakage` on station2 (`--compound-prob 1.0`).

**Gate verification (operator_feed.log):**

| Run | Echo origin-lock | VRF origin-lock |
| --- | ---: | ---: |
| `blind_compound_bgp_route_flap_*` | on | **off** (shipped mid-series) |
| `blind_compound_congestion_breach_*` | on | on |
| `blind_compound_tunnel_degradation_*` | on | on |

| PE1 leg | Run | Detect | Class | NM FA | Spur | Notes |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| bgp_route_flap | `blind_compound_bgp_route_flap_20260719_1239_40m` | 2/2 | 50% | 0/1 | 0 | **Inverse contamination:** station1 BGP leg scored as `vrf_leakage` |
| congestion_breach | `blind_compound_congestion_breach_20260719_1256_40m` | 1/2 | 50% | 0/1 | 3 | VRF leg **missed**; spur = 3× station2 VRF outside windows (not echo) |
| tunnel_degradation | `blind_compound_tunnel_degradation_20260719_1317_40m` | 1/2 | 50% | 0/1 | 0 | VRF leg **missed** |

Artifacts under `data/rpi-net/blind-tests/blind_compound_*`.
