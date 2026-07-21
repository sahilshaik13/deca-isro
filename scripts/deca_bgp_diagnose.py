#!/usr/bin/env python3
"""One-off diagnostic: is bgp_route_flap's F1 collapse (0.51→0.45→0.35 across the
last two Tier-5 VRF campaigns) a class-weighting artifact in the β rare-boost
sweep, or a genuine data-support / separability problem?

Two campaigns deliberately varied VRF-adjacent training volume while leaving
bgp_route_flap's own volume flat; the exam headline (per-class F1 only) can't
tell us WHERE the loss happens:
  - at the anomaly gate (bgp windows never flagged as anomalous at all — a
    binary-separability problem the β sweep can't touch, since build_gate()
    always uses boost=1.0 and rare_ids=set()), or
  - at the multiclass head (bgp windows flagged anomalous but misclassified
    as a different fault — a class-confusion problem β *can* touch), or
  - genuinely support-starved (too few / too homogeneous bgp_route_flap
    windows for either stage to learn a robust boundary).

Reuses the exact data prep + model-building functions from
deca_school_exam_train.py so this is apples-to-apples with the real pipeline,
just with extra instrumentation (confusion matrix + gate-only recall) that
never gets persisted to latest_exam.json today.

Usage:
    python scripts/deca_bgp_diagnose.py --exam-seed 42 --family plain --beta 1.5
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import train_test_split

from _paths import PROCESSED_DIR
from deca_school_exam_train import (
    RANDOM_STATE,
    RARE,
    build_full_head,
    build_gate,
    feature_columns,
    predict_weighted_multiclass_with_confidence,
    stratified_blind_holdout,
    train_phase1,
    to_unified_label,
    UNIFIED_LABELS,
    _align_to_estimator_features,
)


def load_split(exam_seed: int, holdout_frac: float, holdout_policy: str):
    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    df = pd.read_parquet(path)
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)

    y_raw = df["unified_label"].astype(str)
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

    rng = np.random.default_rng(exam_seed)
    blind = stratified_blind_holdout(y, df, holdout_frac, rng=rng, policy=holdout_policy)
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]
    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )
    return X_fit, X_val, X_exam, y_fit, y_val, y_exam, le_classes, class_to_idx, healthy_idx, rare_ids


def main() -> None:
    p = argparse.ArgumentParser(description="Diagnose bgp_route_flap collapse: gate vs head vs support")
    p.add_argument("--exam-seed", type=int, default=42)
    p.add_argument("--holdout-frac", type=float, default=0.20)
    p.add_argument("--holdout-policy", default="random")
    p.add_argument("--family", default="plain", choices=["plain", "wm", "moe"])
    p.add_argument("--beta", type=float, default=1.5, help="rare_boost — 1.5 is the current best-sweep config")
    args = p.parse_args()

    (
        X_fit, X_val, X_exam, y_fit, y_val, y_exam,
        le_classes, class_to_idx, healthy_idx, rare_ids,
    ) = load_split(args.exam_seed, args.holdout_frac, args.holdout_policy)

    print(f"le_classes={le_classes}  healthy_idx={healthy_idx}  rare_ids={rare_ids}")
    print("\n=== Class support (fit pool vs exam) ===")
    fit_counts = {c: int(np.sum(y_fit == i)) for i, c in enumerate(le_classes)}
    exam_counts = {c: int(np.sum(y_exam == i)) for i, c in enumerate(le_classes)}
    for c in le_classes:
        print(f"  {c:20s} fit={fit_counts[c]:6d}  exam={exam_counts[c]:5d}")

    print(f"\n=== Training gate + full_clf (family={args.family}, beta={args.beta}) ===")
    gate = build_gate(X_fit, y_fit, healthy_idx=healthy_idx)
    _, full_clf, thr = train_phase1(
        X_fit, y_fit, X_val, y_val,
        healthy_idx=healthy_idx, rare_ids=rare_ids, boost=args.beta,
        family=args.family, gate=gate,
    )
    print(f"  gate_thr={thr['gate_thr']}  class_thr={thr['class_thr']}")

    # --- Stage 1: gate-only recall per class (independent of beta/class_thr) ---
    p_anom = gate.predict_proba(_align_to_estimator_features(gate, X_exam))[:, 1]
    print("\n=== Stage 1 — anomaly GATE recall per class (boost/class_thr can't affect this) ===")
    print(f"  gate_thr in use downstream: {thr['gate_thr']:.2f}  (also showing 0.30/0.50 for context)")
    for i, c in enumerate(le_classes):
        rows = y_exam == i
        n = int(rows.sum())
        if n == 0:
            continue
        mean_p = float(p_anom[rows].mean())
        for g in sorted({0.30, 0.50, float(thr["gate_thr"])}):
            passed = float((p_anom[rows] >= g).mean())
            print(f"    {c:20s} n={n:4d}  mean_p_anom={mean_p:.3f}  gate>={g:.2f} -> flagged={passed:.3f}")

    # --- Stage 2: full pipeline prediction + confusion matrix ---
    preds, _ = predict_weighted_multiclass_with_confidence(
        gate, full_clf, X_exam, healthy_idx=healthy_idx, gate_thr=thr["gate_thr"], class_thr=thr["class_thr"]
    )
    print("\n=== Stage 2 — full pipeline confusion matrix (rows=true, cols=predicted) ===")
    labels_order = list(range(len(le_classes)))
    cm = confusion_matrix(y_exam, preds, labels=labels_order)
    header = "true\\pred".ljust(20) + "".join(c[:12].rjust(14) for c in le_classes)
    print(header)
    for i, c in enumerate(le_classes):
        row = "".join(str(cm[i, j]).rjust(14) for j in range(len(le_classes)))
        print(f"  {c:18s}{row}")

    print("\n=== Where do missed bgp_route_flap / vrf_leakage rows actually land? ===")
    for target in ("bgp_route_flap", "vrf_leakage"):
        if target not in class_to_idx:
            continue
        ti = class_to_idx[target]
        rows = y_exam == ti
        n = int(rows.sum())
        pred_here = preds[rows]
        dist = {le_classes[j]: int(np.sum(pred_here == j)) for j in range(len(le_classes))}
        print(f"  true={target} (n={n}): predicted as -> {dist}")


if __name__ == "__main__":
    main()
