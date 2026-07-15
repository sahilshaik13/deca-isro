#!/usr/bin/env python3
"""Train the Temporal Loom circumstance **existence** head.

Target: ``circumstance_label`` — which fault’s *situation exists* on this frame
(run-up **or** breach), else ``healthy``. Duration is never a feature; only
multi-scale pattern columns are used (same family as School Exam).

Safe before campaign data exists:
- Missing ``circumstance_label`` → filled as healthy and **deferred** (no fake model).
- Only-healthy lake → deferred artifact under ``models/circumstance/`` so the
  pipeline is wired; re-run after rebuild with a circumstance campaign.

After a circumstance campaign is folded in:

    python scripts/rebuild_unified.py --rpi-run … --rpi-run …
    python scripts/deca_train_circumstance.py

Live use: ``deca_inference.predict_circumstance`` + optional loom pre-arm when
existence agrees with a forming fault class.
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
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, f1_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import RARE, feature_columns, stratified_blind_holdout
from rebuild_unified import UNIFIED_LABELS, to_unified_label

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

RANDOM_STATE = 42
OUT_DIR = MODELS_DIR / "circumstance"
MIN_EXISTENCE_ROWS = 30  # need enough non-healthy existence labels to train


def ensure_circumstance_column(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Return (df, ready). Ready=False means no existence signal yet."""
    df = df.copy()
    if "circumstance_label" not in df.columns:
        df["circumstance_label"] = "healthy"
        return df, False
    y = df["circumstance_label"].map(to_unified_label).astype(str)
    df["circumstance_label"] = y
    n_pos = int((y != "healthy").sum())
    return df, n_pos >= MIN_EXISTENCE_ROWS


def write_deferred(*, reason: str, n_pos: int = 0) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "deferred",
        "ready": False,
        "reason": reason,
        "n_existence_rows": n_pos,
        "min_required": MIN_EXISTENCE_ROWS,
        "date": datetime.now(timezone.utc).isoformat(),
        "hint": (
            "Finish circumstance campaign → rebuild_unified with that run_id → "
            "re-run python scripts/deca_train_circumstance.py"
        ),
    }
    path = OUT_DIR / "deferred.json"
    path.write_text(json.dumps(payload, indent=2))
    # Clear stale trained pickle so inference knows to skip
    for name in ("circumstance_xgb.pkl", "metrics.json"):
        p = OUT_DIR / name
        if p.exists():
            p.unlink()
    print(f"DEFERRED circumstance head: {reason}")
    print(f"  Wrote {path}")
    return path


