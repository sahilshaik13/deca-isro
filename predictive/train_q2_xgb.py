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
    ap.add_argument("--reg-lambda", type=float, default=2.0)
    ap.add_argument("--min-child-weight", type=float, default=2.0)
    ap.add_argument("--subsample", type=float, default=0.9)
    ap.add_argument("--colsample-bytree", type=float, default=0.9)
    ap.add_argument("--learning-rate", type=float, default=0.08)
    ap.add_argument(
        "--weight-power",
        type=float,
        default=1.0,
        help="sample_weight = (max_count/count)^power; >1 boosts rare classes without dropping rows",
    )
    ap.add_argument(
        "--holdout-must-contain",
        action="append",
        default=[],
        help="substring that must appear in ≥1 holdout group (repeatable), e.g. L4_",
    )
    ap.add_argument(
        "--idle-baseline-json",
        default="",
        help="optional idle_baseline.json to embed in model bundle (eval/live parity)",
    )
    ap.add_argument(
        "--util-ceiling-json",
        default="",
        help="optional util_ceiling.json to embed (pct-of-ceil feature parity)",
    )
    ap.add_argument(
        "--max-split-tries",
        type=int,
        default=40,
        help="when --holdout-must-contain set, try seeds until constraints met",
    )
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
        id_to_severity = None
        severity_to_root = None
        if "label" not in df.columns and "root_label" in df.columns:
            df["label"] = df["root_label"]
        if "label" not in df.columns:
            raise SystemExit("missing label column")
        y_raw = df["label"].astype(int).to_numpy()
        # XGBoost requires contiguous 0..K-1 (balanced sets may omit idle / include L6)
        present_raw = sorted(set(y_raw.tolist()))
        raw_to_contig = {r: i for i, r in enumerate(present_raw)}
        contig_to_raw = {i: r for r, i in raw_to_contig.items()}
        y = np.asarray([raw_to_contig[int(v)] for v in y_raw], dtype=int)
        label_names = {
            i: LABEL_NAMES.get(contig_to_raw[i], f"class_{contig_to_raw[i]}")
            for i in range(len(present_raw))
        }
        class_ids = list(range(len(present_raw)))
        target_names = [label_names[i] for i in class_ids]
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
    must: list[str] = [s for s in (args.holdout_must_contain or []) if s]
    split_seed = args.seed
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
        must = [s for s in (args.holdout_must_contain or []) if s]
        train_idx = test_idx = None
        split_seed = args.seed
        holdout_groups = []
        for attempt in range(max(1, args.max_split_tries if must else 1)):
            split_seed = args.seed + attempt
            gss = GroupShuffleSplit(
                n_splits=1, test_size=args.test_size, random_state=split_seed
            )
            tr, te = next(gss.split(X, y, groups))
            held = sorted(set(groups[te].tolist()))
            if must and not all(any(m in g for g in held) for m in must):
                continue
            # XGB multi:softprob needs every class id present in y_train
            if set(np.unique(y[tr]).tolist()) != set(np.unique(y).tolist()):
                continue
            train_idx, test_idx = tr, te
            holdout_groups = held
            break
        if train_idx is None or test_idx is None:
            raise SystemExit(
                f"could not satisfy holdout-must-contain={must} "
                f"(and all-classes-in-train) in {args.max_split_tries} tries"
            )
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        split_mode = "group_holdout"
    else:
        strat = y if len(np.unique(y)) > 1 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=args.test_size, random_state=args.seed, stratify=strat
        )

    counts = {int(k): int(v) for k, v in zip(*np.unique(y_train, return_counts=True))}
    max_c = max(counts.values()) if counts else 1
    power = float(args.weight_power)
    sw = np.asarray(
        [(max_c / counts[int(yi)]) ** power for yi in y_train], dtype=np.float32
    )

    n_classes = int(len(np.unique(y)))
    backend = "xgboost"
    try:
        from xgboost import XGBClassifier

        model = XGBClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            learning_rate=args.learning_rate,
            subsample=args.subsample,
            colsample_bytree=args.colsample_bytree,
            reg_lambda=args.reg_lambda,
            min_child_weight=args.min_child_weight,
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
    idle_bl = None
    if args.idle_baseline_json:
        idle_bl = json.loads(Path(args.idle_baseline_json).read_text())
    util_ceil_bl = None
    if args.util_ceiling_json:
        util_ceil_bl = json.loads(Path(args.util_ceiling_json).read_text())
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
        "idle_baseline": idle_bl,
        "util_ceiling": util_ceil_bl,
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
        "reg_lambda": args.reg_lambda,
        "min_child_weight": args.min_child_weight,
        "subsample": args.subsample,
        "colsample_bytree": args.colsample_bytree,
        "learning_rate": args.learning_rate,
        "weight_power": args.weight_power,
        "holdout_must_contain": must if args.group_split else [],
        "split_seed_used": int(split_seed) if args.group_split else args.seed,
        "data_sources": [str(Path(p).resolve()) for p in args.data],
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
