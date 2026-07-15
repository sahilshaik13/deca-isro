# DECA model playground — mixed test scoreboard

- **When:** `2026-07-15T09:45:04.185448+00:00`
- **Exam seed:** `1784108700` (stratified mixed paper)
- **Holdout:** frac=0.2  policy=random
- **Exam rows:** 3,410 / lake 17,050

## Individual scores

| Model | Role | Primary | Score | Extra |
| --- | --- | --- | ---: | --- |
| `isolation_forest` | Unknown weirdness / anomaly precursor | roc_auc | 0.695 | AP=0.10513310183514897 |
| `fault_classifier_xgb` | What is happening now? (multiclass fault ID) | macro_f1 | 0.824 | Acc=0.966 · rareR=0.7833333333333333 |
| `lstm_ttb` | When will it break? (minutes to breach) | mae_minutes | 2.317 min | n=442 |
| `prophet_ifInOctets` | Macro baseline / seasonality envelope | mae | 1.733e+07 | sMAPE=1.659 · artifact_predict_tail_optimistic |
| `prophet_jitter_ms` | Macro baseline / seasonality envelope | mae | 609.1 | sMAPE=1.559 · artifact_predict_tail_optimistic |
| `prophet_bgp_update_rate` | Macro baseline / seasonality envelope | mae | 6757 | sMAPE=0.305 · artifact_predict_tail_optimistic |
| `topology` | Alert eccentricity / root-node merge (structure only) | eccentricity | {'PE1': 1, 'PE2': 1, 'CORE': 1} | Not a telemetry accuracy model — printed for completeness |

## Fault classifier — per class (mixed paper)

| Class | P | R | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.99 | 0.97 | 0.98 | 3161 |
| congestion_breach | 0.90 | 0.95 | 0.93 | 86 |
| tunnel_degradation | 0.84 | 0.97 | 0.90 | 61 |
| bgp_route_flap | 0.46 | 0.73 | 0.56 | 60 |
| vrf_leakage | 0.67 | 0.83 | 0.74 | 42 |

## Exam label mix

```
{
  "healthy": 3161,
  "congestion_breach": 86,
  "tunnel_degradation": 61,
  "bgp_route_flap": 60,
  "vrf_leakage": 42
}
```

> Isolation Forest + XGB + LSTM share the **same stratified mixed rows**. Prophet uses a chronological tail of each raw series (optionally `--prophet-refit`). Topology is structure-only.
