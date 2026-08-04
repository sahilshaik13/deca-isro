# Unified models across network architectures (Pi + GNS3)

**One-line:** Same LSTM “blinking light” for every fabric; XGBoost severity head
adapts (or is selected) by fabric / root-cause pattern; Approve steers the active PE1.

**Mentor sentence:** We removed TRex and run the same
**iperf3 + NetEM + BGP/CPU/util** fault book on Pi and GNS3, with **aligned SLAs**,
so the live Pi lab and the GNS3 tool share one SD-WAN policy and one predictive
feature space. See [`docs/shared_fault_book.json`](../../docs/shared_fault_book.json).

Do **not** mash Pi + GNS3 time series into one unlabeled training CSV until L1–L5
inject shapes produce similar Prom dynamics. Generators may still differ slightly
(Pi `gre-te-core` vs GNS3 PE1→CORE eth0), but **SLA scales are aligned**
(TT&C ≤25/5/0.1% · Payload ≤80/15/2%).

## Pipeline

```text
                    ┌─ fabric=pi  ──► Prom :9090 ──┐
 Network A / Pi     │                              │
                    │                              ▼
 Chaos / probes ────┤                     feature align 1Hz
 (shared fault book)│                     (same metric names)
 Network B / GNS3   │                              │
                    └─ fabric=gns3 ──► Prom :9091 ─┘
                                                   │
                              ┌────────────────────┼────────────────────┐
                              ▼                    ▼                    ▼
                         Q1 LSTM              Q2 XGBoost            Q3 RAG
                      (shared heads)     (fabric feature / head) (async NLP)
                         ETAs               severity / root cause
                              │                    │
                              └────────┬───────────┘
                                       ▼
                                 Decide rail
                                       ▼
                              Approve → controller
                              (active fabric PE1)
```

## Roles

| Stage | Shared or split? | Rule |
| --- | --- | --- |
| **Metric contract** | Shared names | `sdwan_path_*`, CPU, BGP, util |
| **Collectors / Prom** | Split | Pi `:9090` · GNS3 `:9091` ([`dual_fabric_telemetry.md`](./dual_fabric_telemetry.md)) |
| **SLA gate thresholds** | Shared (aligned) | Pi = GNS3 TT&C ≤25 ms · Payload ≤80 · Gold 99.9% |
| **Fault book L1–L5** | Shared shapes | [`shared_fault_book.json`](../../docs/shared_fault_book.json) — NetEM+iperf, not gauges-only |
| **Q1 LSTM** | Shared | Train primarily on Pi; reuse on GNS3 after texture match |
| **Q2 XGBoost** | Fabric feature or thin dual head | Do not invent severity from fake flat gauges |
| **Chaos stack** | Shared | iperf3 · NetEM · stress · BGP soft-clear (**no TRex**) |
| **Actuation** | Active fabric | Approve → controller → that fabric’s PE1 |

## Alignment checklist (before claiming unified transfer)

1. GNS3 rain/loss injects use **real NetEM** on PE1→CORE (jitter on rain).
2. L4 ends at **3.5%** loss (not 8%).
3. L5 / CE conflict use **real iperf3 ToS** through HTB.
4. Protocol campaign GNS3 stamp captured with the shared book.
5. No unlabeled concat of older gauge-theater series into Q1/Q2.

## What not to do

- Widen Pi SLAs to old GNS3 “demo windows.”
- Bring back TRex — chaos is iperf3 + NetEM only.
- Claim Pi and GNS3 are interchangeable before fault injectors produce similar Prom series.
