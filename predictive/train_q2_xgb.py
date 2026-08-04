"""Train Q2 classifier on root labels or severity segments.

Usage:
  # root 0–3
  python -m predictive.train_q2_xgb --data .../q2_windows.csv --out-dir .../xgb_q2
  # severity 0,1A,1B,...
  python -m predictive.train_q2_xgb --data .../q2_windows.csv --out-dir .../xgb_q2_sev --severity
  # honest holdout: leave whole captures out (no window leakage)
  python -m predictive.train_q2_xgb ... --severity --group-col source_capture --group-split
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from .severity_label import (
    ID_TO_SEVERITY,
    SEVERITY_NAMES,
    SEVERITY_ORDER,
    SEVERITY_TO_ID,
    SEVERITY_TO_ROOT,
)

LABEL_NAMES = {
    0: "normal",
    1: "physical_degradation",
    2: "crypto_cpu_exhaustion",
    3: "route_flap",
}

SKIP_COLS = {
    "window_id",
    "start_idx",
    "end_idx",
    "start_ts",
    "end_ts",
    "label",
    "label_name",
    "source_capture",
    "severity",
    "severity_name",
    "severity_id",
    "root_label",
}


def feature_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cols = [c for c in df.columns if c not in SKIP_COLS and pd.api.types.is_numeric_dtype(df[c])]
    X = df[cols].astype(float).fillna(0.0).to_numpy()
    return X, cols


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--severity",
        action="store_true",
        help="train on severity_id / severity column instead of root label",
    )
    ap.add_argument(
        "--group-col",
        default="source_capture",
        help="column identifying capture/series for group holdout",
    )
    ap.add_argument(
        "--group-split",
        action="store_true",
        help="hold out whole groups (captures) instead of random windows",
    )
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--n-estimators", type=int, default=120)
    args = ap.parse_args()

    frames = [pd.read_csv(p) for p in args.data]
    df = pd.concat(frames, ignore_index=True)

    if args.severity:
        if "severity_id" in df.columns:
            y_raw = df["severity_id"].astype(int).to_numpy()
        elif "severity" in df.columns:
            y_raw = df["severity"].map(SEVERITY_TO_ID).astype(int).to_numpy()
        else:
            raise SystemExit("severity training requires severity or severity_id column")
        # XGBoost requires contiguous 0..K-1 class ids
        present_raw = sorted(set(y_raw.tolist()))
        raw_to_contig = {r: i for i, r in enumerate(present_raw)}
        contig_to_raw = {i: r for r, i in raw_to_contig.items()}
        y = np.asarray([raw_to_contig[int(v)] for v in y_raw], dtype=int)
        label_names = {
            i: SEVERITY_NAMES.get(ID_TO_SEVERITY[contig_to_raw[i]], ID_TO_SEVERITY[contig_to_raw[i]])
            for i in range(len(present_raw))
        }
        class_ids = list(range(len(present_raw)))
        target_names = [label_names[i] for i in class_ids]
        mode = "severity"
        id_to_severity = {i: ID_TO_SEVERITY[contig_to_raw[i]] for i in class_ids}
        severity_to_root = {
            id_to_severity[i]: SEVERITY_TO_ROOT[id_to_severity[i]] for i in class_ids
        }
    else:
        raw_to_contig = contig_to_raw = None
        id_to_severity = None
        severity_to_root = None
        if "label" not in df.columns and "root_label" in df.columns:
            df["label"] = df["root_label"]
        if "label" not in df.columns:
            raise SystemExit("missing label column")
        y = df["label"].astype(int).to_numpy()
        label_names = LABEL_NAMES
        class_ids = [0, 1, 2, 3]
        target_names = [LABEL_NAMES[i] for i in class_ids]
        mode = "root"

    X, feat_cols = feature_matrix(df)
    if len(df) < 16:
        raise SystemExit(f"need more windows, got {len(df)}")

    # Drop classes with <2 samples for stratify
    uniq, cnts = np.unique(y, return_counts=True)
    keep = {int(u) for u, c in zip(uniq, cnts) if c >= 2}
    if len(keep) < len(uniq):
        mask = np.isin(y, list(keep))
        X, y = X[mask], y[mask]
        df = df.iloc[mask].reset_index(drop=True)

    split_mode = "random_window"
    holdout_groups: list[str] = []
    if args.group_split:
        if args.group_col not in df.columns:
            raise SystemExit(
                f"--group-split needs column {args.group_col!r} "
                "(rebuild dataset so source_capture is L*/iter_*)"
            )
        groups = df[args.group_col].astype(str).to_numpy()
        n_groups = len(set(groups.tolist()))
        if n_groups < 2:
            raise SystemExit(f"need ≥2 groups in {args.group_col}, got {n_groups}")
        gss = GroupShuffleSplit(
            n_splits=1, test_size=args.test_size, random_state=args.seed
        )
        train_idx, test_idx = next(gss.split(X, y, groups))
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        holdout_groups = sorted(set(groups[test_idx].tolist()))
        split_mode = "group_holdout"
    else:
        strat = y if len(np.unique(y)) > 1 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=args.test_size, random_state=args.seed, stratify=strat
        )

    counts = {int(k): int(v) for k, v in zip(*np.unique(y_train, return_counts=True))}
    max_c = max(counts.values()) if counts else 1
    sw = np.asarray([max_c / counts[int(yi)] for yi in y_train], dtype=np.float32)

    n_classes = int(len(np.unique(y)))
    backend = "xgboost"
    try:
        from xgboost import XGBClassifier

        model = XGBClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=2.0,
            min_child_weight=2.0,
            objective="multi:softprob",
            num_class=n_classes,
            eval_metric="mlogloss",
            random_state=args.seed,
            n_jobs=2,
        )
    except ImportError:
        from sklearn.ensemble import RandomForestClassifier

        backend = "random_forest"
        model = RandomForestClassifier(
            n_estimators=200,
            max_depth=max(args.max_depth, 6),
            random_state=args.seed,
            class_weight="balanced_subsample",
            n_jobs=2,
        )

    if backend == "xgboost":
        model.fit(X_train, y_train, sample_weight=sw)
    else:
        model.fit(X_train, y_train)
    pred = model.predict(X_test)
    present = sorted(set(y_test.tolist()) | set(pred.tolist()))
    report = classification_report(
        y_test,
        pred,
        labels=present,
        target_names=[label_names.get(i, str(i)) for i in present],
        output_dict=True,
        zero_division=0,
    )
    cm = confusion_matrix(y_test, pred, labels=present).tolist()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / ("q2_severity.joblib" if args.severity else "q2_root_cause.joblib")
    bundle = {
        "model": model,
        "feature_cols": feat_cols,
        "label_names": label_names,
        "backend": backend,
        "mode": mode,
        "severity_to_root": severity_to_root if args.severity else None,
        "id_to_severity": id_to_severity if args.severity else None,
        "class_ids": present,
        "raw_to_contig": raw_to_contig,
        "contig_to_raw": contig_to_raw,
        "split_mode": split_mode,
    }
    joblib.dump(bundle, model_path)
    metrics = {
        "backend": backend,
        "mode": mode,
        "split_mode": split_mode,
        "group_col": args.group_col if args.group_split else None,
        "holdout_groups": holdout_groups,
        "n_holdout_groups": len(holdout_groups),
        "n_total": int(len(df)),
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "label_counts": {str(k): int(v) for k, v in zip(*np.unique(y, return_counts=True))},
        "accuracy": float(report.get("accuracy", 0.0)),
        "macro_f1": float(report.get("macro avg", {}).get("f1-score", 0.0)),
        "weighted_f1": float(report.get("weighted avg", {}).get("f1-score", 0.0)),
        "report": report,
        "confusion_matrix": cm,
        "confusion_labels": present,
        "model": str(model_path),
        "feature_cols": feat_cols,
        "max_depth": args.max_depth,
        "n_estimators": args.n_estimators,
        "smote_note": "prefer undersample-only datasets; SMOTE inflates random-window scores",
    }
    (out_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: metrics[k]
                for k in (
                    "backend",
                    "mode",
                    "split_mode",
                    "n_total",
                    "n_train",
                    "n_test",
                    "n_holdout_groups",
                    "accuracy",
                    "macro_f1",
                    "model",
                )
                if k in metrics
            },
            indent=2,
        )
    )
    print("confusion_matrix:", np.array(cm))


if __name__ == "__main__":
    main()
