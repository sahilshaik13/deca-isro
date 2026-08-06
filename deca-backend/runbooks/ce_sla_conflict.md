# SOP: CE↔CE SLA Policy Conflict / Bandwidth Surge (NOC)

## Description
A **lower-SLA (Bronze/Silver) CE** surges bandwidth (quiet **2–3 Mbps** → **~15–20 Mbps**) and endangers a **higher-SLA (Gold) CE** on the same PE/WAN. Mentor framing: NOC uptime / rogue consumer — **not** a security appliance.

Canonical tiers: [`docs/EDGE_POLICY_LAYERS.md`](../../docs/EDGE_POLICY_LAYERS.md) §2.

| Role | Default lab binding |
| --- | --- |
| Rogue | `ce-mauritius` (Bronze 90%) or `ce-mcf` |
| Victim | `ce-a` NRSC (Gold 99.9% / TT&C) |

## Telemetry signatures
- `ce_util_mbps{ce="ce-mauritius"}` climbing past fire threshold (≥15 Mbps)
- Shared path `sdwan_path_util_mbps` / GRE latency rising; optional `sdwan_policy_conflict=1`
- Decide: `root_cause=ce_sla_conflict`, fields `rogue_ce` / `victim_ce` / `*_sla`

## Diagnostic Steps
1. Confirm which CE is surging (`ce_util_mbps` or PE `veth-pe-*` rates).
2. Confirm victim is Gold TT&C path (NRSC / `ce-a`) still in SLA or approaching breach.
3. Check whether inject `scripts/inject_ce_sla_conflict.sh` is still running.

## Mitigation
1. **HITL Approve** → playbook protects victim (`force_path` to backup if underlay congested).
2. Stop rogue burst: `bash scripts/inject_ce_sla_conflict.sh --clear`.
3. Document which NOC operator Approved (multi-operator audit).

## Demo
```bash
# API-only (safe during protocol campaign)
bash scripts/demo_ce_sla_conflict_seed.sh

# Full inject when station1 injectors are free
bash scripts/inject_ce_sla_conflict.sh
bash scripts/demo_ce_sla_conflict_seed.sh
```
