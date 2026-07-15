#!/usr/bin/env python3
"""Retrain companion models (IF, Prophet ×3, LSTM, topology) on the current lake.

Does **not** touch the promoted fault classifier — that is owned by the School Exam /
orchestrator promotion gate. Use this after Mode B ingest when companions are still
fitted on the previous lake distribution.

  python scripts/deca_retrain_companions.py
  python scripts/deca_retrain_companions.py --skip-prophet --skip-lstm
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import feature_columns
from rebuild_unified import to_unified_label

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

RANDOM_STATE = 42
SEQ_LEN = 16
PROPHET_METRICS = (
    ("ifInOctets", "prophet_ifInOctets"),
    ("jitter_ms", "prophet_jitter_ms"),
    ("bgp_update_rate", "prophet_bgp_update_rate"),
)


def load_lake() -> tuple[pd.DataFrame, list[str]]:
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    df = pd.read_parquet(path)
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if "is_anomaly" not in df.columns:
        df["is_anomaly"] = (df["unified_label"] != "healthy").astype(int)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    return df, feature_columns(df)


def train_isolation_forest(df: pd.DataFrame, feats: list[str]) -> dict:
    X = df[feats]
    y_bin = df["is_anomaly"].astype(int).values
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y_bin, test_size=0.25, random_state=RANDOM_STATE, stratify=y_bin
    )
    healthy = y_tr == 0
    contamination = min(0.08, max(0.02, float(y_tr.mean()) or 0.05))
    pipe = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            (
                "iforest",
                IsolationForest(
                    n_estimators=300,
                    contamination=contamination,
                    random_state=RANDOM_STATE,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipe.fit(X_tr[healthy])

    def anom_score(frame):
        return -pipe.decision_function(frame)

    tr_scores = anom_score(X_tr)
    te_scores = anom_score(X_te)
    calibrator = LogisticRegression(max_iter=1000)
    calibrator.fit(tr_scores.reshape(-1, 1), y_tr)
    te_prob = calibrator.predict_proba(te_scores.reshape(-1, 1))[:, 1]
    auc = float(roc_auc_score(y_te, te_prob))

    out = MODELS_DIR / "isolation_forest"
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, out / "isolation_forest.pkl")
    joblib.dump(calibrator, out / "confidence_calibrator.pkl")
    joblib.dump(
        {
            "imputer": pipe.named_steps["imputer"],
            "scaler": pipe.named_steps["scaler"],
            "feature_columns": feats,
        },
        out / "feature_scaler.pkl",
    )
    stats = {
        "auc": auc,
        "contamination": float(contamination),
        "test_n": int(len(y_te)),
        "anomaly_rate_test": float(y_te.mean()),
    }
    print(f"  IF+Platt ROC-AUC={auc:.4f}  contamination={contamination:.4f}")
    return stats


def train_prophet() -> list[dict]:
    from prophet import Prophet

    raw_path = PROCESSED_DIR / "deca_unified_raw.parquet"
    if not raw_path.exists():
        print(f"  skip Prophet — missing {raw_path}")
        return []
    raw = pd.read_parquet(raw_path)
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
    results = []
    for metric, folder in PROPHET_METRICS:
        series = (
            raw.loc[raw["metric"] == metric, ["timestamp", "value"]]
            .dropna()
            .sort_values("timestamp")
            .drop_duplicates("timestamp", keep="last")
        )
        if len(series) < 40:
            print(f"  skip Prophet {metric}: n={len(series)}")
            continue
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
        out = MODELS_DIR / folder
        out.mkdir(parents=True, exist_ok=True)
        joblib.dump(m, out / f"{folder}.pkl")
        results.append({"name": folder, "n": int(len(pdf)), "metric": metric})
        print(f"  Prophet {metric}: n={len(pdf)}")
    return results


def train_lstm(df: pd.DataFrame, feats: list[str]) -> dict | None:
    try:
        from tensorflow import keras
        from tensorflow.keras import layers
    except ImportError:
        print("  skip LSTM — tensorflow not installed")
        return None

    sub = df[df["source"] == "network"].copy().sort_index()
    sub = sub[~sub.index.duplicated(keep="last")]
    if "time_to_breach_minutes" not in sub.columns:
        print("  skip LSTM — missing time_to_breach_minutes")
        return None
    filled = sub[feats].copy()
    filled = filled.fillna(filled.median(numeric_only=True)).fillna(0.0).astype(np.float32)
    ttb = sub["time_to_breach_minutes"].astype(float).to_numpy()
    mat = filled.to_numpy()
    Xs, ys = [], []
    for i in range(SEQ_LEN - 1, len(mat)):
        if np.isnan(ttb[i]):
            continue
        Xs.append(mat[i - SEQ_LEN + 1 : i + 1])
        ys.append(float(ttb[i]))
    X_seq = np.asarray(Xs, dtype=np.float32)
    y_seq = np.asarray(ys, dtype=np.float32)
    if len(X_seq) < 40:
        print(f"  skip LSTM — only {len(X_seq)} sequences")
        return None
    n_full = int(len(X_seq))
    if len(X_seq) > 4000:
        rng = np.random.default_rng(RANDOM_STATE)
        pick = rng.choice(len(X_seq), size=4000, replace=False)
        X_seq, y_seq = X_seq[pick], y_seq[pick]

    Xtr, Xte, ytr, yte = train_test_split(
        X_seq, y_seq, test_size=0.2, random_state=RANDOM_STATE
    )
    flat = Xtr.reshape(-1, Xtr.shape[-1])
    mu, sigma = flat.mean(0), flat.std(0)
    sigma[sigma < 1e-8] = 1.0
    Xtr = (Xtr - mu) / sigma
    Xte = (Xte - mu) / sigma

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
    model.fit(Xtr, ytr, validation_split=0.15, epochs=12, batch_size=64, verbose=0)
    pred = model.predict(Xte, verbose=0).ravel()
    mae = float(mean_absolute_error(yte, pred))

    out = MODELS_DIR / "lstm"
    out.mkdir(parents=True, exist_ok=True)
    model.save(out / "fault_lstm_v1.keras")
    joblib.dump(
        {"mean": mu, "std": sigma, "feature_columns": feats, "seq_len": SEQ_LEN},
        out / "lstm_scaler.pkl",
    )
    stats = {
        "mae_minutes": mae,
        "n_sequences_used": int(len(X_seq)),
        "n_sequences_available": n_full,
        "test_n": int(len(yte)),
    }
    print(f"  LSTM MAE={mae:.3f} min  sequences={n_full} (fit on {len(X_seq)})")
    return stats


def write_topology() -> dict:
    g = nx.DiGraph()
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
    und = g.to_undirected()
    ecc = {n: nx.eccentricity(und, n) for n in und.nodes} if nx.is_connected(und) else {}
    payload = {
        "nodes": [{"id": n, **nodes[n]} for n in g.nodes],
        "edges": [{"source": u, "target": v, **d} for u, v, d in g.edges(data=True)],
        "eccentricity": ecc,
    }
    out = MODELS_DIR / "topology"
    out.mkdir(parents=True, exist_ok=True)
    (out / "topology_graph.json").write_text(json.dumps(payload, indent=2))
    joblib.dump(g, out / "topology_graph.pkl")
    print(f"  topology eccentricity={ecc}")
    return {"eccentricity": ecc}


def patch_manifest(
    df: pd.DataFrame,
    feats: list[str],
    *,
    if_stats: dict | None,
    prophet_arts: list[dict],
    lstm_stats: dict | None,
    topo: dict,
) -> None:
    man_path = MODELS_DIR / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    man["companions_retrain_date"] = datetime.now(timezone.utc).isoformat()
    man["row_counts_by_source"] = {
        str(k): int(v) for k, v in df["source"].value_counts().items()
    }
    man["unified_label_counts"] = {
        str(k): int(v) for k, v in df["unified_label"].value_counts().items()
    }
    man["feature_columns"] = feats
    man["n_rows"] = int(len(df))

    # Refresh scoreboard companion lines; keep XGB line from school_exam if present.
    summary = []
    if if_stats:
        summary.append(
            {
                "Component": "Isolation Forest + Platt",
                "Primary score": f"ROC-AUC {if_stats['auc']:.3f}",
                "Notes": "Retrained on post–Tier-6 lake",
            }
        )
    se = man.get("school_exam") or {}
    if se.get("exam_macro_f1") is not None:
        summary.append(
            {
                "Component": "XGBoost Phase 1 (tiers 1–3)",
                "Primary score": (
                    f"Macro-F1 {se['exam_macro_f1']:.3f} "
                    f"(promoted {se.get('head_family', '?')})"
                ),
                "Notes": "School Exam Mode B; SMOTE refused",
            }
        )
    if lstm_stats:
        summary.append(
            {
                "Component": "LSTM time-to-breach",
                "Primary score": f"MAE {lstm_stats['mae_minutes']:.3f} min",
                "Notes": (
                    f"{lstm_stats.get('n_sequences_available', '?')} network sequences, "
                    f"T={SEQ_LEN}"
                ),
            }
        )
    if prophet_arts:
        pts = " / ".join(str(a["n"]) for a in prophet_arts)
        summary.append(
            {
                "Component": "Prophet ×3",
                "Primary score": "Fit complete",
                "Notes": f"{pts} points (ifInOctets / jitter / bgp)",
            }
        )
    ecc = topo.get("eccentricity")
    summary.append(
        {
            "Component": "Topology",
            "Primary score": f"e(v)={ecc}",
            "Notes": "PE1–PE2–CORE digraph",
        }
    )
    man.setdefault("scoreboard", {})["summary"] = summary

    models = man.get("models") or []
    by_name = {m.get("name"): m for m in models}

    def upsert(name: str, payload: dict) -> None:
        if name in by_name:
            by_name[name].update(payload)
        else:
            models.append({"name": name, **payload})
            by_name[name] = models[-1]

    if if_stats:
        upsert(
            "isolation_forest",
            {
                "file": "models/isolation_forest/isolation_forest.pkl",
                "type": "sklearn",
                "metrics": if_stats,
            },
        )
    if lstm_stats:
        upsert(
            "lstm",
            {
                "file": "models/lstm/fault_lstm_v1.keras",
                "type": "keras",
                "metrics": lstm_stats,
            },
        )
    for a in prophet_arts:
        upsert(
            a["name"],
            {
                "file": f"models/{a['name']}/{a['name']}.pkl",
                "type": "prophet",
                "metrics": {"n": a["n"], "metric": a["metric"]},
            },
        )
    man["models"] = models
    man_path.write_text(json.dumps(man, indent=2))
    print(f"  Patched {man_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrain IF / Prophet / LSTM / topology")
    parser.add_argument("--skip-if", action="store_true")
    parser.add_argument("--skip-prophet", action="store_true")
    parser.add_argument("--skip-lstm", action="store_true")
    parser.add_argument("--skip-topology", action="store_true")
    args = parser.parse_args()

    print(f"\n{'=' * 60}\n▶ Retrain companions (fault classifier untouched)\n{'=' * 60}")
    df, feats = load_lake()
    print(f"Lake rows={len(df):,}  features={len(feats)}")
    print("Labels:", df["unified_label"].value_counts().to_dict())

    if_stats = None
    if not args.skip_if:
        print("\n=== Isolation Forest + Platt ===")
        if_stats = train_isolation_forest(df, feats)

    prophet_arts: list[dict] = []
    if not args.skip_prophet:
        print("\n=== Prophet ×3 ===")
        prophet_arts = train_prophet()

    lstm_stats = None
    if not args.skip_lstm:
        print("\n=== LSTM time-to-breach ===")
        lstm_stats = train_lstm(df, feats)

    topo: dict = {}
    if not args.skip_topology:
        print("\n=== Topology ===")
        topo = write_topology()

    print("\n=== Manifest ===")
    patch_manifest(
        df,
        feats,
        if_stats=if_stats,
        prophet_arts=prophet_arts,
        lstm_stats=lstm_stats,
        topo=topo,
    )

    report = {
        "date": datetime.now(timezone.utc).isoformat(),
        "n_rows": int(len(df)),
        "isolation_forest": if_stats,
        "prophet": prophet_arts,
        "lstm": lstm_stats,
        "topology": topo,
        "fault_classifier": "untouched",
    }
    out = MODELS_DIR / "companions_retrain.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    print(f"{'=' * 60}\nCOMPANIONS DONE\n{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
