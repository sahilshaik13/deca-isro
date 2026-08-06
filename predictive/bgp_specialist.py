"""BGP mild vs severe (3A/3B) specialist — refines primary Q2 without retraining it.

Live `d2` was trained without 3A in its class set (contig map skips severity_id 6),
so it always emits 3B for flap texture. This module:
  1. Trains a small XGB on BGP rate features only (3A vs 3B)
  2. At infer: when primary severity is 3B (or 3A), optionally re-label via specialist
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split

from .severity_label import SEVERITY_TO_ID

BGP_FEAT_CANDIDATES = [
    "bgp_flap_count_delta",
    "bgp_flap_count_slope",
    "bgp_flap_count_rate_mean",
    "bgp_flap_count_rate_std",
    "bgp_flap_count_rate_max",
]

# Label bands (severity_label): mild ≥0.2, severe ≥1.0 flaps/s rolling.
# Specialist threshold fallback when model unavailable.
RATE_3B_MIN = 0.65


def _feat_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in BGP_FEAT_CANDIDATES if c in df.columns]


def refine_3a_3b(
    severity: str,
    feats: dict[str, float],
    *,
    bundle: dict | None = None,
    use_threshold_fallback: bool = True,
    min_3a_proba: float = 0.75,
) -> str:
    """Refine 3B→3A only when specialist is confident (protects 3B recall).

    Primary `d2` almost never emits 3A. We only *downgrade* 3B→3A when
    P(3A) ≥ min_3a_proba (or rate clearly mild). Never force 3B→3A on weak evidence.
    """
    if severity not in ("3A", "3B"):
        return severity
    if severity == "3A":
        return "3A"  # keep rare primary 3A
    # severity == 3B → maybe downgrade
    if bundle is not None:
        cols = bundle["feature_cols"]
        model = bundle["model"]
        x = np.asarray([[float(feats.get(c, 0.0) or 0.0) for c in cols]], dtype=np.float32)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(x)[0]
            # classes 0=3A, 1=3B
            p_3a = float(proba[0]) if len(proba) > 1 else 0.0
            if p_3a >= float(bundle.get("min_3a_proba", min_3a_proba)):
                return "3A"
            return "3B"
        pred = int(model.predict(x)[0])
        return "3B" if pred == 1 else "3A"
    if use_threshold_fallback:
        rate = float(feats.get("bgp_flap_count_rate_mean") or 0.0)
        rmax = float(feats.get("bgp_flap_count_rate_max") or 0.0)
        # conservative mild: both mean and max look mild
        if rate >= 0 and rate < 0.5 and rmax <= 5.0:
            return "3A"
        return "3B"
    return severity


def train(data_csv: Path, out_dir: Path, seed: int = 42) -> dict:
    df = pd.read_csv(data_csv)
    ab = df[df["severity"].astype(str).isin(["3A", "3B"])].copy()
    cols = _feat_cols(ab)
    if not cols:
        raise SystemExit("no BGP feature columns in windows CSV")
    X = ab[cols].astype(float).fillna(0.0).to_numpy()
    y = (ab["severity"].astype(str) == "3B").astype(int).to_numpy()
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y
    )
    try:
        from xgboost import XGBClassifier

        model = XGBClassifier(
            max_depth=3,
            n_estimators=80,
            learning_rate=0.08,
            reg_lambda=2.0,
            min_child_weight=2,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="binary:logistic",
            eval_metric="logloss",
            n_jobs=2,
        )
        backend = "xgboost"
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(max_depth=3, n_estimators=80)
        backend = "sklearn_gb"

    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    acc = float(accuracy_score(yte, pred))
    report = classification_report(
        yte, pred, target_names=["3A", "3B"], output_dict=True, zero_division=0
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_cols": cols,
        "classes": ["3A", "3B"],
        "backend": backend,
        "rate_3b_min_fallback": RATE_3B_MIN,
    }
    joblib.dump(bundle, out_dir / "bgp_3a3b.joblib")
    metrics = {
        "backend": backend,
        "n_total": int(len(ab)),
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "accuracy": acc,
        "report": report,
        "feature_cols": cols,
        "label_counts": {
            "3A": int((y == 0).sum()),
            "3B": int((y == 1).sum()),
        },
    }
    (out_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--data",
        default="data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q2_windows.csv",
    )
    ap.add_argument(
        "--out-dir",
        default="data/deca/predictive/protocol_models/bgp_3a3b_specialist",
    )
    args = ap.parse_args()
    m = train(Path(args.data), Path(args.out_dir))
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
