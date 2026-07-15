---
tags:
  - deca
  - architecture
  - models
aliases:
  - Model Architectures
cssclasses:
  - wide
---

# DECA — model architectures

Internals of each live artifact under `models/`. Training loop: [[DECA_Training_Architecture]]

---

## Stack map

```mermaid
flowchart TB
    X["x ∈ ℝ²⁰<br/>slope · rolling_std · rolling_mean · accel"]

    X --> IF["① Isolation Forest + Platt"]
    X --> XGB["② XGB two-stage ensemble"]
    X --> LSTM["③ LSTM time-to-breach"]
    RAW["raw telemetry series"] --> P["④ Prophet ×3"]
    LAB["PE1 · PE2 · CORE"] --> TOPO["⑤ Topology digraph"]

    IF --> O1["P(anomaly)"]
    XGB --> O2["unified_label"]
    LSTM --> O3["minutes to breach"]
    P --> O4["ŷ(t) envelopes"]
    TOPO --> O5["e(v) / alert root"]
```

---

## ① Isolation Forest + Platt

300 trees · contamination ≈ 0.073 · `models/isolation_forest/`

```mermaid
flowchart LR
    F["x ∈ ℝ²⁰"] --> I["Imputer"] --> S["Scaler"] --> IF["IsolationForest<br/>300 trees"]
    IF --> T1["Tree₁"] & T2["Tree₂"] & TN["Tree₃₀₀"]
    T1 & T2 & TN --> SC["s = −decision_function"]
    SC --> LR["LogisticRegression<br/>P = σ(A·s+B)"]
    LR --> OUT["P(anomaly)"]
```

$$
s(x,n)=2^{-E(h(x))/c(n)},\qquad P=\frac{1}{1+e^{As+B}}
$$

---

## ② XGBoost Phase‑1

Gate 200×depth4 · Full 250×depth5 · `models/fault_classifier/`

```mermaid
flowchart TB
    X["x ∈ ℝ²⁰"] --> IMP["Imputer"]
    IMP --> G["Gate XGB<br/>200 trees · depth 4"]
    G --> PA["P(anomaly)"]
    PA -->|P &lt; τ_gate| H["healthy"]
    PA -->|P ≥ τ_gate| F["Full XGB<br/>250 trees · depth 5"]
    F --> DIV["p_c / t_c"]
    DIV --> Y["ŷ = argmax"]
```

$$
w_i=\frac{N}{K\,n_{y_i}},\quad w_i'=w_i\cdot\beta\ \text{(BGP/VRF)}
$$

---

## ③ LSTM *(neural network)*

`(batch, 16, 20)` → 35,265 trainable params · `models/lstm/fault_lstm_v1.keras`

```mermaid
flowchart TB
    IN["Input (16, 20)"] --> L1["LSTM(64)<br/>return_sequences<br/>21,760 params"]
    L1 --> L2["LSTM(32)<br/>12,416 params"]
    L2 --> D1["Dense(32) ReLU<br/>1,056 params"]
    D1 --> D2["Dense(1)<br/>33 params"]
    D2 --> OUT["τ̂ minutes"]
```

```mermaid
flowchart LR
    R1["t−15"] --- R2["…"] --- R16["t"]
    R16 --> Y["y = TTB(t)"]
```

| Layer | Shape | Params |
| --- | --- | ---: |
| LSTM(64) | `(None,16,64)` | 21,760 |
| LSTM(32) | `(None,32)` | 12,416 |
| Dense(32) | `(None,32)` | 1,056 |
| Dense(1) | `(None,1)` | 33 |

---

## ④ Prophet ×3

Additive seasonal model · not a neural net

```mermaid
flowchart TB
    Y["y(t)"] --> G["g(t) trend"]
    Y --> S["s(t) daily+weekly"]
    Y --> E["ε_t"]
    G & S & E --> SUM["ŷ = g + s + ε"]
```

| Series | Fit n |
| --- | ---: |
| ifInOctets | 4,502 |
| jitter_ms | 8,000 |
| bgp_update_rate | 320 |

---

## ⑤ Topology

```mermaid
flowchart LR
    PE1["PE1 e=1"] <--> CORE["CORE e=1"]
    PE2["PE2 e=1"] <--> CORE
    PE1 -.-> PE2
```

$$
e(v)=\max_u d(v,u)=1
$$

---

## Feature vector

```mermaid
mindmap
  root((x ∈ ℝ²⁰))
    BGP
      slope / std / mean / accel
    ifInOctets
      slope / std / mean / accel
    ifOutOctets
      slope / std / mean / accel
    jitter_ms
      slope / std / mean / accel
    packet_loss_pct
      slope / std / mean / accel
```
