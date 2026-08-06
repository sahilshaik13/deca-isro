"""Util congestion specialist — patches frozen Q2 when it under-calls 5A/5B.

Mirrors bgp_specialist: small XGB on util/ceil features only. At infer, when
primary says healthy/0 (or util) but specialist is confident of congestion,
promote/refine to 5A/5B. Does not retrain the primary.
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
from sklearn.preprocessing import LabelEncoder

UTIL_FEAT_CANDIDATES = [
    "util_gre_mbps_mean",
    "util_gre_mbps_max",
    "util_gre_mbps_last",
    "util_gre_mbps_slope",
    "htb_payload_ceil_mbps_mean",
    "htb_payload_ceil_mbps_max",
    "htb_payload_ceil_mbps_last",
    "htb_payload_ceil_mbps_slope",
    "loss_gre_pct_mean",
    "loss_gre_pct_max",
    "jitter_gre_ms_mean",
]


def _feat_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in UTIL_FEAT_CANDIDATES if c in df.columns]


def _ratio(feats: dict[str, float]) -> float:
    util = float(feats.get("util_gre_mbps_mean") or feats.get("util_gre_mbps_last") or 0.0)
    ceil = float(
        feats.get("htb_payload_ceil_mbps_mean")
        or feats.get("htb_payload_ceil_mbps_last")
        or 0.0
    )
    if ceil <= 1e-6:
        return 0.0
    return util / ceil


def refine_util(
    severity: str,
    feats: dict[str, float],
    *,
    bundle: dict | None = None,
    min_util_proba: float = 0.70,
) -> str:
    """Promote 0→5A/5B when util specialist is confident.

    Does **not** rewrite an existing 5A/5B from the primary (that path
    destroyed util_phase_exact when the specialist was synth-skewed).
    Never demotes rain/cpu/bgp/loss.
    """
    if severity != "0":
        return severity

    if bundle is not None:
        cols = bundle["feature_cols"]
        model = bundle["model"]
        le: LabelEncoder = bundle["label_encoder"]
        x = np.asarray([[float(feats.get(c, 0.0) or 0.0) for c in cols]], dtype=np.float32)
        thr = float(bundle.get("min_util_proba", min_util_proba))
        classes = list(le.classes_)
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(x)[0]
            pmap = {str(classes[i]): float(proba[i]) for i in range(len(classes))}
            p5a = pmap.get("5A", 0.0)
            p5b = pmap.get("5B", 0.0)
            p_util = p5a + p5b
            if p_util < thr:
                return "0"
            return "5B" if p5b >= p5a else "5A"
        pred_i = int(model.predict(x)[0])
        pred = str(le.inverse_transform([pred_i])[0])
        return pred if pred in ("5A", "5B") else "0"

    util = float(feats.get("util_gre_mbps_mean") or 0.0)
    ceil = float(feats.get("htb_payload_ceil_mbps_mean") or 0.0)
    r = _ratio(feats)
    if ceil >= 20 and r >= 0.85 and util >= 15:
        return "5B"
    if ceil >= 12 and r >= 0.55 and util >= 8:
        return "5A"
    return severity


def train(
    data_csv: Path,
    out_dir: Path,
    seed: int = 42,
    min_util_proba: float = 0.70,
) -> dict:
    df = pd.read_csv(data_csv)
    use = df[df["severity"].astype(str).isin(["0", "5A", "5B"])].copy()
    cols = _feat_cols(use)
    if not cols:
        raise SystemExit("no util feature columns in windows CSV")
    X = use[cols].astype(float).fillna(0.0).to_numpy()
    y_str = use["severity"].astype(str).to_numpy()
    le = LabelEncoder()
    y = le.fit_transform(y_str)
    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y
    )
    try:
        from xgboost import XGBClassifier

        model = XGBClassifier(
            max_depth=3,
            n_estimators=100,
            learning_rate=0.08,
            reg_lambda=2.0,
            min_child_weight=2,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="multi:softprob",
            num_class=len(le.classes_),
            eval_metric="mlogloss",
            n_jobs=2,
        )
        backend = "xgboost"
    except ImportError:
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(max_depth=3, n_estimators=100)
        backend = "sklearn_gb"

    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    yte_s = le.inverse_transform(yte)
    pred_s = le.inverse_transform(pred)
    acc = float(accuracy_score(yte_s, pred_s))
    report = classification_report(
        yte_s, pred_s, labels=["0", "5A", "5B"], output_dict=True, zero_division=0
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "label_encoder": le,
        "feature_cols": cols,
        "min_util_proba": float(min_util_proba),
        "backend": backend,
        "holdout_acc": acc,
        "report": report,
        "n_train": int(len(ytr)),
        "n_test": int(len(yte)),
    }
    joblib.dump(bundle, out_dir / "util_5a5b.joblib")
    (out_dir / "train_metrics.json").write_text(
        json.dumps(
            {k: v for k, v in bundle.items() if k not in ("model", "label_encoder")},
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(json.dumps({"out": str(out_dir), "holdout_acc": acc, "backend": backend}, indent=2))
    return bundle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-csv", required=True)
    ap.add_argument(
        "--out-dir",
        default="data/deca/predictive/protocol_models/util_5a5b_specialist",
    )
    ap.add_argument("--min-util-proba", type=float, default=0.70)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    train(
        Path(args.data_csv),
        Path(args.out_dir),
        seed=args.seed,
        min_util_proba=args.min_util_proba,
    )


if __name__ == "__main__":
    main()
