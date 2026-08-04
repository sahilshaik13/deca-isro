# Past sealed blind incidents (lab)

Derived from scorecard.json under data/rpi-net/live/.

## blind_20260718_0848_60m / blind_20260718_0848_60m_e01_congestion_breach
- fault: `congestion_breach` on `station1`
- detected: True predicted=`congestion_breach` class_correct=True
- confirmed_lead_min=9.7 advisory_lead_min=10.5 eta_error_min=-6.3
- window: 2026-07-18T03:20:28.608369+00:00 → 2026-07-18T03:32:07.259787+00:00

## blind_20260718_0848_60m / blind_20260718_0848_60m_e02_bgp_route_flap
- fault: `bgp_route_flap` on `station1`
- detected: True predicted=`bgp_route_flap` class_correct=True
- confirmed_lead_min=-1.3 advisory_lead_min=0.5 eta_error_min=5.0
- window: 2026-07-18T03:42:43.683510+00:00 → 2026-07-18T03:50:13.233412+00:00

## blind_20260718_0848_60m / blind_20260718_0848_60m_e03_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=5.3 advisory_lead_min=6.3 eta_error_min=-0.3
- window: 2026-07-18T03:55:15.650357+00:00 → 2026-07-18T04:02:12.138870+00:00

## blind_20260718_0848_60m / blind_20260718_0848_60m_e04_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: False predicted=`None` class_correct=False
- confirmed_lead_min=None advisory_lead_min=None eta_error_min=None
- window: 2026-07-18T04:07:38.004166+00:00 → 2026-07-18T04:12:51.432178+00:00

## blind_20260718_2219_60m / blind_20260718_2219_60m_e01_bgp_route_flap
- fault: `bgp_route_flap` on `station1`
- detected: True predicted=`bgp_route_flap` class_correct=True
- confirmed_lead_min=4.8 advisory_lead_min=7.4 eta_error_min=0.8
- window: 2026-07-18T16:51:09.448546+00:00 → 2026-07-18T17:00:02.133264+00:00

## blind_20260718_2219_60m / blind_20260718_2219_60m_e02_congestion_breach
- fault: `congestion_breach` on `station1`
- detected: True predicted=`congestion_breach` class_correct=True
- confirmed_lead_min=6.4 advisory_lead_min=7.2 eta_error_min=-4.2
- window: 2026-07-18T17:02:57.086054+00:00 → 2026-07-18T17:10:50.420102+00:00

## blind_20260718_2219_60m / blind_20260718_2219_60m_e03_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=1.4 advisory_lead_min=2.4 eta_error_min=-0.7
- window: 2026-07-18T17:17:54.673363+00:00 → 2026-07-18T17:24:59.899056+00:00

## blind_20260718_2219_60m / blind_20260718_2219_60m_e04_congestion_breach
- fault: `congestion_breach` on `station1`
- detected: True predicted=`congestion_breach` class_correct=True
- confirmed_lead_min=6.4 advisory_lead_min=6.9 eta_error_min=-3.6
- window: 2026-07-18T17:32:39.316666+00:00 → 2026-07-18T17:44:37.662296+00:00

## blind_baseline_feature_bgp_20260721_2321_40m / blind_baseline_feature_bgp_20260721_2321_40m_cg01_e01_bgp_route_flap
- fault: `bgp_route_flap` on `station1`
- detected: False predicted=`None` class_correct=False
- confirmed_lead_min=None advisory_lead_min=9.4 eta_error_min=None
- window: 2026-07-21T17:53:27.385745+00:00 → 2026-07-21T18:03:56.990071+00:00

## blind_baseline_feature_bgp_20260721_2321_40m / blind_baseline_feature_bgp_20260721_2321_40m_cg01_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: True predicted=`vrf_leakage` class_correct=True
- confirmed_lead_min=7.4 advisory_lead_min=7.7 eta_error_min=-5.9
- window: 2026-07-21T17:53:27.386076+00:00 → 2026-07-21T18:02:15.133474+00:00

## blind_baseline_feature_tunnel_20260721_2302_40m / blind_baseline_feature_tunnel_20260721_2302_40m_cg01_e01_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=3.3 advisory_lead_min=4.0 eta_error_min=4.5
- window: 2026-07-21T17:35:45.170706+00:00 → 2026-07-21T17:40:40.622087+00:00

## blind_baseline_feature_tunnel_20260721_2302_40m / blind_baseline_feature_tunnel_20260721_2302_40m_cg01_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: False predicted=`None` class_correct=False
- confirmed_lead_min=None advisory_lead_min=7.7 eta_error_min=None
- window: 2026-07-21T17:35:45.171249+00:00 → 2026-07-21T17:44:19.819059+00:00

## blind_compound_bgp_route_flap_20260719_1239_40m / blind_compound_bgp_route_flap_20260719_1239_40m_cg01_e01_bgp_route_flap
- fault: `bgp_route_flap` on `station1`
- detected: True predicted=`vrf_leakage` class_correct=False
- confirmed_lead_min=7.2 advisory_lead_min=7.8 eta_error_min=-2.4
- window: 2026-07-19T07:11:45.483570+00:00 → 2026-07-19T07:20:29.688058+00:00

