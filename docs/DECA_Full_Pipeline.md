# DECA — Complete Pipeline Documentation

Detect, Explain, Correlate, Act. Air-gapped predictive copilot for secure MPLS operations, built for BAH 2026 PS13.

This document covers the full pipeline end to end: data sources, feature engineering, the ML prediction engine, the offline LLM copilot, and integration. Code snippets are illustrative and meant to be adapted to your actual file paths and column names once your dataset is finalized.

---

## 1. Architecture Overview

```
Raspberry Pi 4 x3 (MPLS/SD-WAN simulation)
        |
   Telegraf + pmacct (telemetry export)
        |
   Prometheus (laptop, time-series store)
        |
   Feature engineering (pandas)
        |
   ML ensemble: Prophet + Isolation Forest + LSTM/TFT + SHAP
        |
   ChromaDB (RAG) + DeepSeek-R1 1.5B (llama.cpp)
        |
   FastAPI autonomous loop -> React dashboard
```

Network layer status: complete. This document covers everything from data onward.

---

## 2. Datasets

### 2.1 Public datasets — real network behavior, used for baseline validation

| Dataset | Link | One-line reason |
|---|---|---|
| MAWI Working Group Traffic Archive | https://mawi.wide.ad.jp/mawi/ | Real backbone traffic captured daily since 1999, used to build a realistic "normal" traffic baseline instead of a sterile synthetic one |
| CAIDA Passive Traffic Traces | https://www.caida.org/catalog/datasets/passive_dataset/ | Real anonymized backbone traces from production networks, validates our congestion model generalizes beyond our own lab |
| CAIDA Datasets Overview (BGP, topology, DDoS) | https://www.caida.org/catalog/datasets/overview/ | Central catalog including Route Views BGP tables and attack traces |
| RIPE RIS (Routing Information Service) | https://ris.ripe.net/ | Live global archive of real BGP updates since 1999, used to learn genuine route flap and convergence-stress patterns |
| RouteViews Project | http://www.routeviews.org/routeviews/ | Continuously archived real BGP table dumps from production routers, the standard academic reference for BGP anomaly research |
| CICIDS2018 (Canadian Institute for Cybersecurity) | https://www.unb.ca/cic/datasets/ids-2018.html | Labeled modern network traffic with injected anomalies, used to benchmark our Isolation Forest pipeline against a known standard |
| Google Cluster Trace Data | https://github.com/google/cluster-data | Real infrastructure operational telemetry with failure events, validates that our fault injection produces realistic gradual degradation, not sudden drops |
| GÉANT Network Data & Publications | https://www.geant.org/Networks | Real European research/education backbone operating at carrier-grade MPLS scale, structurally close to a multi-site government WAN |

### 2.2 Self-generated dataset — DECA Pi simulation

No public dataset covers IPSec rekey anomalies, RSVP-TE stress signals, VRF route leakage, or SD-WAN controller policy drift. These come only from the 3-node Raspberry Pi testbed, run extensively:

- Each of the 5 fault scenarios run 100–200 times with varied timing/severity
- iPerf3 background traffic run continuously for multiple days before labeling
- Real MAWI/CAIDA traffic patterns replayed as background load underneath synthetic faults

---

## 3. Data Pipeline — Export and Feature Engineering

### 3.1 Export from Prometheus to CSV

```python
import requests
import pandas as pd
from datetime import datetime, timedelta

PROM_URL = "http://localhost:9090/api/v1/query_range"

def export_metric(metric_name, start, end, step="15s"):
    params = {
        "query": metric_name,
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "step": step
    }
    resp = requests.get(PROM_URL, params=params).json()
    rows = []
    for series in resp["data"]["result"]:
        labels = series["metric"]
        for ts, val in series["values"]:
            rows.append({
                "timestamp": datetime.fromtimestamp(float(ts)),
                "metric": metric_name,
                "value": float(val),
                **labels
            })
    return pd.DataFrame(rows)

end = datetime.utcnow()
start = end - timedelta(hours=72)

metrics = [
    "ifInOctets", "ifOutOctets", "jitter_ms", "packet_loss_pct",
    "bgp_hold_timer_remaining", "bgp_update_rate", "rekey_duration_ms",
    "rsvp_path_retransmit_rate", "vrf_route_count", "bgp_flap_count"
]

frames = [export_metric(m, start, end) for m in metrics]
df = pd.concat(frames, ignore_index=True)
df.to_csv("deca_raw_telemetry.csv", index=False)
```

### 3.2 Feature engineering — trajectory features, not raw thresholds

This is the core requirement from Catch 2: the model must learn rate-of-change, not absolute values.

