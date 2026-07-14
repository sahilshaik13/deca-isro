# DECA Prediction System: Theoretical & Mathematical Blueprint

This document outlines the theoretical foundations, core formulas, and structural training methodology for the DECA predictive analytics pipeline (ISRO BAH 2026). It now also records the **applied realization** from the 2026-07-14 training run on the current unified lake (`scripts/train_models.py`).

Orchestration: `python scripts/rebuild_unified.py` → `python scripts/train_models.py`  
Artifacts: `models/manifest.json` plus one folder per model family under `models/`

---

## 0. Applied dataset (this train)

| Layer | Path / id | Rows used |
| --- | --- | ---: |
| Raw telemetry merge | `data/processed/deca_unified_raw.parquet` | 81,592 |
| Feature matrix | `data/processed/deca_unified_dataset.parquet` | **17,050** |
| Campaign ground truth | `data/rpi-net/runs/20260713_155333/` (21 usable faults) | — |
| Fault windows used for labels | `data/processed/deca_unified_fault_log.csv` | 21 |

**Sources in the feature matrix**

| `source` | Feature rows | Role |
| --- | ---: | --- |
| `network` | 8,772 | RPi CE–PE–CE telemetry + supervised faults |
| `public` | 8,278 | Atlas / BGP rates / Cisco / MAWI as healthy context |

**Unified label vocabulary** (`unified_label` — shared across network + public)

| Label | Rows | Origin |
| --- | ---: | --- |
| `healthy` | 15,804 | Network rest (`fault_type=none`) + **all** public rows |
| `congestion_breach` | 430 | RPi windows only |
| `tunnel_degradation` | 306 | RPi windows only |
| `bgp_route_flap` | 300 | RPi windows only |
| `vrf_leakage` | 210 | RPi windows only |

Binary anomaly flag: `is_anomaly = 1 ⟺ unified_label ≠ healthy` (1,246 positive rows).

**Public raw inputs feeding the lake (not separately re-labeled):** Cisco Gi1 counters, MAWI Samplepoint-F magnitude CSV, BGP update rates (`bgp_update_rates_full`), RIPE Atlas sampled + baseline. IODA/BGP outage CSVs remain provenance-only (`public_outage_labels_provenance.csv`) — Jul-5-centric events do not overlap Jul 8–13 public telem.

**20 engineered features** (10-minute rolling windows; slope / rolling_std / rolling_mean / accel per metric):

`bgp_update_rate_*`, `ifInOctets_*`, `ifOutOctets_*`, `jitter_ms_*`, `packet_loss_pct_*`

Train/test split for supervised heads: **75% / 25%**, `random_state=42`, stratified on the target. Median impute + zero-fill for modality gaps (e.g. BGP columns all-NaN on network-only rows).

Training date (UTC): **2026-07-14T13:33:35Z**.

---

## 1. Multivariate Anomaly & Precursor Detection
**Methodology:** Isolation Forest with Platt Score Calibration

### Theory & Structure
Instead of profiling "normal" network behavior, an Isolation Forest explicitly isolates anomalies. Because network faults (BGP flap, VRF leakage, etc.) introduce structural deviations from standard traffic matrices, they are easier to isolate. The model builds an ensemble of Isolation Trees (iTrees). Anomalies require fewer random splits → shorter path lengths.

Platt Scaling converts unbounded anomaly scores into operator-facing probabilities $P(\text{anomaly})$.

### Mathematical Formulation
**1. Isolation Forest Anomaly Score:**
$$s(x, n) = 2^{-\frac{E(h(x))}{c(n)}}$$
Where $h(x)$ is path length, $E(h(x))$ is the expected path length across trees, and $c(n)$ normalizes unsuccessful BST search length.

**2. Platt Score Calibration:**
$$P(y=1|s) = \frac{1}{1 + \exp(A \cdot s(x) + B)}$$
Parameters $A, B$ learned by logistic MLE on a labeled score set.

