# DECA model playground — mixed test scoreboard

- **When:** `2026-07-15T11:14:39.579913+00:00`
- **Exam seed:** `7` (stratified mixed paper)
- **Holdout:** frac=0.2  policy=random
- **Exam rows:** 3,410 / lake 17,050

## Individual scores

| Model | Role | Primary | Score | Extra |
| --- | --- | --- | ---: | --- |
| `isolation_forest` | Unknown weirdness / anomaly precursor | roc_auc | 0.706 | AP=0.10778560068011211 |
| `fault_classifier_xgb` | What is happening now? (multiclass fault ID) | macro_f1 | 0.825 | Acc=0.967 · rareR=0.7928571428571429 |
| `lstm_ttb` |  | — | — | {"skipped": true} |
| `prophet` |  | — | — | {"skipped": true} |
| `topology` | Alert eccentricity / root-node merge (structure only) | eccentricity | {'PE1': 1, 'PE2': 1, 'CORE': 1} | Not a telemetry accuracy model — printed for completeness |

## Fault classifier — per class (mixed paper)

| Class | P | R | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| healthy | 0.99 | 0.97 | 0.98 | 3161 |
| congestion_breach | 0.92 | 0.97 | 0.94 | 86 |
| tunnel_degradation | 0.89 | 0.97 | 0.93 | 61 |
| bgp_route_flap | 0.50 | 0.80 | 0.62 | 60 |
| vrf_leakage | 0.56 | 0.79 | 0.65 | 42 |

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
