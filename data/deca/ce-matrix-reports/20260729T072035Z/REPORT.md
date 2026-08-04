# DECA CE Matrix Traffic Report — `20260729T072035Z`

**Overall:** 9 PASS / 30 FAIL / 39 total — NEEDS ATTENTION

## Situations

| Situation | Pass | Fail |
| --- | ---: | ---: |
| `S1_ce_lo_mesh` | 2 | 10 |
| `S2_lan_ws_mesh` | 2 | 10 |
| `S3_iperf_clear` | 1 | 7 |
| `S4_mild_netem` | 0 | 2 |
| `S4_recover` | 0 | 1 |
| `preflight` | 4 | 0 |

## Site participation (src/dst across icmp+iperf)

| Site | src PASS | src FAIL | dst PASS | dst FAIL | Verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| **mauritius** | 0 | 6 | 0 | 6 | NO DATA |
| **mcf** | 2 | 6 | 3 | 5 | CHECK |
| **nrsc** | 0 | 11 | 0 | 8 | NO DATA |
| **sac** | 3 | 5 | 2 | 9 | CHECK |

## Failures

| Situation | Test | From | To | Detail |
| --- | --- | --- | --- | --- |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | sac:10.100.2.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | mauritius:10.100.3.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | mcf:10.100.4.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | sac:10.100.2.1 | nrsc:10.100.1.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | sac:10.100.2.1 | mauritius:10.100.3.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | nrsc:10.100.1.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | sac:10.100.2.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | mcf:10.100.4.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | mcf:10.100.4.1 | nrsc:10.100.1.1 | 100% loss or unreachable |
| `S1_ce_lo_mesh` | ping_ce_lo | mcf:10.100.4.1 | mauritius:10.100.3.1 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | sac-ws:10.101.2.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | mauritius-ws:10.101.3.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | mcf-ws:10.101.4.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | sac-ws | nrsc-ws:10.101.1.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | sac-ws | mauritius-ws:10.101.3.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | nrsc-ws:10.101.1.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | sac-ws:10.101.2.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | mcf-ws:10.101.4.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | mcf-ws | nrsc-ws:10.101.1.2 | 100% loss or unreachable |
| `S2_lan_ws_mesh` | ping_lan_ws | mcf-ws | mauritius-ws:10.101.3.2 | 100% loss or unreachable |
| `S3_iperf_clear` | gold_nrsc_to_sac | nrsc-ws | sac-srv:5201 | {  |
| `S3_iperf_clear` | distant_mau_to_sac | mau-ws | sac-srv:5201 | {  |
| `S3_iperf_clear` | regional_mcf_to_nrsc | mcf-ws | nrsc-srv:5201 | {  |
| `S3_iperf_clear` | reverse_sac_to_nrsc | sac-ws | nrsc-srv:5201 | {  |
| `S3_iperf_clear` | same_pe1_nrsc_to_mau | nrsc-ws | mau-srv:5201 | {  |
| `S3_iperf_clear` | cross_mau_to_mcf | mau-ws | mcf-srv:5201 | {  |
| `S3_iperf_clear` | cross_mcf_to_mau | mcf-ws | mau-srv:5201 | {  |
| `S4_mild_netem` | ping_ce_lo_under_netem | nrsc:10.100.1.1 | sac:10.100.2.1 | 100% loss or unreachable |
| `S4_mild_netem` | gold_nrsc_to_sac_under_netem | nrsc-ws | sac-srv:5201 | {  |
| `S4_recover` | ping_ce_lo_after_clear | nrsc:10.100.1.1 | sac:10.100.2.1 | 100% loss or unreachable |

## Full results

| Sit | Test | From | To | Proto | OK | RTT ms | Loss % | Mbps |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |
| `preflight` | netns_present | nrsc | station1/ce-a | check | **PASS** | - | - | - |
| `preflight` | netns_present | sac | station2/ce-b | check | **PASS** | - | - | - |
| `preflight` | netns_present | mauritius | station1/ce-mauritius | check | **PASS** | - | - | - |
| `preflight` | netns_present | mcf | station2/ce-mcf | check | **PASS** | - | - | - |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | sac:10.100.2.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | mauritius:10.100.3.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | nrsc:10.100.1.1 | mcf:10.100.4.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | sac:10.100.2.1 | nrsc:10.100.1.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | sac:10.100.2.1 | mauritius:10.100.3.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | sac:10.100.2.1 | mcf:10.100.4.1 | icmp | **PASS** | 0.238 | 0 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | nrsc:10.100.1.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | sac:10.100.2.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mauritius:10.100.3.1 | mcf:10.100.4.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mcf:10.100.4.1 | nrsc:10.100.1.1 | icmp | **FAIL** | - | 100 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mcf:10.100.4.1 | sac:10.100.2.1 | icmp | **PASS** | 0.188 | 0 | - |
| `S1_ce_lo_mesh` | ping_ce_lo | mcf:10.100.4.1 | mauritius:10.100.3.1 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | sac-ws:10.101.2.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | mauritius-ws:10.101.3.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | nrsc-ws | mcf-ws:10.101.4.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | sac-ws | nrsc-ws:10.101.1.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | sac-ws | mauritius-ws:10.101.3.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | sac-ws | mcf-ws:10.101.4.2 | icmp | **PASS** | 0.335 | 0 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | nrsc-ws:10.101.1.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | sac-ws:10.101.2.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mauritius-ws | mcf-ws:10.101.4.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mcf-ws | nrsc-ws:10.101.1.2 | icmp | **FAIL** | - | 100 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mcf-ws | sac-ws:10.101.2.2 | icmp | **PASS** | 0.262 | 0 | - |
| `S2_lan_ws_mesh` | ping_lan_ws | mcf-ws | mauritius-ws:10.101.3.2 | icmp | **FAIL** | - | 100 | - |
| `S3_iperf_clear` | gold_nrsc_to_sac | nrsc-ws | sac-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | distant_mau_to_sac | mau-ws | sac-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | regional_mcf_to_nrsc | mcf-ws | nrsc-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | reverse_sac_to_nrsc | sac-ws | nrsc-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | same_pe1_nrsc_to_mau | nrsc-ws | mau-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | same_pe2_sac_to_mcf | sac-ws | mcf-srv:5201 | iperf3 | **PASS** | - | - | 4439.67 |
| `S3_iperf_clear` | cross_mau_to_mcf | mau-ws | mcf-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S3_iperf_clear` | cross_mcf_to_mau | mcf-ws | mau-srv:5201 | iperf3 | **FAIL** | - | - | 0.00 |
| `S4_mild_netem` | ping_ce_lo_under_netem | nrsc:10.100.1.1 | sac:10.100.2.1 | icmp | **FAIL** | - | 100 | - |
| `S4_mild_netem` | gold_nrsc_to_sac_under_netem | nrsc-ws | sac-srv:5201 | iperf3 | **FAIL** | - | - | - |
| `S4_recover` | ping_ce_lo_after_clear | nrsc:10.100.1.1 | sac:10.100.2.1 | icmp | **FAIL** | - | 100 | - |

_Artifacts: `/home/brain/deca-isro/data/deca/ce-matrix-reports/20260729T072035Z` (`REPORT.md`, `report.json`, `results.tsv`, `run.log`)_