```python
import pandas as pd
import numpy as np

def engineer_features(df, window_minutes=10):
    df = df.sort_values(["metric", "timestamp"]).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    out = []

    for metric, group in df.groupby("metric"):
        group = group.set_index("timestamp").resample("15S").mean(numeric_only=True)
        group["value"] = group["value"].interpolate()

        # Rate of change (slope) over rolling window
        group[f"{metric}_slope"] = group["value"].diff() / 15.0

        # Rolling variance (jitter trend precursor)
        window = f"{window_minutes}min"
        group[f"{metric}_rolling_std"] = group["value"].rolling(window).std()

        # Rolling mean for baseline comparison
        group[f"{metric}_rolling_mean"] = group["value"].rolling(window).mean()

        # Acceleration (second derivative) — catches accelerating trends
        group[f"{metric}_accel"] = group[f"{metric}_slope"].diff() / 15.0

        out.append(group[[f"{metric}_slope", f"{metric}_rolling_std",
                           f"{metric}_rolling_mean", f"{metric}_accel"]])

    features = pd.concat(out, axis=1).dropna()
    return features

features = engineer_features(df)
features.to_parquet("deca_features.parquet")
```

### 3.3 Labeling fault runs

```python
def label_fault_windows(features, fault_log_csv):
    """
    fault_log_csv columns: fault_type, fault_start, breach_time
    Produces: time_to_breach_minutes, is_precursor (bool)
    """
    fault_log = pd.read_csv(fault_log_csv, parse_dates=["fault_start", "breach_time"])
    features["time_to_breach_minutes"] = np.nan
    features["fault_type"] = "none"

    for _, row in fault_log.iterrows():
        mask = (features.index >= row["fault_start"]) & (features.index <= row["breach_time"])
        minutes_to_breach = (row["breach_time"] - features.index[mask]).total_seconds() / 60.0
        features.loc[mask, "time_to_breach_minutes"] = minutes_to_breach
        features.loc[mask, "fault_type"] = row["fault_type"]

    return features

labeled = label_fault_windows(features, "fault_injection_log.csv")
labeled.to_parquet("deca_labeled_dataset.parquet")
```

---

## 4. ML Prediction Engine

### 4.1 Prophet — per-metric trajectory forecasting

```python
from prophet import Prophet
import pandas as pd

def train_prophet(series_df, metric_col):
    prophet_df = series_df.reset_index()[["timestamp", metric_col]]
    prophet_df.columns = ["ds", "y"]

    model = Prophet(
        changepoint_prior_scale=0.5,
        interval_width=0.90,
        daily_seasonality=False,
        weekly_seasonality=False
    )
    model.fit(prophet_df)

    future = model.make_future_dataframe(periods=40, freq="15S")
    forecast = model.predict(future)
    return model, forecast

model, forecast = train_prophet(labeled, "ifInOctets_rolling_mean")
# forecast[["ds","yhat","yhat_lower","yhat_upper"]] gives predicted trajectory + confidence interval
```

### 4.2 Isolation Forest — multivariate anomaly detection

```python
from sklearn.ensemble import IsolationForest
import joblib

feature_cols = [c for c in labeled.columns if c.endswith(("_slope", "_rolling_std", "_accel"))]

iso = IsolationForest(
    n_estimators=200,
    contamination=0.05,
    random_state=42
)
iso.fit(labeled[feature_cols].dropna())

joblib.dump(iso, "isolation_forest.pkl")

labeled["anomaly_score"] = iso.decision_function(labeled[feature_cols].fillna(0))
labeled["is_anomaly"] = iso.predict(labeled[feature_cols].fillna(0)) == -1
```

### 4.3 LSTM — v1 baseline sequence model

```python
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
import numpy as np

class TelemetrySequenceDataset(Dataset):
    def __init__(self, df, feature_cols, target_col, seq_len=40):
        self.X, self.y = [], []
        values = df[feature_cols].fillna(0).values
        targets = df[target_col].fillna(999).values  # 999 = no breach
        for i in range(len(df) - seq_len):
            self.X.append(values[i:i+seq_len])
            self.y.append(targets[i+seq_len])
        self.X = torch.tensor(np.array(self.X), dtype=torch.float32)
        self.y = torch.tensor(np.array(self.y), dtype=torch.float32)

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]

class FaultLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        last_hidden = out[:, -1, :]
        return self.fc(last_hidden).squeeze(-1)

# Training loop
dataset = TelemetrySequenceDataset(labeled, feature_cols, "time_to_breach_minutes")
loader = DataLoader(dataset, batch_size=32, shuffle=True)

model = FaultLSTM(input_size=len(feature_cols))
optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
criterion = nn.MSELoss()

for epoch in range(50):
    total_loss = 0
    for X_batch, y_batch in loader:
        optimizer.zero_grad()
        pred = model(X_batch)
        loss = criterion(pred, y_batch)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    print(f"Epoch {epoch+1}, loss: {total_loss/len(loader):.4f}")

torch.save(model.state_dict(), "fault_lstm_v1.pt")
```

