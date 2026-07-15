#!/usr/bin/env python3
"""DECA model playground — mixed blind test, one scoreboard for every model.

Draws a stratified random exam paper from the feature lake, then scores each
artifact under models/ independently (Isolation Forest, XGB fault classifier,
LSTM TTB, Prophet ×3, topology metadata). No retrain / no promote.

  python scripts/deca_model_playground.py
  python scripts/deca_model_playground.py --exam-seed 42
  python scripts/deca_model_playground.py --prophet-refit   # slower, honest Prophet

Outputs: models/playground/
See docs/MODELS.md
"""
from __future__ import annotations

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    classification_report,
    f1_score,
    mean_absolute_error,
    recall_score,
    roc_auc_score,
)

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import (
    RARE,
    feature_columns,
    predict_weighted_multiclass,
    stratified_blind_holdout,
)
from rebuild_unified import UNIFIED_LABELS, to_unified_label

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

OUT_DIR = MODELS_DIR / "playground"
PROPHET_METRICS = (
    ("ifInOctets", "prophet_ifInOctets"),
    ("jitter_ms", "prophet_jitter_ms"),
    ("bgp_update_rate", "prophet_bgp_update_rate"),
)


def load_feature_lake() -> tuple[pd.DataFrame, list[str]]:
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    df = pd.read_parquet(path)
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if "is_anomaly" not in df.columns:
        df["is_anomaly"] = (df["unified_label"] != "healthy").astype(int)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)
    return df, feats


def encode_labels(y_raw: pd.Series) -> tuple[np.ndarray, list[str], dict[str, int]]:
    le_classes = [c for c in UNIFIED_LABELS if c in set(y_raw)]
    le_classes += sorted(set(y_raw) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = y_raw.map(class_to_idx).astype(int).values
    return y, le_classes, class_to_idx


def score_isolation_forest(X: pd.DataFrame, y_anom: np.ndarray) -> dict:
    if_dir = MODELS_DIR / "isolation_forest"
    pipe = joblib.load(if_dir / "isolation_forest.pkl")
    cal = joblib.load(if_dir / "confidence_calibrator.pkl")
    meta = joblib.load(if_dir / "feature_scaler.pkl")
    cols = meta.get("feature_columns") or list(X.columns)
    Xm = X[cols]
    raw = -pipe.decision_function(Xm)
    p = cal.predict_proba(raw.reshape(-1, 1))[:, 1]
    out = {
        "model": "isolation_forest",
        "role": "Unknown weirdness / anomaly precursor",
        "n_rows": int(len(Xm)),
        "primary_metric": "roc_auc",
        "roc_auc": float(roc_auc_score(y_anom, p)) if len(np.unique(y_anom)) > 1 else None,
        "average_precision": float(average_precision_score(y_anom, p))
        if y_anom.sum() > 0
        else None,
        "anomaly_rate_true": float(y_anom.mean()),
        "anomaly_rate_pred_mean_p": float(p.mean()),
    }
    return out


def score_fault_classifier(
    X: pd.DataFrame, y: np.ndarray, le_classes: list[str], class_to_idx: dict[str, int]
) -> dict:
    clf_dir = MODELS_DIR / "fault_classifier"
    bundle = joblib.load(clf_dir / "fault_classifier_xgb.pkl")
    le = joblib.load(clf_dir / "label_encoder.pkl")
    classes = list(le.get("classes") or le_classes)
    # Remap if encoder order matches lake labels
    healthy_idx = int(bundle["healthy_idx"])
    rare_ids = [class_to_idx[c] for c in RARE if c in class_to_idx]
    from deca_inference import load_promoted_loom, loom_config_from_bundle

    # Shuffled playground / School Exam papers are not sequences — score raw frames only.
    # Sticky loom boost lives in decision_thresholds.json → loom.metrics (temporal score).
    pred = predict_weighted_multiclass(
        bundle["gate"],
        bundle["full_clf"],
        X,
        healthy_idx=healthy_idx,
        gate_thr=float(bundle["gate_thr"]),
        class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
    )
    report = classification_report(
        y,
        pred,
        labels=list(range(len(classes))),
        target_names=classes,
        zero_division=0,
        output_dict=True,
    )
    rare_recalls = [
        float(recall_score(y == c, pred == c, zero_division=0)) for c in rare_ids
    ]
    loom = loom_config_from_bundle(bundle)
    loom_live = load_promoted_loom()
    loom_metrics = loom_live.get("metrics") if isinstance(loom_live.get("metrics"), dict) else None
    return {
        "model": "fault_classifier_xgb",
        "role": "What is happening now? (multiclass fault ID)",
        "n_rows": int(len(X)),
        "mode": bundle.get("mode"),
        "gate_thr": float(bundle["gate_thr"]),
        "phase": bundle.get("phase"),
        "rare_boost": bundle.get("rare_boost"),
        "head_family": bundle.get("head_family"),
        "loom": {
            "enabled": loom.get("enabled", True),
            "enter_k": loom.get("enter_k"),
            "exit_k": loom.get("exit_k"),
            "applied_on_playground": False,
            "reason": "playground papers are shuffled — use temporal_persist_score / live stream",
            "temporal_boost": {
                "delta_macro_f1": (loom_metrics or {}).get("delta_macro_f1"),
                "raw_macro_f1": ((loom_metrics or {}).get("raw") or {}).get("macro_f1"),
                "persistent_macro_f1": ((loom_metrics or {}).get("persistent") or {}).get(
                    "macro_f1"
                ),
            }
            if loom_metrics
            else None,
        },
        "primary_metric": "macro_f1",
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, pred, average="weighted", zero_division=0)),
        "accuracy": float(accuracy_score(y, pred)),
        "mean_rare_recall": float(np.mean(rare_recalls)) if rare_recalls else None,
        "per_class": {
            c: {
                "precision": float(report[c]["precision"]),
                "recall": float(report[c]["recall"]),
                "f1": float(report[c]["f1-score"]),
                "support": int(report[c]["support"]),
            }
            for c in classes
            if c in report
        },
    }


