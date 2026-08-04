# DECA lab topology (air-gapped RAG)

Physical multi-site Pi lab (not EVE-NG). Authoritative addressing & restore:
[`docs/STATION_NETWORK_SETUP.md`](../../docs/STATION_NETWORK_SETUP.md).
Master SD-WAN policies: [`docs/DECA_SDWAN_POLICY_RULES.md`](../../docs/DECA_SDWAN_POLICY_RULES.md).

## Hosts

| Host | Role | Lab IP |
| --- | --- | --- |
| station1 | PE1 / NRSC + Mauritius CEs; AAR probe origin | 192.168.50.10 |
| station2 | PE2 / SAC + MCF CEs | 192.168.50.20 |
| station3 | CORE / P — **single** CORE loopback `10.1.3.1` (dual-P netns scripts exist, **not applied**) | 192.168.50.30 |
| brain (desktop) | Operator desktop / Prom `:9090` (Pi) + `:9091` (GNS3) / SD-WAN ctrl `:9280` / orchestrator / Kafka | 192.168.50.1 |

Sites (logical): CORE, SAC, NRSC, Mauritius (distant), MCF Hassan.

**Dual fabric:** Same NOC also drives a GNS3 sim fabric (external drive). Active fabric `pi`\|`gns3` via `GET/POST /api/v1/fabric`. See [`dual_fabric_telemetry.md`](./dual_fabric_telemetry.md) · [`lab/gns3/TOPOLOGY.md`](../../lab/gns3/TOPOLOGY.md).

## Planes

| Plane | What |
| --- | --- |
| Underlay | `gre-te-core` (OSPF cost 5) preferred; `eth0` (cost 50) backup; LDP on GRE |
| TE | OSPF-TE TED + pathd SR-TE BSID 40001/40002 |
| Overlay | IPsec ESP `deca-sdwan` PE1↔PE2 (zero-trust; no cleartext WAN) |
| VRF | `vrf-mission` (TT&C + Payload AAR); `vrf-admin` = PS13 vrf-default (admin→eth0) |
| AAR | **Aligned:** TT&C ≤25/5/0.1%; Payload ≤80/15/2%; Gold 99.9%. `enter_k=3` / `exit_k=10`; TT&C preempts. Edge layers: CE/PE/P — `docs/EDGE_POLICY_LAYERS.md` |
| Telemetry | Dual Flow 2 — topics `sdwan_telemetry_pi` / `_gns3` → Prom `:9090` / `:9091` |

## Fault origin hosts (ground truth)

| Fault | Origin host |
| --- | --- |
| congestion_breach | station1 |
| tunnel_degradation | station1 |
| bgp_route_flap | station1 |
| policy_drift | station1 |
| vrf_leakage | station2 |

Mauritius and MCF are **not** fault-injection targets (distance / multi-site baselines).