## blind_compound_bgp_route_flap_20260719_1239_40m / blind_compound_bgp_route_flap_20260719_1239_40m_cg01_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: True predicted=`vrf_leakage` class_correct=True
- confirmed_lead_min=5.1 advisory_lead_min=5.8 eta_error_min=3.5
- window: 2026-07-19T07:11:45.483906+00:00 → 2026-07-19T07:18:18.657083+00:00

## blind_compound_congestion_breach_20260719_1256_40m / blind_compound_congestion_breach_20260719_1256_40m_cg01_e01_congestion_breach
- fault: `congestion_breach` on `station1`
- detected: True predicted=`congestion_breach` class_correct=True
- confirmed_lead_min=10.5 advisory_lead_min=11.3 eta_error_min=-4.1
- window: 2026-07-19T07:30:12.489647+00:00 → 2026-07-19T07:43:00.923374+00:00

## blind_compound_congestion_breach_20260719_1256_40m / blind_compound_congestion_breach_20260719_1256_40m_cg01_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: False predicted=`None` class_correct=False
- confirmed_lead_min=None advisory_lead_min=6.8 eta_error_min=None
- window: 2026-07-19T07:30:12.489937+00:00 → 2026-07-19T07:37:58.486839+00:00

## blind_compound_tunnel_degradation_20260719_1317_40m / blind_compound_tunnel_degradation_20260719_1317_40m_cg01_e01_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=2.3 advisory_lead_min=2.8 eta_error_min=1.0
- window: 2026-07-19T07:51:14.731350+00:00 → 2026-07-19T07:57:04.718440+00:00

## blind_compound_tunnel_degradation_20260719_1317_40m / blind_compound_tunnel_degradation_20260719_1317_40m_cg01_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: False predicted=`None` class_correct=False
- confirmed_lead_min=None advisory_lead_min=2.7 eta_error_min=None
- window: 2026-07-19T07:51:14.731735+00:00 → 2026-07-19T07:55:26.304633+00:00

## blind_echo_20260719_1102_45m / blind_echo_20260719_1102_45m_e01_congestion_breach
- fault: `congestion_breach` on `station1`
- detected: True predicted=`congestion_breach` class_correct=True
- confirmed_lead_min=10.8 advisory_lead_min=11.6 eta_error_min=-5.1
- window: 2026-07-19T05:35:20.024841+00:00 → 2026-07-19T05:47:37.161050+00:00

## blind_echo_20260719_1102_45m / blind_echo_20260719_1102_45m_e02_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=3.9 advisory_lead_min=4.4 eta_error_min=-0.8
- window: 2026-07-19T05:54:41.098401+00:00 → 2026-07-19T06:02:28.686529+00:00

## blind_echo_20260719_1102_45m / blind_echo_20260719_1102_45m_e03_tunnel_degradation
- fault: `tunnel_degradation` on `station1`
- detected: True predicted=`tunnel_degradation` class_correct=True
- confirmed_lead_min=4.1 advisory_lead_min=4.6 eta_error_min=-1.8
- window: 2026-07-19T06:09:55.714382+00:00 → 2026-07-19T06:18:54.271398+00:00

## blind_pd_originlock_20260724_1614 / blind_pd_originlock_20260724_1614_e01_policy_drift
- fault: `policy_drift` on `station1`
- detected: True predicted=`policy_drift` class_correct=True
- confirmed_lead_min=2.9 advisory_lead_min=4.9 eta_error_min=-1.4
- window: 2026-07-24T16:17:14.328895+00:00 → 2026-07-24T16:23:05.281514+00:00

## blind_policy_drift_20260724_1540 / blind_policy_drift_20260724_1540_e01_policy_drift
- fault: `policy_drift` on `station1`
- detected: True predicted=`policy_drift` class_correct=True
- confirmed_lead_min=3.7 advisory_lead_min=3.7 eta_error_min=-2.0
- window: 2026-07-24T15:37:14.098765+00:00 → 2026-07-24T15:42:32.777524+00:00

## blind_vrf_isolated_20260719_1333_45m / blind_vrf_isolated_20260719_1333_45m_e01_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: True predicted=`vrf_leakage` class_correct=True
- confirmed_lead_min=-3.4 advisory_lead_min=-2.4 eta_error_min=7.2
- window: 2026-07-19T08:04:26.539906+00:00 → 2026-07-19T08:09:42.881637+00:00

## blind_vrf_isolated_20260719_1333_45m / blind_vrf_isolated_20260719_1333_45m_e02_vrf_leakage
- fault: `vrf_leakage` on `station2`
- detected: True predicted=`vrf_leakage` class_correct=True
- confirmed_lead_min=3.6 advisory_lead_min=3.6 eta_error_min=1.0
- window: 2026-07-19T08:16:59.855673+00:00 → 2026-07-19T08:23:38.284083+00:00

_Total incidents indexed: 25_