### 4.4 TFT — v2 upgrade, interpretable transformer

Run this on Google Colab with a free T4 GPU. Requires `pytorch-forecasting`.

```python
# Colab cell 1 — install
!pip install pytorch-forecasting pytorch-lightning -q

# Colab cell 2 — prepare TimeSeriesDataSet
import pandas as pd
from pytorch_forecasting import TimeSeriesDataSet, TemporalFusionTransformer
from pytorch_forecasting.metrics import QuantileLoss
import pytorch_lightning as pl

df = pd.read_parquet("deca_labeled_dataset.parquet").reset_index()
df["time_idx"] = range(len(df))
df["group"] = "deca_link_1"  # single series id, extend if multi-link

feature_cols = [c for c in df.columns if c.endswith(("_slope", "_rolling_std", "_accel"))]

max_encoder_length = 40   # 10 min at 15s resolution
max_prediction_length = 20  # 5 min forecast horizon

training = TimeSeriesDataSet(
    df[:-max_prediction_length],
    time_idx="time_idx",
    target="time_to_breach_minutes",
    group_ids=["group"],
    max_encoder_length=max_encoder_length,
    max_prediction_length=max_prediction_length,
    time_varying_unknown_reals=feature_cols,
    target_normalizer=None,
)

validation = TimeSeriesDataSet.from_dataset(training, df, predict=True, stop_randomization=True)

train_loader = training.to_dataloader(train=True, batch_size=32)
val_loader = validation.to_dataloader(train=False, batch_size=32)

# Colab cell 3 — train
tft = TemporalFusionTransformer.from_dataset(
    training,
    learning_rate=0.03,
    hidden_size=16,
    attention_head_size=2,
    dropout=0.1,
    loss=QuantileLoss(),
)

trainer = pl.Trainer(max_epochs=30, accelerator="gpu", devices=1)
trainer.fit(tft, train_dataloaders=train_loader, val_dataloaders=val_loader)

trainer.save_checkpoint("tft_v2.ckpt")

# Colab cell 4 — interpretability plot (screenshot this for documentation)
raw_predictions = tft.predict(val_loader, mode="raw", return_x=True)
interpretation = tft.interpret_output(raw_predictions.output, reduction="sum")
tft.plot_interpretation(interpretation)
```

Download `tft_v2.ckpt` from Colab, bring it to the laptop for CPU-only inference:

```python
from pytorch_forecasting import TemporalFusionTransformer

tft = TemporalFusionTransformer.load_from_checkpoint("tft_v2.ckpt", map_location="cpu")
tft.eval()
# tft.predict(new_data) for inference, no GPU needed at demo time
```

### 4.5 SHAP — feature attribution for the LLM

```python
import shap

# Wrap Isolation Forest score as a black-box function for SHAP
def predict_fn(X):
    return iso.decision_function(X)

explainer = shap.KernelExplainer(predict_fn, labeled[feature_cols].sample(100))
shap_values = explainer.shap_values(labeled[feature_cols].iloc[[current_row_idx]])

contributions = dict(zip(feature_cols, shap_values[0]))
top_contributors = sorted(contributions.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
# Feed top_contributors directly into the LLM prompt context
```

### 4.6 Confidence calibration

```python
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression

# Binary breach/no-breach classifier calibrated with Platt scaling
raw_model = LogisticRegression()
calibrated = CalibratedClassifierCV(raw_model, method="sigmoid", cv=5)
calibrated.fit(X_train, y_train_binary)

calibrated_confidence = calibrated.predict_proba(X_new)[:, 1]
# This number is what you report to the operator as "87% confidence" — genuinely calibrated
```

---

## 5. Offline LLM Copilot

### 5.1 llama.cpp setup

```bash
CMAKE_ARGS="-DLLAMA_CUBLAS=off" pip install llama-cpp-python --break-system-packages
```

```python
from llama_cpp import Llama

llm = Llama(
    model_path="/opt/models/deepseek-r1-distill-qwen-1.5b-q4_k_m.gguf",
    n_ctx=2048,
    n_threads=6,
    verbose=False
)
```

### 5.2 Local embedding model, GGUF only, never sentence-transformers

```python
embed_model = Llama(
    model_path="/opt/models/all-minilm-l6-v2.gguf",
    embedding=True,
    n_ctx=512,
    verbose=False
)

class LocalGGUFEmbedding:
    def __call__(self, input):
        return [embed_model.embed(text) for text in input]
```

### 5.3 ChromaDB with local embedding