def train(*, holdout_frac: float, exam_seed: int | None, rare_boost: float) -> int:
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    if not path.exists():
        write_deferred(reason=f"missing lake {path}")
        return 0

    df = pd.read_parquet(path)
    if "unified_label" not in df.columns and "fault_type" in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()

    df, ready = ensure_circumstance_column(df)
    y_raw = df["circumstance_label"].astype(str)
    n_pos = int((y_raw != "healthy").sum())
    if not ready:
        write_deferred(
            reason=(
                "no circumstance existence signal in lake yet "
                f"({n_pos} non-healthy rows; need ≥{MIN_EXISTENCE_ROWS})"
            ),
            n_pos=n_pos,
        )
        return 0

    feats = feature_columns(df)
    if not feats:
        write_deferred(reason="no multi-scale feature columns found")
        return 0

    # Drop ultra-rare classes for stable stratified split
    keep = y_raw.value_counts()
    mask = y_raw.isin(keep[keep >= 5].index)
    df = df.loc[mask]
    y_raw = y_raw.loc[mask]
    X = df[feats]

    le_classes = [c for c in UNIFIED_LABELS if c in set(y_raw)]
    le_classes += sorted(set(y_raw) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = y_raw.map(class_to_idx).astype(int).values
    healthy_idx = class_to_idx["healthy"]
    rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}

    seed = exam_seed if exam_seed is not None else int(datetime.now(timezone.utc).timestamp())
    rng = np.random.default_rng(seed)
    blind = stratified_blind_holdout(y, df, holdout_frac, rng=rng, policy="random")
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]

    print(f"Circumstance existence train  seed={seed}")
    print("  lake existence counts:", {c: int((y_raw == c).sum()) for c in le_classes})
    print("  exam counts:", {le_classes[i]: int(np.sum(y_exam == i)) for i in range(len(le_classes))})

    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )

    # Sample weights: inverse freq + rare boost (existence of BGP/VRF matters)
    classes, counts = np.unique(y_fit, return_counts=True)
    freq = {int(c): int(n) for c, n in zip(classes, counts)}
    k, n = len(classes), len(y_fit)
    w = np.array([n / (k * freq[int(yi)]) for yi in y_fit], dtype=np.float64)
    if rare_boost != 1.0 and rare_ids:
        for i, yi in enumerate(y_fit):
            if int(yi) in rare_ids:
                w[i] *= rare_boost

    clf = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "xgb",
                XGBClassifier(
                    n_estimators=250,
                    max_depth=5,
                    learning_rate=0.08,
                    subsample=0.9,
                    colsample_bytree=0.9,
                    objective="multi:softprob",
                    num_class=len(le_classes),
                    eval_metric="mlogloss",
                    random_state=RANDOM_STATE,
                    n_jobs=4,
                ),
            ),
        ]
    )
    clf.fit(X_fit, y_fit, xgb__sample_weight=w)

    pred_exam = clf.predict(X_exam)
    report = classification_report(
        y_exam,
        pred_exam,
        labels=list(range(len(le_classes))),
        target_names=le_classes,
        zero_division=0,
        output_dict=True,
    )
    macro = float(f1_score(y_exam, pred_exam, average="macro", zero_division=0))
    acc = float(accuracy_score(y_exam, pred_exam))
    rare_rec = (
        float(
            np.mean(
                [
                    recall_score(y_exam == c, pred_exam == c, zero_division=0)
                    for c in rare_ids
                ]
            )
        )
        if rare_ids
        else 0.0
    )

    print(f"\n=== Circumstance existence exam ===")
    print(f"  Macro-F1={macro:.4f}  Acc={acc:.4f}  rareR={rare_rec:.4f}")
    for c in le_classes:
        if c in report:
            print(f"    {c}: F1={report[c]['f1-score']:.3f}  support={int(report[c]['support'])}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    deferred = OUT_DIR / "deferred.json"
    if deferred.exists():
        deferred.unlink()

    bundle = {
        "clf": clf,
        "classes": le_classes,
        "healthy_idx": healthy_idx,
        "feature_columns": feats,
        "mode": "circumstance_existence",
        "rare_boost": rare_boost,
        "phase": "loom_warp4",
        "note": (
            "Predicts which fault circumstance exists (run-up or breach). "
            "Not fault duration. Use with apply_loom pre-arm on chronological streams."
        ),
    }
    joblib.dump(bundle, OUT_DIR / "circumstance_xgb.pkl")

    metrics = {
        "date": datetime.now(timezone.utc).isoformat(),
        "status": "trained",
        "ready": True,
        "exam_seed": seed,
        "holdout_frac": holdout_frac,
        "n_train": int(len(X_fit)),
        "n_val": int(len(X_val)),
        "n_exam": int(len(X_exam)),
        "n_existence_rows": n_pos,
        "macro_f1": macro,
        "accuracy": acc,
        "mean_rare_recall": rare_rec,
        "per_class_f1": {c: float(report[c]["f1-score"]) for c in le_classes if c in report},
        "lake_existence_counts": {c: int((y_raw == c).sum()) for c in le_classes},
        "rare_boost": rare_boost,
    }
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # Patch manifest
    man_path = MODELS_DIR / "manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        models = man.setdefault("models", [])
        entry = {
            "name": "circumstance_existence_xgb",
            "path": "models/circumstance/circumstance_xgb.pkl",
            "role": "Does fault X's circumstance exist? (run-up ∪ breach)",
            "metrics": {
                "macro_f1": macro,
                "accuracy": acc,
                "mean_rare_recall": rare_rec,
                "per_class_f1": metrics["per_class_f1"],
            },
        }
        replaced = False
        for i, m in enumerate(models):
            if m.get("name") == "circumstance_existence_xgb":
                models[i] = entry
                replaced = True
                break
        if not replaced:
            models.append(entry)
        man["circumstance"] = {
            "date": metrics["date"],
            "macro_f1": macro,
            "ready": True,
        }
        man_path.write_text(json.dumps(man, indent=2))

    print(f"\nWrote {OUT_DIR / 'circumstance_xgb.pkl'}")
    print(f"Wrote {OUT_DIR / 'metrics.json'}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Train Temporal Loom circumstance existence head")
    p.add_argument("--holdout-frac", type=float, default=0.20)
    p.add_argument("--exam-seed", type=int, default=None)
    p.add_argument("--rare-boost", type=float, default=1.5)
    args = p.parse_args()
    return train(holdout_frac=args.holdout_frac, exam_seed=args.exam_seed, rare_boost=args.rare_boost)


if __name__ == "__main__":
    raise SystemExit(main())
