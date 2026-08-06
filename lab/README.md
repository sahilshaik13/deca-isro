# Lab ops (desktop ↔ multi-site Pi cluster)

Desktop/brain helpers for the physical DECA station network (five sites on three Pis + SD-WAN/MPLS/TE).

Topology diagrams: [`docs/STATION_NETWORK_SETUP.md`](../docs/STATION_NETWORK_SETUP.md)  
Policy catalog: [`docs/EDGE_POLICY_LAYERS.md`](../docs/EDGE_POLICY_LAYERS.md)  
Evidence: [`docs/NETWORK_EXPANSION_FINDINGS.md`](../docs/NETWORK_EXPANSION_FINDINGS.md)

Run from the **brain host on the lab LAN** (typically `192.168.50.1`).

### Day-to-day

```bash
stations                            # → lab/deca_station_map.sh (what belongs to station1/2/3)
stations --live                     # same + live systemd status over SSH
check stations                      # → lab/deca_diagnostic.sh (site map + VPN + Prom)
bash lab/deca_ops.sh check          # PASS/FAIL/WARN summary variant
bash lab/deca_ops.sh heal           # restart failed services + expansion boot
bash lab/deca_ops.sh install-boot   # sticky cold-boot units
bash lab/deca-deploy.sh             # full plug-and-play when needed
```

**Cold power-on:** `deca-expansion-boot.service` then `deca-watchdog` (+60s) restore VRF, GRE, HTB, site LANs, MPLS-on-GRE, OSPF-TE/SR-TE heal, swanctl IPsec, and write `/run/deca/station-ready`.

**Desktop power-cut (brain):** user systemd `deca-protocol-campaign.service` + `deca-protocol-watchdog.service` resume the active protocol stamp after boot (see [`predictive/README.md`](../predictive/README.md)).

### Current scripts (keep)

| Script | Role |
| --- | --- |
| [`deca_station_map.sh`](deca_station_map.sh) | Terminal ownership map (`stations`) — units/scripts/sites per Pi |
| [`deca_diagnostic.sh`](deca_diagnostic.sh) | Master health check (`check stations`) — full site inventory |
| [`deca_ops.sh`](deca_ops.sh) | Unified check / heal / install-boot |
| [`deca-deploy.sh`](deca-deploy.sh) | Plug-and-play deploy |
| [`deca_install_expansion_boot.sh`](deca_install_expansion_boot.sh) | Install expansion boot unit on Pis |
| [`deca-expansion-boot.sh`](deca-expansion-boot.sh) | On-Pi boot heal (VRF/GRE/HTB/MPLS/SR-TE/site-LAN/swanctl) |
| [`deca-swanctl-up.sh`](deca-swanctl-up.sh) | Load/initiate swanctl IPsec (`copy_dscp`) |
| [`deca_expand_phase_{a,b,c,d,g,h,te}.sh`](.) | Expansion phases (Mauritius → dual-cost → TE → QoS) |
| [`deca_te_verify.sh`](deca_te_verify.sh) | OSPF-TE TED + SR-TE preferred/backup proof |
| [`deca_htb_qos.sh`](deca_htb_qos.sh) | PS13 HTB: TT&C `0x88` LLQ · Payload `0x80` 70%+RED · BE scavenger |
| [`deca_iperf_qos_traffic.sh`](deca_iperf_qos_traffic.sh) | Multi-class iperf3 generators (**no TRex**) |
| [`telemetry-pipeline/`](telemetry-pipeline/) | Dual Flow 2: Telegraf → Kafka (per-fabric topics) → Prom `:9090` Pi / `:9091` GNS3 |
| [`gns3/`](gns3/) | GNS3 dual-fabric lab (external drive; Flow 1 + chaos) |
| [`deca_vrf_isolation_check.sh`](deca_vrf_isolation_check.sh) | VRF + IPsec `copy_dscp` / fail-closed check |
| [`swanctl/`](swanctl/) | PE1/PE2 swanctl templates with `copy_dscp=out` |
| [`deca_sdwan_controller.py`](deca_sdwan_controller.py) | TT&C + Payload AAR controller (`enter_k=3`/`exit_k=10`; TT&C preempts) |
| [`deca_sdwan_verify.sh`](deca_sdwan_verify.sh) | Live multi-class switch/recover/conflict proof |
| [`deca_rtc_ds3231_sync.sh`](deca_rtc_ds3231_sync.sh) | One-shot DS3231 enable / RTC re-stamp (steady state = kernel driver + chrony only) |
| [`exporters/`](exporters/) | Phase-D + SD-WAN Telegraf exec scripts |
| [`run_traffic.sh`](run_traffic.sh) | Laptop CE-lo iperf background (**not** during campaigns) |
| [`link_home.sh`](link_home.sh) | Symlink current scripts into `$HOME` |

### Archive

Superseded pre-expansion / duplicate helpers: [`archive/`](archive/)  
(`check_stations.sh`, `check_step7.sh`, `apply_boot_fix.sh`, `deca-heal-telemetry.sh`, `startupppp`, `forwardss`, …)

Related under `scripts/`: `deca_deploy_stations.sh` (alternate deploy), `deca_fix_prom_vpn.sh` (Prom TSDB wipe). Archived duplicates: `scripts/archive/lab-ops/`.

Topology runbook: [`docs/STATION_NETWORK_SETUP.md`](../docs/STATION_NETWORK_SETUP.md)  
Perimeter: [`docs/PROBLEM_STATEMENT_13.md`](../docs/PROBLEM_STATEMENT_13.md)

## Optional home shortcuts

```bash
bash lab/link_home.sh
# ~/deca_diagnostic.sh , ~/deca_ops.sh , ~/check_stations.sh → diagnostic
```
