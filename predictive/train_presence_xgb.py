"""Train multi-label family presence (6 binary XGBs) beside Q2.

Writes under protocol_models/_candidates/ and train_logs/presence_skel only.
Does NOT touch promoted models or cite board.

Usage:
  python -m predictive.train_presence_xgb \\
    --protocol-dir data/deca/predictive/protocol/full_variants_pi_20260803T175816Z \\
    --seed 42
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupShuffleSplit
from xgboost import XGBClassifier

from .presence_label import PRESENCE_COLS, PRESENCE_FAMILIES, attach_presence_labels
from .train_q2_xgb import SKIP_COLS

PRESENCE_SKIP = set(SKIP_COLS) | set(PRESENCE_COLS) | {"is_compound"}


def _feature_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cols = [
        c
        for c in df.columns
        if c not in PRESENCE_SKIP and pd.api.types.is_numeric_dtype(df[c])
    ]
    X = df[cols].astype(float).fillna(0.0).to_numpy()
    return X, cols


def _group_split(
    df: pd.DataFrame,
    *,
    seed: int,
    test_size: float,
    must_contain: str = "COMPOUND",
    max_tries: int = 80,
) -> tuple[np.ndarray, np.ndarray]:
    groups = df["source_capture"].astype(str).to_numpy()
    y_dummy = np.zeros(len(df))
    for offset in range(max_tries):
        gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed + offset)
        train_idx, test_idx = next(gss.split(df, y_dummy, groups))
        hold_groups = set(groups[test_idx])
        if any(must_contain in g for g in hold_groups):
            return train_idx, test_idx
    raise RuntimeError(f"could not put {must_contain} in holdout after {max_tries} tries")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--protocol-dir",
        default="data/deca/predictive/protocol/full_variants_pi_20260803T175816Z",
    )
    ap.add_argument("--data", default="", help="override q2_windows.csv path")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    proto = Path(args.protocol_dir)
    if not proto.is_absolute():
        proto = root / proto
    data_path = Path(args.data) if args.data else proto / "dataset" / "q2_windows.csv"
    if not data_path.is_absolute():
        data_path = root / data_path

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out_dir) if args.out_dir else (
        root / "data/deca/predictive/protocol_models/_candidates" / f"presence_skel_{stamp}"
    )
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)
    logs = proto / "train_logs" / "presence_skel"
    logs.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(data_path)
    df = attach_presence_labels(raw, proto)
    side = logs / "q2_windows_presence.csv"
    df.to_csv(side, index=False)

    train_idx, test_idx = _group_split(df, seed=args.seed, test_size=args.test_size)
    train_df, test_df = df.iloc[train_idx].copy(), df.iloc[test_idx].copy()

    X_tr, feat_cols = _feature_matrix(train_df)
    X_te, _ = _feature_matrix(test_df)
    # align columns if needed
    X_te = test_df.reindex(columns=feat_cols, fill_value=0.0).astype(float).fillna(0.0).to_numpy()

    models: dict[str, Any] = {}
    per_family: dict[str, dict] = {}
    y_true_all = []
    y_pred_all = []

    for k, col in zip(PRESENCE_FAMILIES, PRESENCE_COLS):
        y_tr = train_df[col].astype(int).to_numpy()
        y_te = test_df[col].astype(int).to_numpy()
        # skip empty positive family in train (e.g. L6 absent)
        if y_tr.sum() == 0:
            per_family[col] = {"skipped": True, "reason": "no_positives_in_train"}
            models[col] = None
            continue
        clf = XGBClassifier(
            n_estimators=120,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=4,
            random_state=args.seed,
            tree_method="hist",
        )
        clf.fit(X_tr, y_tr)
        pred = (clf.predict_proba(X_te)[:, 1] >= 0.5).astype(int)
        models[col] = clf
        f1 = float(f1_score(y_te, pred, zero_division=0))
        per_family[col] = {
            "f1": f1,
            "support_pos": int(y_te.sum()),
            "pred_pos": int(pred.sum()),
            "train_pos": int(y_tr.sum()),
        }
        y_true_all.append(y_te)
        y_pred_all.append(pred)

    if y_true_all:
        Yt = np.column_stack(y_true_all)
        Yp = np.column_stack(y_pred_all)
        macro = float(f1_score(Yt, Yp, average="macro", zero_division=0))
        micro = float(f1_score(Yt, Yp, average="micro", zero_division=0))
    else:
        macro = micro = 0.0

    # Compound-only subset
    comp_mask = test_df["is_compound"].astype(int).eq(1).to_numpy()
    comp_metrics: dict[str, float] = {}
    if comp_mask.any() and y_true_all:
        Yt_c = np.column_stack([yt[comp_mask] for yt in y_true_all])
        Yp_c = np.column_stack([yp[comp_mask] for yp in y_pred_all])
        comp_metrics = {
            "macro_f1": float(f1_score(Yt_c, Yp_c, average="macro", zero_division=0)),
            "micro_f1": float(f1_score(Yt_c, Yp_c, average="micro", zero_division=0)),
            "n_windows": int(comp_mask.sum()),
        }

    bundle = {
        "models": models,
        "feature_cols": feat_cols,
        "presence_cols": list(PRESENCE_COLS),
        "families": list(PRESENCE_FAMILIES),
        "threshold": 0.5,
        "seed": args.seed,
        "protocol_dir": str(proto),
        "data": str(data_path),
        "split_mode": "group_source_capture_holdout_must_COMPOUND",
        "holdout_captures": sorted(set(test_df["source_capture"].astype(str))),
        "train_captures": sorted(set(train_df["source_capture"].astype(str))),
    }
    joblib.dump(bundle, out / "presence_bundle.joblib")

    receipt = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out),
        "sidecar_csv": str(side),
        "n_train": int(len(train_df)),
        "n_holdout": int(len(test_df)),
        "holdout_macro_f1": macro,
        "holdout_micro_f1": micro,
        "compound_holdout": comp_metrics,
        "per_family": per_family,
        "note": "skeleton GT=recipe multi-hot on COMPOUND; pinpoint=root one-hot; not wired to Decide",
        "cite_board": "untouched",
    }
    (out / "TRAIN_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    (logs / "TRAIN_RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
