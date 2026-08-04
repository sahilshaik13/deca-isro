# Jury demo — dual-fabric NOC (Pi + GNS3)

**One line:** Fabric → Fault → Decide → Approve.  
**Mentor sentence:** Same iperf3 + NetEM + BGP/CPU/util fault book and aligned SLAs on Pi and GNS3 — one SD-WAN policy, one predictive feature space. **No TRex.**

## Setup (before jury)

1. Pi campaign **idle** (or leave Pi faults alone if campaign still owns BGP)
2. Dashboard http://localhost:3000 · API :8000 — **same SLA budgets** on both fabrics (TT&C ≤25/5/0.1% · Payload ≤80/15/2%)
3. Dual Flow 2 up: `bash lab/telemetry-pipeline/verify_dual_prom.sh` (Pi `:9090` · GNS3 `:9091`)
4. GNS3 project **DECA** started; exporter `:9275`; marker `DECA_READY`
5. Chaos layer: **iperf3 + NetEM** (+ CPU / BGP / util) → branch CE → IPsec → PE → vrf-mission → CORE → DC/Hub
6. Approve pushes controller rules onto the **active** fabric PE1
7. Fault shapes: [`docs/shared_fault_book.json`](shared_fault_book.json)

## Script (≈8 minutes)

| Step | Action | Say |
| --- | --- | --- |
| 1 | Show **Simulation source = Pi** | Live Raspberry Pi SD-WAN fabric |
| 2 | (If campaign idle) click **Rain fade** | NetEM delay ramp on PE1 GRE |
| 3 | Point at **Decide** rail | Q1 ETA + Q2 class + concerns before SLA breach |
| 4 | **Approve** | Controller steers backup eth0 / gre |
| 5 | Switch **Simulation source → GNS3** | Same Decide math, sim fabric |
| 6 | Click **CE SLA conflict** | Bronze iperf surge vs Gold TT&C (rogue/victim) |
| 7 | Optional **Loss ramp** | NetEM loss 0→3.5% (Payload SLA) |
| 8 | Show Chaos tools | iperf3 ToS · NetEM · same L1–L5 book as Pi |

## Pitch language (jury)

- Same **LSTM blinking light** for Pi and GNS3 (shared Q1; **aligned** SLA thresholds)
- **XGBoost** severity / root-cause head **selected by Simulation source** (or `fabric` feature)
- Telemetry split (`:9090` / `:9091`) — do not mash unlabeled CSVs until textures match
- Approve steers the **active** fabric PE1

See [`unified_dual_architecture_ml.md`](../deca-backend/runbooks/unified_dual_architecture_ml.md).

```text
Dynamic routing (Approve / controller)
        ↓
Overlay / underlay (CORE · PE1 · PE2 · CEs)
        ↑
Synthetic Traffic & Chaos Injection (Pi twin — no TRex)
  • iperf3  — TCP/UDP + ToS (0x88 / 0x80)
  • NetEM   — latency / jitter / loss
  • stress  — CPU / crypto
  • BGP     — soft-clear flap
        ↓
Branch site CE → SD-WAN PE
```

## Do not

- Widen Pi SLAs for demos
- Claim Pi ≡ GNS3 before NetEM+iperf series look alike
- Use or demo TRex (removed from DECA)
