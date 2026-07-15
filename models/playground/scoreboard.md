# DECA model playground — mixed test scoreboard

- **When:** `2026-07-15T15:48:47.327289+00:00`
- **Exam seed:** `1784130519` (stratified mixed paper)
- **Holdout:** frac=0.2  policy=random
- **Exam rows:** 4,782 / lake 23,909

## Individual scores

| Model | Role | Primary | Score | Extra |
| --- | --- | --- | ---: | --- |
| `isolation_forest` | Unknown weirdness / anomaly precursor | roc_auc | 0.575 | AP=0.18823098280786732 |
| `fault_classifier_xgb` | What is happening now? (multiclass fault ID) | macro_f1 | 0.773 | Acc=0.915 · rareR=0.5682926829268293 |
| `lstm_ttb` | When will it break? (minutes to breach) | mae_minutes | 2.466 min | n=1953 |
| `prophet_ifInOctets` | Macro baseline / seasonality envelope | mae | 1.816e+09 | sMAPE=2.000 · honest_refit_prefix |
| `prophet_jitter_ms` | Macro baseline / seasonality envelope | mae | 185.8 | sMAPE=1.858 · honest_refit_prefix |
| `prophet_bgp_update_rate` | Macro baseline / seasonality envelope | mae | 8882 | sMAPE=0.440 · honest_refit_prefix |
| `topology` | Alert eccentricity / root-node merge (structure only) | eccentricity | {'PE1': 1, 'PE2': 1, 'CORE': 1} | Not a telemetry accuracy model — printed for completeness |

## Fault classifier — per class (mixed paper)

| Class | P | R | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.96 | 0.94 | 0.95 | 3992 |
| congestion_breach | 0.94 | 0.98 | 0.96 | 252 |
| tunnel_degradation | 0.88 | 0.92 | 0.90 | 170 |
| bgp_route_flap | 0.54 | 0.60 | 0.57 | 245 |
| vrf_leakage | 0.46 | 0.54 | 0.50 | 123 |

## Exam label mix

```
{
  "healthy": 3992,
  "congestion_breach": 252,
  "tunnel_degradation": 170,
  "bgp_route_flap": 245,
  "vrf_leakage": 123
}
```

> Isolation Forest + XGB + LSTM share the **same stratified mixed rows**. Prophet uses a chronological tail of each raw series (optionally `--prophet-refit`). Topology is structure-only.