def score_lstm(df: pd.DataFrame, feats: list[str], blind_index: pd.DatetimeIndex) -> dict:
    try:
        import tensorflow as tf  # noqa: F401
        from tensorflow import keras
    except ImportError:
        from keras import models as keras_models

        keras = type("K", (), {"models": keras_models})()

    scaler = joblib.load(MODELS_DIR / "lstm" / "lstm_scaler.pkl")
    model = keras.models.load_model(MODELS_DIR / "lstm" / "fault_lstm_v1.keras")
    cols = list(scaler["feature_columns"])
    seq_len = int(scaler["seq_len"])
    mean, std = np.asarray(scaler["mean"]), np.asarray(scaler["std"])
    std = np.where(std < 1e-9, 1.0, std)

    net = df[df["source"] == "network"].sort_index()
    if "time_to_breach_minutes" not in net.columns:
        return {"model": "lstm_ttb", "error": "missing time_to_breach_minutes", "n_sequences": 0}

    mat = net[cols].apply(pd.to_numeric, errors="coerce")
    mat = mat.fillna(mat.median(numeric_only=True)).fillna(0.0).values.astype(np.float64)
    ttb = pd.to_numeric(net["time_to_breach_minutes"], errors="coerce").values
    idx = net.index

    blind_set = set(pd.DatetimeIndex(blind_index))
    Xs, ys = [], []
    for i in range(seq_len - 1, len(mat)):
        if np.isnan(ttb[i]):
            continue
        if idx[i] not in blind_set:
            continue
        Xs.append(mat[i - seq_len + 1 : i + 1])
        ys.append(float(ttb[i]))

    if not Xs:
        return {
            "model": "lstm_ttb",
            "role": "When will it break? (minutes to breach)",
            "n_sequences": 0,
            "note": "No network sequences with finite TTB ending on mixed-test rows",
        }

    X = (np.asarray(Xs) - mean) / std
    y = np.asarray(ys, dtype=np.float64)
    pred = model.predict(X, verbose=0).ravel()
    mae = float(mean_absolute_error(y, pred))
    return {
        "model": "lstm_ttb",
        "role": "When will it break? (minutes to breach)",
        "n_sequences": int(len(y)),
        "seq_len": seq_len,
        "primary_metric": "mae_minutes",
        "mae_minutes": mae,
        "rmse_minutes": float(np.sqrt(np.mean((y - pred) ** 2))),
        "mean_true_ttb": float(y.mean()),
        "mean_pred_ttb": float(pred.mean()),
    }


