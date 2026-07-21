#!/usr/bin/env python3
"""Tier A onboarding: threshold-only recalibration — no retraining.

This is the "config-only, recalibrate in hours, not weeks" onboarding path
described in docs/ISRO_PORTABILITY.md and docs/CALIBRATION_CAMPAIGN_SPEC.md
(Tier A). It reuses the ALREADY-FITTED active gate + multiclass head
(``models/fault_classifier/fault_classifier_xgb.pkl``) exactly as-is — no
tree is refit — and only re-runs the existing threshold grid search
(``tune_thresholds()`` from ``deca_school_exam_train.py``) against a labeled
sample, then writes the recalibrated ``gate_thr`` / ``class_thr`` back out.

Two usage modes:
  1. Demo mode (no --sample-parquet): draws a fresh holdout sample from our
     own current lake, to demonstrate the mechanism end-to-end without a real
     foreign network's data.
  2. Real onboarding mode (--sample-parquet path/to/sample.parquet): the
     labeled sample must already be in the unified schema (``unified_label``
     column + the same engineered feature columns rebuild_unified.py
     produces) — i.e. run the target network's telemetry through
     rebuild_unified.py first, then point this script at the resulting
     parquet.

Default is a dry run (prints the before/after threshold diff and exam
score); pass --apply to actually write the new thresholds into
models/fault_classifier/ (backs up the previous files first).
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import (
    RARE,
    _align_to_estimator_features,
    evaluate,
    feature_columns,
    load_active_classifier,
    stratified_blind_holdout,
    tune_thresholds,
)
from rebuild_unified import UNIFIED_LABELS


def load_labeled_sample(sample_parquet: str | None, holdout_frac: float, seed: int):
    if sample_parquet:
        df = pd.read_parquet(sample_parquet)
        print(f"Loaded external labeled sample: {sample_parquet} ({len(df)} rows)")
    else:
        df = pd.read_parquet(PROCESSED_DIR / "deca_unified_dataset.parquet")
        print(
            f"No --sample-parquet given — demoing against a fresh holdout draw from "
            f"our own current lake ({len(df)} rows). Pass --sample-parquet with a "
            f"real target-network sample for actual onboarding."
        )

    df = df.dropna(subset=["unified_label"]).reset_index(drop=True)
    le_classes = [c for c in UNIFIED_LABELS if c in set(df["unified_label"])]
    le_classes += sorted(set(df["unified_label"]) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = df["unified_label"].map(class_to_idx).to_numpy()
    feats = feature_columns(df)
    X = df[feats]

    rng = np.random.default_rng(seed)
    idx = stratified_blind_holdout(y, df, holdout_frac, rng=rng, policy="random")
    return X[idx].reset_index(drop=True), y[idx], le_classes, class_to_idx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--sample-parquet",
        type=str,
        default=None,
        help="Labeled sample from the target network (unified schema). Omit to demo "
        "against a fresh holdout draw from the current lake.",
    )
    parser.add_argument("--holdout-frac", type=float, default=0.30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the recalibrated thresholds into models/fault_classifier/ "
        "(backs up the previous files first). Default is dry-run only.",
    )
    args = parser.parse_args()

    bundle = load_active_classifier()
    if bundle is None:
        raise SystemExit(
            "No active classifier at models/fault_classifier/fault_classifier_xgb.pkl "
            "— nothing to recalibrate."
        )
    gate = bundle["gate"]
    full_clf = bundle["full_clf"]
    healthy_idx = int(bundle["healthy_idx"])

    X, y, le_classes, class_to_idx = load_labeled_sample(args.sample_parquet, args.holdout_frac, args.seed)
    rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}
    print(f"Recalibration sample: {len(X)} rows, classes={le_classes}")

    X_aligned = _align_to_estimator_features(full_clf, X)

    clf_dir = MODELS_DIR / "fault_classifier"
    old_thr_path = clf_dir / "decision_thresholds.json"
    old = json.loads(old_thr_path.read_text()) if old_thr_path.exists() else {}
    old_gate_thr = old.get("gate_thr", bundle.get("gate_thr"))
    old_class_thr = old.get("class_thr", {})
    print(f"\nBEFORE — gate_thr={old_gate_thr}  class_thr={old_class_thr}")

    idx_to_class = {i: c for c, i in class_to_idx.items()}
    old_score = evaluate(
        gate,
        full_clf,
        X_aligned,
        y,
        healthy_idx=healthy_idx,
        gate_thr=float(old_gate_thr) if old_gate_thr is not None else 0.5,
        class_thr={int(class_to_idx[c]): float(v) for c, v in old_class_thr.items() if c in class_to_idx},
        le_classes=le_classes,
        rare_idx_list=sorted(rare_ids),
    )
    print(
        f"  scored on THIS sample with OLD thresholds: "
        f"macro_f1={old_score['macro_f1']:.4f}  rare_recall={old_score['mean_rare_recall']:.4f}"
    )

    best = tune_thresholds(gate, full_clf, X_aligned, y, healthy_idx=healthy_idx, rare_ids=rare_ids)
    new_class_thr_named = {idx_to_class[k]: v for k, v in best["class_thr"].items() if k in idx_to_class}
    print(f"\nAFTER  — gate_thr={best['gate_thr']}  class_thr={new_class_thr_named}")
    print(f"  scored on THIS sample with NEW thresholds: macro_f1={best['macro_f1']:.4f}")

    delta = best["macro_f1"] - old_score["macro_f1"]
    print(f"\nΔ macro-F1 from recalibration alone (no retrain): {delta:+.4f}")

    if not args.apply:
        print("\nDry run only — pass --apply to write these thresholds into models/fault_classifier/")
        return

    bak = MODELS_DIR / f"fault_classifier.bak_recalibrate_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    shutil.copytree(clf_dir, bak)
    print(f"\nBacked up previous thresholds → {bak.name}")

    bundle["gate_thr"] = best["gate_thr"]
    bundle["class_thr"] = best["class_thr"]
    joblib.dump(bundle, clf_dir / "fault_classifier_xgb.pkl")

    le_path = clf_dir / "label_encoder.pkl"
    if le_path.exists():
        le_bundle = joblib.load(le_path)
        le_bundle["gate_thr"] = best["gate_thr"]
        le_bundle["class_thr"] = new_class_thr_named
        joblib.dump(le_bundle, le_path)

    old.update(
        {
            "gate_thr": best["gate_thr"],
            "class_thr": new_class_thr_named,
            "recalibrated_at": datetime.now(timezone.utc).isoformat(),
            "recalibration_sample_rows": int(len(X)),
            "recalibration_macro_f1_on_sample": best["macro_f1"],
        }
    )
    old_thr_path.write_text(json.dumps(old, indent=2))
    print(f"Wrote recalibrated thresholds → {old_thr_path}")
    print("Gate + classifier trees were NOT retrained — only gate_thr/class_thr changed.")


if __name__ == "__main__":
    main()