### Applied process (this train)
1. Fit `IsolationForest(n_estimators=300, contamination≈0.073)` **only on healthy train rows** (`is_anomaly=0`), after `SimpleImputer(median)` + `StandardScaler` over the 20 features.
2. Map scikit-learn’s decision function to a positive anomaly score: $s'(x) = -\,\mathrm{decision\_function}(x)$ (larger ⇒ more anomalous). This is the operational stand-in for the $s(x,n)$ ranking in the formula above.
3. Fit `LogisticRegression` on $(s'(x), y)$ from the full train split → Platt $A, B$.
4. Evaluate calibrated $P(y=1|s')$ on the held-out 25% test set (4,263 rows, 312 anomalies).

**Artifacts:** `models/isolation_forest/` (`isolation_forest.pkl`, `confidence_calibrator.pkl`, `feature_scaler.pkl`)

### End result
| Metric | Value |
| --- | ---: |
| Test ROC-AUC (Platt $P$) | **0.720** |
| Contamination (fit) | 0.073 |

---

## 2. Trajectory Forecasting (Macro Trends)
**Methodology:** Prophet Additive Regression

### Theory & Structure
Prophet captures daily/weekly seasonality and trend shifts in macro telemetry so SLA-style breaches can be projected against a structural baseline, even with missing probe samples.

### Mathematical Formulation
$$y(t) = g(t) + s(t) + h(t) + \epsilon_t$$
* $g(t)$ — piecewise linear trend  
* $s(t)$ — periodic (daily / weekly) seasonality  
* $h(t)$ — holiday / scheduled-event effects (unused here)  
* $\epsilon_t$ — noise  

### Applied process (this train)
Source series taken from **`deca_unified_raw.parquet`** (long-form `timestamp, metric, value`), not the feature matrix:

| Metric | Series points fitted | Artifact |
| --- | ---: | --- |
| `ifInOctets` | 4,502 | `models/prophet_ifInOctets/prophet_ifInOctets.pkl` |
| `jitter_ms` | 8,000 (capped from denser samples) | `models/prophet_jitter_ms/prophet_jitter_ms.pkl` |
| `bgp_update_rate` | 320 | `models/prophet_bgp_update_rate/prophet_bgp_update_rate.pkl` |

Settings: `daily_seasonality=True`, `weekly_seasonality=True`, `yearly_seasonality=False`, `changepoint_prior_scale=0.05`. Timestamps de-tz’d to naive UTC for Prophet’s `ds` column. Cap at 8k evenly spaced points for CPU.

### End result
Three fitted additive baselines covering octets, jitter, and BGP update rate; used as **macro trend priors** for SLA / breach foreshadowing alongside the LSTM micro estimate. No separate holdout MAE logged for Prophet in this run (fit-only regeneration of the three pickle artifacts).

---

## 3. Time-to-Breach Estimation (Micro Sequences)
**Methodology:** Long Short-Term Memory (LSTM) Networks

### Theory & Structure
LSTMs model short, non-linear precursor sequences (jitter spikes, bitrate swings) while Prophet handles macro seasonality. Gates retain slow degradations (e.g. tunnel) and drop irrelevant noise, regressing minutes until breach.

### Mathematical Formulation
* Forget: $f_t = \sigma(W_f \cdot [h_{t-1}, x_t] + b_f)$  
* Input: $i_t = \sigma(W_i \cdot [h_{t-1}, x_t] + b_i)$  
* Cell: $C_t = f_t \odot C_{t-1} + i_t \odot \tanh(W_C \cdot [h_{t-1}, x_t] + b_C)$  
* Output: $o_t = \sigma(W_o \cdot [h_{t-1}, x_t] + b_o)$,\quad $h_t = o_t \odot \tanh(C_t)$  

The final dense head maps $h_T$ → $\widehat{\text{TTB}}$ (minutes).

### Applied process (this train)
1. Restrict to `source=network`; dedupe timestamps; median→0 fill on the 20 features.
2. Build sliding windows of length **$T = 16$** ending on rows where `time_to_breach_minutes` is finite (campaign fault windows).
3. Supervise with $y = \text{time\_to\_breach\_minutes}$ at the window end.
4. Standardize features with train-set mean/std; architecture `LSTM(64) → LSTM(32) → Dense(32, relu) → Dense(1)`.
5. Train 12 epochs, batch 64, Adam $10^{-3}$, MSE loss / MAE metric; 80/20 train–test of the **623** windows.

**Artifacts:** `models/lstm/fault_lstm_v1.keras`, `models/lstm/lstm_scaler.pkl`

### End result
| Metric | Value |
| --- | ---: |
| Supervised sequences | **623** |
| Test MAE | **2.143 minutes** |
| Test size | 125 sequences |

---

## 4. Unified-label classification (operational layer)
**Methodology:** Multiclass XGBoost on `unified_label`

Not a separate numbered block in the original theory doc, but required so network + public rows share one supervised vocabulary for fault-type prediction.

### Applied process
* Target: `unified_label` ∈ {`healthy`, `congestion_breach`, `tunnel_degradation`, `bgp_route_flap`, `vrf_leakage`}
* Features: same 20-column engineered matrix; median impute (keep empty features)
* Model: `XGBClassifier(n_estimators=200, max_depth=5, lr=0.08, subsample=0.9, colsample_bytree=0.9)`
* Split: stratified 75/25 on 17,050 rows

**Artifacts:** `models/fault_classifier/` (`fault_classifier_xgb.pkl`, `label_encoder.pkl`, `scorecard.png`)

### End result (held-out test, n=4,263)

| Aggregate | Score |
| --- | ---: |
| Accuracy | **0.97** |
| Macro-F1 | **0.716** |
| Weighted-F1 | **0.96** |

| Class | Precision | Recall | F1 | Support |
| --- | ---: | ---: | ---: | ---: |
| `healthy` | 0.97 | 1.00 | **0.984** | 3,951 |
| `congestion_breach` | 0.93 | 0.89 | **0.910** | 108 |
| `tunnel_degradation` | 0.92 | 0.84 | **0.878** | 77 |
| `bgp_route_flap` | 0.94 | 0.23 | **0.366** | 75 |
| `vrf_leakage` | 0.94 | 0.29 | **0.441** | 52 |

BGP / VRF remain recall-limited (few windows vs large healthy class). Congestion and tunnel generalize well on this lake.

---

## 5. Feature Attribution & Alert Deduplication
**Methodology:** SHAP (theory) · XGBoost gain proxy (this train) · NetworkX (graph)

### Theory & Structure
1. **SHAP** allocates credit $\phi_i$ across features via cooperative game theory.  
2. **NetworkX** models CE–PE–CE as a digraph; eccentricity / path distance collapses alert storms to a root node.

### Mathematical Formulation
**1. SHAP:**
$$\phi_i(f, x) = \sum_{S \subseteq N \setminus \{i\}} \frac{|S|! (M - |S| - 1)!}{M!} [f(S \cup \{i\}) - f(S)]$$

**2. Eccentricity:**
$$e(v) = \max_{u \in V} d(v, u)$$

### Applied process (this train)
**Attribution:** `shap` was not installed in the train env. Applied the discrete ranking of **XGBoost feature importances** (gain) as a tractable proxy for which telemetry channels drive $\hat{y}$ — same “credit allocation” intent as SHAP, not the exact Shapley sum. Top channels:

| Rank | Feature | Importance |
| ---: | --- | ---: |
| 1 | `packet_loss_pct_rolling_std` | 0.171 |
| 2 | `packet_loss_pct_rolling_mean` | 0.129 |
| 3 | `jitter_ms_slope` | 0.099 |
| 4 | `jitter_ms_rolling_std` | 0.086 |
| 5 | `ifOutOctets_rolling_std` | 0.070 |

→ `models/fault_classifier/feature_attribution.json`

**Topology:** Directed CE–PE–CE graph matching the lab:

| Node | Host | IP |
| --- | --- | --- |
| PE1 | station1 | 192.168.50.10 |
| PE2 | station2 | 192.168.50.20 |
| CORE | station3 | 192.168.50.30 |

Edges: PE1↔CORE, PE2↔CORE, PE1→PE2 overlay. Undirected eccentricity on this small mesh:

$$e(\mathrm{PE1}) = e(\mathrm{PE2}) = e(\mathrm{CORE}) = 1$$

→ `models/topology/topology_graph.json`, `models/topology/topology_graph.pkl`

### End result
Attribution ranks loss volatility and jitter dynamics highest for multiclass decisions. Topology artifact is ready for alert merge by shortest-path / eccentricity once live alerts bind to nodes.

---

## 6. Scoreboard summary (2026-07-14)

| Component | Primary score | Notes |
| --- | --- | --- |
| Isolation Forest + Platt | ROC-AUC **0.720** | Healthy-only IF fit; Platt on full train scores |
| XGBoost `unified_label` | Macro-F1 **0.716**, Acc **0.97** | Weak: BGP flap / VRF recall |
| LSTM time-to-breach | MAE **2.143 min** | 623 network fault sequences, $T=16$ |
| Prophet ×3 | Fit complete | 4502 / 8000 / 320 points |
| Attribution | Top: loss std / mean, jitter slope | XGBoost gain proxy |
| Topology | $e(v)=1$ ∀ nodes | PE1–PE2–CORE digraph |

### Detailed granular per-class scorecard

Held-out XGBoost `unified_label` test set (n = 4,263):

| Target Class Identifier | Precision | Recall | F1-Score | Support | Operational Status |
| --- | ---: | ---: | ---: | ---: | --- |
| `healthy` | 0.97 | 1.00 | 0.984 | 3,951 | Exceptional Baseline Hold |
| `congestion_breach` | 0.93 | 0.89 | 0.910 | 108 | Highly Generalizable |
| `tunnel_degradation` | 0.92 | 0.84 | 0.878 | 77 | Highly Generalizable |
| `bgp_route_flap` | 0.94 | 0.23 | 0.366 | 75 | Recall-Limited / Data Scarce |
| `vrf_leakage` | 0.94 | 0.29 | 0.441 | 52 | Recall-Limited / Data Scarce |

Reproduce:

```bash
source .venv/bin/activate
python scripts/rebuild_unified.py
python scripts/train_models.py
```