def _prophet_series(raw: pd.DataFrame, metric: str) -> pd.DataFrame:
    s = raw.loc[raw["metric"] == metric, ["timestamp", "value"]].copy()
    s["timestamp"] = pd.to_datetime(s["timestamp"], utc=True)
    s["value"] = pd.to_numeric(s["value"], errors="coerce")
    s = s.dropna().sort_values("timestamp")
    s["ds"] = s["timestamp"].dt.tz_localize(None)
    s["y"] = s["value"]
    return s[["ds", "y"]].drop_duplicates("ds")


def score_prophet(
    holdout_frac: float, *, honest_refit: bool, max_points: int = 8000
) -> list[dict]:
    from prophet import Prophet

    raw_path = PROCESSED_DIR / "deca_unified_raw.parquet"
    if not raw_path.exists():
        return [{"model": "prophet", "error": f"missing {raw_path}"}]
    raw = pd.read_parquet(raw_path)
    results = []
    for metric, folder in PROPHET_METRICS:
        series = _prophet_series(raw, metric)
        if len(series) < 20:
            results.append(
                {
                    "model": f"prophet_{metric}",
                    "role": "Macro baseline / seasonality envelope",
                    "n_points": int(len(series)),
                    "error": "series too short",
                }
            )
            continue
        if len(series) > max_points:
            # Match training downsample for jitter
            pick = np.linspace(0, len(series) - 1, max_points).astype(int)
            series = series.iloc[pick].reset_index(drop=True)

        n_hold = max(5, int(round(len(series) * holdout_frac)))
        n_hold = min(n_hold, len(series) // 5)
        train, hold = series.iloc[:-n_hold], series.iloc[-n_hold:]
        pkl = MODELS_DIR / folder / f"{folder}.pkl"

        if honest_refit:
            m = Prophet(
                daily_seasonality=True,
                weekly_seasonality=True,
                yearly_seasonality=False,
                changepoint_prior_scale=0.05,
            )
            m.fit(train)
            mode = "honest_refit_prefix"
        else:
            m = joblib.load(pkl)
            mode = "artifact_predict_tail_optimistic"

        fc = m.predict(hold[["ds"]])
        y_true = hold["y"].values
        y_hat = fc["yhat"].values
        mae = float(mean_absolute_error(y_true, y_hat))
        denom = np.maximum(np.abs(y_true) + np.abs(y_hat), 1e-9)
        smape = float(np.mean(2.0 * np.abs(y_true - y_hat) / denom))
        results.append(
            {
                "model": f"prophet_{metric}",
                "role": "Macro baseline / seasonality envelope",
                "n_train": int(len(train)),
                "n_holdout": int(len(hold)),
                "score_mode": mode,
                "primary_metric": "mae",
                "mae": mae,
                "smape": smape,
                "artifact": str(pkl.relative_to(MODELS_DIR.parent)),
            }
        )
    return results


def score_topology() -> dict:
    path = MODELS_DIR / "topology" / "topology_graph.json"
    if not path.exists():
        return {"model": "topology", "error": "missing topology_graph.json"}
    g = json.loads(path.read_text())
    return {
        "model": "topology",
        "role": "Alert eccentricity / root-node merge (structure only)",
        "scored_on_lake": False,
        "nodes": g.get("nodes"),
        "eccentricity": g.get("eccentricity"),
        "primary_metric": "eccentricity",
        "note": "Not a telemetry accuracy model — printed for completeness",
    }


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# DECA model playground — mixed test scoreboard",
        "",
        f"- **When:** `{report['playground_date']}`",
        f"- **Exam seed:** `{report['exam_seed']}` (stratified mixed paper)",
        f"- **Holdout:** frac={report['holdout_frac']}  policy={report['holdout_policy']}",
        f"- **Exam rows:** {report['n_exam_rows']:,} / lake {report['n_lake_rows']:,}",
        "",
        "## Individual scores",
        "",
        "| Model | Role | Primary | Score | Extra |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in report["scoreboard"]:
        model = row.get("model", "?")
        role = row.get("role", "")
        primary = row.get("primary_metric", "—")
        if row.get("error"):
            score, extra = "ERR", row["error"]
        elif primary == "roc_auc":
            score = f"{row.get('roc_auc', float('nan')):.3f}"
            extra = f"AP={row.get('average_precision')}"
        elif primary == "macro_f1":
            score = f"{row.get('macro_f1', float('nan')):.3f}"
            extra = f"Acc={row.get('accuracy', 0):.3f} · rareR={row.get('mean_rare_recall')}"
        elif primary == "mae_minutes":
            score = f"{row.get('mae_minutes', float('nan')):.3f} min"
            extra = f"n={row.get('n_sequences')}"
        elif primary == "mae":
            score = f"{row.get('mae', float('nan')):.4g}"
            extra = f"sMAPE={row.get('smape', float('nan')):.3f} · {row.get('score_mode')}"
        elif primary == "eccentricity":
            score = str(row.get("eccentricity"))
            extra = row.get("note", "")
        else:
            score, extra = "—", json.dumps({k: row[k] for k in row if k not in ('model', 'role')})[:80]
        lines.append(f"| `{model}` | {role} | {primary} | {score} | {extra} |")

    xgb = next((r for r in report["models"] if r.get("model") == "fault_classifier_xgb"), None)
    if xgb and xgb.get("per_class"):
        lines += [
            "",
            "## Fault classifier — per class (mixed paper)",
            "",
            "| Class | P | R | F1 | Support |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for c, m in xgb["per_class"].items():
            lines.append(
                f"| {c} | {m['precision']:.2f} | {m['recall']:.2f} | {m['f1']:.2f} | {m['support']} |"
            )
        loom = xgb.get("loom") or {}
        boost = loom.get("temporal_boost") or {}
        lines += [
            "",
            "### Temporal Loom (live stream — not applied on this shuffled paper)",
            "",
            f"- Knobs: `enter_k={loom.get('enter_k')}` · `exit_k={loom.get('exit_k')}` · "
            f"enabled={loom.get('enabled')}",
        ]
        if boost.get("persistent_macro_f1") is not None:
            lines.append(
                f"- Chronological boost: raw Macro‑F1 `{boost.get('raw_macro_f1'):.3f}` → "
                f"sticky `{boost.get('persistent_macro_f1'):.3f}` "
                f"(Δ `{boost.get('delta_macro_f1'):+.3f}`) — see `docs/DECA_TEMPORAL_LOOM.md`"
            )
        else:
            lines.append(
                "- Run `python scripts/deca_score_temporal.py` to measure and bake loom boost metrics."
            )

    lines += [
        "",
        "## Exam label mix",
        "",
        "```",
        json.dumps(report["exam_label_counts"], indent=2),
        "```",
        "",
        "> Isolation Forest + XGB + LSTM share the **same stratified mixed rows**. "
        "Prophet uses a chronological tail of each raw series (optionally `--prophet-refit`). "
        "Topology is structure-only.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="DECA model playground — mixed test scoreboard")
    parser.add_argument("--holdout-frac", type=float, default=0.20)
    parser.add_argument(
        "--holdout-policy",
        choices=("random", "time_tail"),
        default="random",
        help="random = mixed general paper (default)",
    )
    parser.add_argument("--exam-seed", type=int, default=None)
    parser.add_argument(
        "--prophet-refit",
        action="store_true",
        help="Honest Prophet: refit on series prefix before scoring holdout tail",
    )
    parser.add_argument("--skip-lstm", action="store_true")
    parser.add_argument("--skip-prophet", action="store_true")
    args = parser.parse_args()

    seed = args.exam_seed if args.exam_seed is not None else int(datetime.now(timezone.utc).timestamp())
    rng = np.random.default_rng(seed)

    print(f"\n{'=' * 60}\n▶ DECA model playground — mixed test\n{'=' * 60}")
    print(f"exam_seed={seed}  policy={args.holdout_policy}  holdout_frac={args.holdout_frac}")

    df, feats = load_feature_lake()
    y_raw = df["unified_label"].astype(str)
    y, le_classes, class_to_idx = encode_labels(y_raw)
    blind = stratified_blind_holdout(
        y, df, args.holdout_frac, rng=rng, policy=args.holdout_policy
    )
    X_ex = df.iloc[blind][feats]
    y_ex = y[blind]
    y_anom = df.iloc[blind]["is_anomaly"].astype(int).values
    exam_counts = {le_classes[i]: int(np.sum(y_ex == i)) for i in range(len(le_classes))}
    print("Exam label mix:", exam_counts)
    print(f"Lake={len(df):,}  exam_rows={int(blind.sum()):,}  features={len(feats)}")

    results: list[dict] = []

    print("\n=== Isolation Forest ===")
    if_score = score_isolation_forest(X_ex, y_anom)
    results.append(if_score)
    print(f"  ROC-AUC={if_score.get('roc_auc')}  AP={if_score.get('average_precision')}")

    print("\n=== Fault classifier (XGB) ===")
    xgb_score = score_fault_classifier(X_ex, y_ex, le_classes, class_to_idx)
    results.append(xgb_score)
    print(
        f"  Macro-F1={xgb_score['macro_f1']:.4f}  Acc={xgb_score['accuracy']:.4f}  "
        f"rare-recall={xgb_score['mean_rare_recall']}"
    )

    if not args.skip_lstm:
        print("\n=== LSTM time-to-breach ===")
        lstm_score = score_lstm(df, feats, df.index[blind])
        results.append(lstm_score)
        if lstm_score.get("n_sequences"):
            print(f"  MAE={lstm_score['mae_minutes']:.3f} min  n={lstm_score['n_sequences']}")
        else:
            print(f"  {lstm_score.get('note') or lstm_score.get('error')}")
    else:
        results.append({"model": "lstm_ttb", "skipped": True})

    if not args.skip_prophet:
        print("\n=== Prophet ×3 ===")
        for p in score_prophet(args.holdout_frac, honest_refit=args.prophet_refit):
            results.append(p)
            if p.get("mae") is not None:
                print(f"  {p['model']}: MAE={p['mae']:.4g}  sMAPE={p['smape']:.3f}  ({p['score_mode']})")
            else:
                print(f"  {p['model']}: {p.get('error')}")
    else:
        results.append({"model": "prophet", "skipped": True})

    print("\n=== Topology ===")
    topo = score_topology()
    results.append(topo)
    print(f"  eccentricity={topo.get('eccentricity')}")

    scoreboard = []
    for r in results:
        if r.get("skipped") or r.get("error"):
            scoreboard.append(r)
            continue
        scoreboard.append(
            {
                "model": r.get("model"),
                "role": r.get("role"),
                "primary_metric": r.get("primary_metric"),
                "roc_auc": r.get("roc_auc"),
                "average_precision": r.get("average_precision"),
                "macro_f1": r.get("macro_f1"),
                "accuracy": r.get("accuracy"),
                "mean_rare_recall": r.get("mean_rare_recall"),
                "mae_minutes": r.get("mae_minutes"),
                "n_sequences": r.get("n_sequences"),
                "mae": r.get("mae"),
                "smape": r.get("smape"),
                "score_mode": r.get("score_mode"),
                "eccentricity": r.get("eccentricity"),
                "note": r.get("note"),
                "error": r.get("error"),
            }
        )

    report = {
        "playground_date": datetime.now(timezone.utc).isoformat(),
        "exam_seed": seed,
        "holdout_frac": args.holdout_frac,
        "holdout_policy": args.holdout_policy,
        "n_lake_rows": int(len(df)),
        "n_exam_rows": int(blind.sum()),
        "n_features": len(feats),
        "exam_label_counts": exam_counts,
        "prophet_refit": args.prophet_refit,
        "models": results,
        "scoreboard": scoreboard,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "latest_playground.json"
    md_path = OUT_DIR / "scoreboard.md"
    csv_path = OUT_DIR / "scoreboard.csv"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    write_markdown(report, md_path)
    pd.DataFrame(scoreboard).to_csv(csv_path, index=False)

    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {csv_path}")
    print(f"\n{'=' * 60}\nPLAYGROUND DONE — see models/playground/scoreboard.md\n{'=' * 60}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