```python
import chromadb

chroma_client = chromadb.PersistentClient(path="./chroma_store")
collection = chroma_client.create_collection(
    name="runbooks",
    embedding_function=LocalGGUFEmbedding()
)

# Populate with runbook documents
runbooks = [
    ("congestion-hub-spoke", open("runbooks/congestion.md").read()),
    ("bgp-flap", open("runbooks/bgp_flap.md").read()),
    ("tunnel-degradation", open("runbooks/tunnel_degradation.md").read()),
    ("policy-drift", open("runbooks/policy_drift.md").read()),
    ("vrf-leakage", open("runbooks/vrf_leakage.md").read()),
]

for doc_id, content in runbooks:
    collection.add(documents=[content], ids=[doc_id])
```

### 5.4 RAG query with confidence gating

```python
def query_rag(question, min_similarity=0.6):
    results = collection.query(query_texts=[question], n_results=3)
    top_similarity = 1 - results["distances"][0][0]

    if top_similarity < min_similarity:
        return None, "INSUFFICIENT_CONTEXT"

    return results["documents"][0], top_similarity
```

### 5.5 Structured LLM prompt

```python
SYSTEM_PROMPT = """You are an offline NOC copilot for a secure MPLS network.
You ONLY use information provided in CONTEXT. Never invent device names,
IP addresses, VRF names, or AS numbers. If context is insufficient, say so.
Always respond in this JSON format only:
{
  "predicted_issue": "...",
  "confidence_score": 0.XX,
  "time_to_impact_minutes": X,
  "root_cause": "...",
  "affected_scope": ["site", "vrf", "service"],
  "contributing_signals": {"signal_name": contribution_pct},
  "recommended_actions": ["step1", "step2"]
}"""

def generate_alert_explanation(prediction, shap_contributions, retrieved_docs):
    context = f"""
ML PREDICTION:
  Fault type: {prediction['fault_type']}
  Confidence (calibrated): {prediction['confidence']}
  Time to breach: {prediction['time_to_breach']} minutes
  SHAP contributions: {shap_contributions}

RETRIEVED RUNBOOK:
  {retrieved_docs}
"""
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": context}
        ],
        temperature=0.2,
        max_tokens=400
    )
    return response["choices"][0]["message"]["content"]
```

---

## 6. Autonomous Loop

```python
import time
import networkx as nx

def autonomous_loop():
    topo = build_topology_graph()

    while True:
        metrics = pull_latest_metrics()
        features = engineer_features(metrics)

        prophet_forecast = run_prophet(features)
        anomaly_score = iso.decision_function(features[feature_cols])
        lstm_prediction = model(torch.tensor(features[feature_cols].values, dtype=torch.float32))

        confidence = calibrated.predict_proba(features[feature_cols])[:, 1][0]

        if confidence > 0.65:
            shap_contributions = compute_shap(features)
            affected_paths = trace_fault_propagation(topo, root_node=current_link)
            retrieved_docs, similarity = query_rag(f"fault on {current_link}")

            explanation = generate_alert_explanation(
                {"fault_type": predicted_type, "confidence": confidence,
                 "time_to_breach": lstm_prediction.item()},
                shap_contributions,
                retrieved_docs
            )

            push_alert_to_dashboard(explanation, urgency=confidence / max(lstm_prediction.item(), 1))

        time.sleep(60)
```

---

## 7. NVIDIA GPU Training Summary

| Step | Where | Notes |
|---|---|---|
| Prophet, Isolation Forest, SHAP | Laptop CPU | Fast, no GPU needed |
| LSTM v1 training | Laptop CPU or Colab T4 | Small model, CPU acceptable for v1 |
| TFT v2 training | Google Colab T4 (free) — https://colab.research.google.com | ~1-3 hours for this dataset size |
| Kaggle alternative | https://www.kaggle.com/code — 30 GPU-hrs/week free | Backup if Colab session limits hit |
| All inference at demo time | Laptop CPU only | Trained weights downloaded once, no GPU or internet needed after |

---

## 8. File Checklist Before Demo

- [ ] `deca_labeled_dataset.parquet` — final feature-engineered, labeled dataset
- [ ] `isolation_forest.pkl`
- [ ] `fault_lstm_v1.pt` or `tft_v2.ckpt`
- [ ] `/opt/models/deepseek-r1-distill-qwen-1.5b-q4_k_m.gguf`
- [ ] `/opt/models/all-minilm-l6-v2.gguf`
- [ ] `chroma_store/` populated with 5+ runbooks and 10+ incident records
- [ ] Ablation comparison table (threshold vs Prophet vs TFT lead time)
- [ ] TFT interpretability plot screenshot from Colab
- [ ] Calibration curve plot
