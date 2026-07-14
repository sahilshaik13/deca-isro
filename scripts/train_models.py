#!/usr/bin/env python3
"""Train DECA prediction stack on the current unified feature matrix.

Maps to docs/DECA_Model_Development_Blueprint.md:
  1. Isolation Forest + Platt calibration (anomaly confidence)
  2. Prophet additive models (macro trajectory: octets / jitter / BGP rate)
  3. LSTM (time-to-breach micro sequences)
  4. NetworkX CE–PE–CE topology artifact (alert dedup / eccentricity)
Plus multiclass XGBoost on unified_label (healthy + four lab faults) so network
and public rows share one classification vocabulary.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
from prophet import Prophet
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from tensorflow import keras
from tensorflow.keras import layers
from xgboost import XGBClassifier

from _paths import MODELS_DIR, PROCESSED_DIR, REPO_ROOT
from rebuild_unified import UNIFIED_LABELS, to_unified_label

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEQ_LEN = 16
RANDOM_STATE = 42
META_COLS = {
    "run_id",
    "source",
    "fault_type",
    "unified_label",
    "is_anomaly",
    "time_to_breach_minutes",
    "timestamp",
}

# One subdirectory per model family under models/
MODEL_DIRS = {
    "isolation_forest": "isolation_forest",
    "fault_classifier": "fault_classifier",
    "prophet_ifInOctets": "prophet_ifInOctets",
    "prophet_jitter_ms": "prophet_jitter_ms",
    "prophet_bgp_update_rate": "prophet_bgp_update_rate",
    "lstm": "lstm",
    "topology": "topology",
}


def model_dir(name: str) -> Path:
    """Return models/<name>/, creating it if needed."""
    key = MODEL_DIRS.get(name, name)
    d = MODELS_DIR / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel_model_path(name: str, filename: str) -> str:
    return f"models/{MODEL_DIRS.get(name, name)}/{filename}"


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c not in META_COLS
        and (
            c.endswith("_slope")
            or c.endswith("_rolling_std")
            or c.endswith("_rolling_mean")
            or c.endswith("_accel")
        )
    ]


def load_dataset() -> tuple[pd.DataFrame, list[str]]:
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    df = pd.read_parquet(path)
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if "is_anomaly" not in df.columns:
        df["is_anomaly"] = (df["unified_label"] != "healthy").astype(int)
    # Ensure index time is available for sequences
    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
        else:
            df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)
    if not feats:
        raise SystemExit("No engineered feature columns found in dataset")
    return df, feats


def wipe_old_models() -> None:
    import shutil

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for p in list(MODELS_DIR.iterdir()):
        if p.is_file():
            p.unlink()
            removed += 1
        elif p.is_dir():
            shutil.rmtree(p)
            removed += 1
    print(f"Cleared models/ ({removed} entries)")


def train_isolation_forest(df: pd.DataFrame, feats: list[str]) -> dict:
    print("\n=== 1. Isolation Forest + Platt calibration ===")
    X = df[feats]
    y = df["is_anomaly"].astype(int).values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=y
    )

    # Fit IF on healthy train rows only (blueprint: isolate structural faults)
    healthy_mask = y_train == 0
    pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            (
                "iforest",
                IsolationForest(
                    n_estimators=300,
                    contamination=min(0.08, max(0.02, float(y_train.mean()) or 0.05)),
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipe.fit(X_train[healthy_mask])

    def anomaly_score(frame: pd.DataFrame) -> np.ndarray:
        # Higher = more anomalous (flip sklearn decision_function)
        return -pipe.decision_function(frame)

    train_scores = anomaly_score(X_train)
    test_scores = anomaly_score(X_test)

    # Platt via logistic calibration on scores → P(anomaly)
    from sklearn.linear_model import LogisticRegression

    calibrator = LogisticRegression(max_iter=1000)
    calibrator.fit(train_scores.reshape(-1, 1), y_train)
    test_prob = calibrator.predict_proba(test_scores.reshape(-1, 1))[:, 1]
    auc = roc_auc_score(y_test, test_prob) if len(np.unique(y_test)) > 1 else float("nan")
    print(f"  IF+Platt ROC-AUC={auc:.4f}  (test n={len(y_test)}, anomalies={int(y_test.sum())})")

    out = model_dir("isolation_forest")
    joblib.dump(pipe, out / "isolation_forest.pkl")
    joblib.dump(calibrator, out / "confidence_calibrator.pkl")
    # Keep standalone scaler alias for inference convenience
    joblib.dump(
        {
            "imputer": pipe.named_steps["imputer"],
            "scaler": pipe.named_steps["scaler"],
            "feature_columns": feats,
        },
        out / "feature_scaler.pkl",
    )
    return {
        "name": "isolation_forest",
        "auc": float(auc),
        "contamination": float(pipe.named_steps["iforest"].contamination),
    }


def train_classifier(df: pd.DataFrame, feats: list[str]) -> dict:
    print("\n=== Classification (unified_label) ===")
    X = df[feats]
    y_raw = df["unified_label"].astype(str)
    # Drop classes with < 2 samples (shouldn't happen)
    counts = y_raw.value_counts()
    keep = counts[counts >= 5].index
    mask = y_raw.isin(keep)
    X, y_raw = X.loc[mask], y_raw.loc[mask]

    le_classes = [c for c in UNIFIED_LABELS if c in set(y_raw)]
    for c in sorted(set(y_raw) - set(le_classes)):
        le_classes.append(c)
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = y_raw.map(class_to_idx).astype(int).values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=RANDOM_STATE, stratify=y
    )

    clf = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "xgb",
                XGBClassifier(
                    n_estimators=200,
                    max_depth=5,
                    learning_rate=0.08,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    clf.fit(X_train, y_train)
    pred = clf.predict(X_test)
    macro_f1 = f1_score(y_test, pred, average="macro")
    report = classification_report(
        y_test, pred, target_names=le_classes, zero_division=0, output_dict=True
    )
    print(f"  macro-F1={macro_f1:.4f}")
    print(classification_report(y_test, pred, target_names=le_classes, zero_division=0))

    out = model_dir("fault_classifier")
    joblib.dump(clf, out / "fault_classifier_xgb.pkl")
    joblib.dump({"classes": le_classes}, out / "label_encoder.pkl")

    cm = confusion_matrix(y_test, pred, labels=list(range(len(le_classes))))
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(le_classes)))
    ax.set_yticks(range(len(le_classes)))
    ax.set_xticklabels(le_classes, rotation=45, ha="right")
    ax.set_yticklabels(le_classes)
    ax.set_xlabel("Predicted unified_label")
    ax.set_ylabel("True unified_label")
    ax.set_title(f"DECA unified_label classifier (macro-F1={macro_f1:.3f})")
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", color="black", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(out / "scorecard.png", dpi=140)
    plt.close(fig)

    # Top feature importances (SHAP substitute — shap not installed)
    booster = clf.named_steps["xgb"]
    importances = booster.feature_importances_
    top = sorted(zip(feats, importances), key=lambda t: t[1], reverse=True)[:15]
    attribution = [{"feature": f, "importance": float(v)} for f, v in top]
    (out / "feature_attribution.json").write_text(json.dumps(attribution, indent=2))
    print("  wrote feature_attribution.json (XGBoost gain proxy; install shap for full SHAP)")

    return {
        "name": "fault_classifier_xgb",
        "macro_f1": float(macro_f1),
        "classes": le_classes,
        "per_class_f1": {c: float(report[c]["f1-score"]) for c in le_classes if c in report},
    }


def train_prophet() -> list[dict]:
    print("\n=== 2. Prophet macro forecasts ===")
    raw = pd.read_parquet(PROCESSED_DIR / "deca_unified_raw.parquet")
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    metrics = [
        ("ifInOctets", "prophet_ifInOctets"),
        ("jitter_ms", "prophet_jitter_ms"),
        ("bgp_update_rate", "prophet_bgp_update_rate"),
    ]
    artifacts = []
    for metric, folder in metrics:
        series = (
            raw.loc[raw["metric"] == metric, ["timestamp", "value"]]
            .dropna()
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
        )
        if len(series) < 40:
            print(f"  skip {metric}: only {len(series)} points")
            continue
        # Cap points for CPU — keep evenly spaced sample of up to 8k
        if len(series) > 8000:
            idx = np.linspace(0, len(series) - 1, 8000).astype(int)
            series = series.iloc[idx]
        pdf = pd.DataFrame(
            {
                "ds": series["timestamp"].dt.tz_localize(None),
                "y": series["value"].astype(float),
            }
        )
        m = Prophet(
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            changepoint_prior_scale=0.05,
        )
        m.fit(pdf)
        out = model_dir(folder)
        fname = f"{folder}.pkl"
        joblib.dump(m, out / fname)
        print(f"  fitted {metric} on {len(pdf)} points → {folder}/{fname}")
        artifacts.append(
            {
                "name": folder,
                "file": rel_model_path(folder, fname),
                "type": "prophet",
                "n": len(pdf),
            }
        )
    return artifacts


def build_sequences(
    df: pd.DataFrame, feats: list[str], seq_len: int = SEQ_LEN
) -> tuple[np.ndarray, np.ndarray]:
    """Sliding windows labeled by time_to_breach at the window end (network faults)."""
    sub = df[df["source"] == "network"].copy().sort_index()
    # Deduplicate timestamps so sequences are well-defined
    sub = sub[~sub.index.duplicated(keep="last")]
    filled = sub[feats].copy()
    filled = filled.fillna(filled.median(numeric_only=True)).fillna(0.0).astype(np.float32)
    ttb = sub["time_to_breach_minutes"].astype(float).to_numpy()
    mat = filled.to_numpy()
    Xs, ys = [], []
    for i in range(seq_len - 1, len(mat)):
        target = ttb[i]
        if np.isnan(target):
            continue
        Xs.append(mat[i - seq_len + 1 : i + 1])
        ys.append(float(target))
    if not Xs:
        return np.empty((0, seq_len, len(feats))), np.empty((0,))
    return np.asarray(Xs, dtype=np.float32), np.asarray(ys, dtype=np.float32)


def train_lstm(df: pd.DataFrame, feats: list[str]) -> dict | None:
    print("\n=== 3. LSTM time-to-breach ===")
    X, y = build_sequences(df, feats)
    if len(X) < 40:
        print(f"  skip LSTM: only {len(X)} sequences (need ≥40)")
        return None

    # Cap for CPU time
    if len(X) > 4000:
        rng = np.random.default_rng(RANDOM_STATE)
        pick = rng.choice(len(X), size=4000, replace=False)
        X, y = X[pick], y[pick]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )
    # Per-feature standardize using train flatten
    flat = X_train.reshape(-1, X_train.shape[-1])
    mu = flat.mean(axis=0)
    sigma = flat.std(axis=0)
    sigma[sigma < 1e-8] = 1.0
    X_train = (X_train - mu) / sigma
    X_test = (X_test - mu) / sigma

    model = keras.Sequential(
        [
            layers.Input(shape=(SEQ_LEN, len(feats))),
            layers.LSTM(64, return_sequences=True),
            layers.LSTM(32),
            layers.Dense(32, activation="relu"),
            layers.Dense(1),
        ]
    )
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse", metrics=["mae"])
    model.fit(
        X_train,
        y_train,
        validation_split=0.15,
        epochs=12,
        batch_size=64,
        verbose=1,
    )
    pred = model.predict(X_test, verbose=0).ravel()
    mae = mean_absolute_error(y_test, pred)
    print(f"  LSTM MAE={mae:.3f} minutes  (test n={len(y_test)})")

    out = model_dir("lstm")
    model.save(out / "fault_lstm_v1.keras")
    joblib.dump(
        {"mean": mu, "std": sigma, "feature_columns": feats, "seq_len": SEQ_LEN},
        out / "lstm_scaler.pkl",
    )
    return {"name": "fault_lstm_v1", "mae_minutes": float(mae), "n_sequences": int(len(X))}


def build_topology() -> dict:
    print("\n=== 4. NetworkX CE–PE–CE topology ===")
    g = nx.DiGraph()
    # Mirrors lab: PE1 / PE2 / CORE
    nodes = {
        "PE1": {"host": "station1", "ip": "192.168.50.10"},
        "PE2": {"host": "station2", "ip": "192.168.50.20"},
        "CORE": {"host": "station3", "ip": "192.168.50.30"},
    }
    for n, attrs in nodes.items():
        g.add_node(n, **attrs)
    g.add_edge("PE1", "CORE", link="ce-pe")
    g.add_edge("CORE", "PE1", link="pe-ce")
    g.add_edge("PE2", "CORE", link="ce-pe")
    g.add_edge("CORE", "PE2", link="pe-ce")
    g.add_edge("PE1", "PE2", link="overlay")

    ecc = {}
    und = g.to_undirected()
    if nx.is_connected(und):
        ecc = {n: nx.eccentricity(und, n) for n in und.nodes}
    payload = {
        "nodes": [{"id": n, **nodes[n]} for n in g.nodes],
        "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
        "eccentricity": ecc,
    }
    out = model_dir("topology")
    (out / "topology_graph.json").write_text(json.dumps(payload, indent=2))
    joblib.dump(g, out / "topology_graph.pkl")
    print("  wrote topology/{topology_graph.json, topology_graph.pkl}")
    return {"name": "topology_graph", "nodes": list(g.nodes), "eccentricity": ecc}


def main() -> None:
    print(f"Repo: {REPO_ROOT}")
    wipe_old_models()
    df, feats = load_dataset()
    print(
        f"Dataset: {len(df)} rows · features={len(feats)} · "
        f"sources={df['source'].value_counts().to_dict()}"
    )
    print("unified_label:\n", df["unified_label"].value_counts().to_string())

    metrics = {
        "training_date": datetime.now(timezone.utc).isoformat(),
        "row_counts_by_source": df["source"].value_counts().to_dict(),
        "unified_label_counts": df["unified_label"].value_counts().to_dict(),
        "feature_columns": feats,
        "unified_labels": list(UNIFIED_LABELS),
        "models": [],
    }

    if_stats = train_isolation_forest(df, feats)
    metrics["models"].append(
        {
            "name": "isolation_forest",
            "file": rel_model_path("isolation_forest", "isolation_forest.pkl"),
            "type": "sklearn",
            "metrics": if_stats,
        }
    )
    metrics["models"].append(
        {
            "name": "confidence_calibrator",
            "file": rel_model_path("isolation_forest", "confidence_calibrator.pkl"),
            "type": "sklearn",
        }
    )
    metrics["models"].append(
        {
            "name": "feature_scaler",
            "file": rel_model_path("isolation_forest", "feature_scaler.pkl"),
            "type": "sklearn",
        }
    )

    clf_stats = train_classifier(df, feats)
    metrics["models"].append(
        {
            "name": "fault_classifier_xgb",
            "file": rel_model_path("fault_classifier", "fault_classifier_xgb.pkl"),
            "type": "xgboost",
            "metrics": {k: v for k, v in clf_stats.items() if k != "name"},
        }
    )
    metrics["models"].append(
        {
            "name": "label_encoder",
            "file": rel_model_path("fault_classifier", "label_encoder.pkl"),
            "type": "sklearn",
        }
    )
    metrics["models"].append(
        {
            "name": "scorecard",
            "file": rel_model_path("fault_classifier", "scorecard.png"),
            "type": "artifact",
        }
    )
    metrics["models"].append(
        {
            "name": "feature_attribution",
            "file": rel_model_path("fault_classifier", "feature_attribution.json"),
            "type": "artifact",
        }
    )

    for art in train_prophet():
        metrics["models"].append(art)

    lstm_stats = train_lstm(df, feats)
    if lstm_stats:
        metrics["models"].append(
            {
                "name": "fault_lstm_v1",
                "file": rel_model_path("lstm", "fault_lstm_v1.keras"),
                "type": "keras",
                "metrics": lstm_stats,
            }
        )
        metrics["models"].append(
            {
                "name": "lstm_scaler",
                "file": rel_model_path("lstm", "lstm_scaler.pkl"),
                "type": "sklearn",
            }
        )

    topo = build_topology()
    metrics["models"].append(
        {
            "name": "topology_graph",
            "file": rel_model_path("topology", "topology_graph.json"),
            "type": "networkx",
            "metrics": topo,
        }
    )

    (MODELS_DIR / "manifest.json").write_text(json.dumps(metrics, indent=2, default=str))
    print(f"\nWrote {MODELS_DIR / 'manifest.json'}")
    print("Training complete.")


if __name__ == "__main__":
    main()
