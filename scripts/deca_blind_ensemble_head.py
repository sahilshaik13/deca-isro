#!/usr/bin/env python3
"""Train + exam-score the ``wm`` companion head for the blind-test ensemble (#5).

Honest path (not the full-lake shortcut)
----------------------------------------
1. Carve a stratified blind holdout from the unified lake (School Exam paper).
2. Train the ``wm`` head **only** on the study pool — never on the exam rows.
3. Score both the promoted ``plain`` head and the new ``wm`` head on that same
   paper, and report agreement / disagreement so we know agreement gating has
   real diversity before leaning on ensemble numbers in a blind live run.

The operator loads ``fault_classifier_wm.pkl`` only when ``--ensemble`` is
passed; default single-head behaviour is unchanged.

Usage
-----
    python scripts/deca_blind_ensemble_head.py
    python scripts/deca_blind_ensemble_head.py --exam-seed 42 --boost 1.0
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import (
    RARE,
    build_full_head,
    evaluate,
    feature_columns,
    load_active_classifier,
    score_active_classifier,
    stratified_blind_holdout,
)
from rebuild_unified import to_unified_label


def _per_class_f1(report: dict, classes: list[str]) -> dict[str, float]:
    return {
        c: round(float(report[c]["f1-score"]), 3)
        for c in classes
        if c in report and isinstance(report[c], dict)
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train + exam-score the wm ensemble companion head"
    )
    parser.add_argument("--boost", type=float, default=1.0,
                        help="Rare-class inverse-freq boost for the wm head")
    parser.add_argument("--holdout-frac", type=float, default=0.2,
                        help="Fraction of each class held out as the exam paper")
    parser.add_argument("--exam-seed", type=int, default=42,
                        help="RNG seed for the stratified blind holdout (fixed = reproducible)")
    parser.add_argument("--holdout-policy", default="random",
                        choices=("random", "time_tail"),
                        help="School Exam holdout policy")
    parser.add_argument("--out", default=None,
                        help="Output pkl (default: models/fault_classifier/fault_classifier_wm.pkl)")
    parser.add_argument(
        "--min-disagree",
        type=float,
        default=0.02,
        help="Hard-abort only if disagreement is below this (heads are identical). "
        "Low-but-nonzero disagreement prints a WARN but still saves if agreement "
        "gating suppresses false faults on the exam.",
    )
    parser.add_argument(
        "--warn-disagree",
        type=float,
        default=0.05,
        help="Warn (but still save) when disagreement is below this fraction",
    )
    args = parser.parse_args()

    clf_dir = MODELS_DIR / "fault_classifier"
    le = joblib.load(clf_dir / "label_encoder.pkl")
    # Share the promoted head's exact class ordering so wm indices line up.
    le_classes = list(le["classes"])
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    healthy_idx = class_to_idx["healthy"]
    rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}
    rare_idx_list = sorted(rare_ids)

    path = PROCESSED_DIR / "deca_unified_dataset.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing feature lake: {path}")
    df = pd.read_parquet(path)
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)

    y_raw = df["unified_label"].astype(str)
    keep = y_raw.isin(class_to_idx)
    df, y_raw = df.loc[keep], y_raw.loc[keep]
    X = df[feats]
    y = y_raw.map(class_to_idx).astype(int).values

    rng = np.random.default_rng(args.exam_seed)
    blind = stratified_blind_holdout(
        y, df, args.holdout_frac, rng=rng, policy=args.holdout_policy
    )
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]

    counts_pool = {le_classes[i]: int(np.sum(y_pool == i)) for i in range(len(le_classes))}
    counts_exam = {le_classes[i]: int(np.sum(y_exam == i)) for i in range(len(le_classes))}
    print("=" * 68)
    print("  DECA wm COMPANION — School Exam holdout train + score")
    print("=" * 68)
    print(f"  lake={len(X):,}  study={len(X_pool):,}  exam={len(X_exam):,}  "
          f"seed={args.exam_seed}  policy={args.holdout_policy}")
    print(f"  study counts: {counts_pool}")
    print(f"  exam  counts: {counts_exam}")
    print(f"  Training wm on study pool only (rare_boost={args.boost})...")

    full_clf = build_full_head(
        "wm", X_pool, y_pool, healthy_idx=healthy_idx, rare_ids=rare_ids, boost=args.boost
    )

    # Score both heads on the same exam paper, sharing the promoted gate/thresholds
    # so the comparison is head-vs-head, not gate-vs-gate.
    plain_bundle = load_active_classifier()
    if plain_bundle is None:
        raise SystemExit("No promoted plain classifier — cannot exam-score the ensemble pair.")

    gate = plain_bundle["gate"]
    gate_thr = float(plain_bundle["gate_thr"])
    class_thr = {int(k): float(v) for k, v in plain_bundle.get("class_thr", {}).items()}

    plain_scored = score_active_classifier(
        plain_bundle, X_exam, y_exam, le_classes=le_classes, rare_idx_list=rare_idx_list
    )
    if plain_scored is None:
        raise SystemExit("Promoted plain head incompatible with lake features — abort.")

    wm_scored = evaluate(
        gate, full_clf, X_exam, y_exam,
        healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr,
        le_classes=le_classes, rare_idx_list=rare_idx_list,
    )

    plain_pred = plain_scored["pred"]
    wm_pred = wm_scored["pred"]
    agree = plain_pred == wm_pred
    agree_rate = float(np.mean(agree))
    disagree_rate = 1.0 - agree_rate

    # Where they disagree: how often is each one right?
    disagree_mask = ~agree
    n_dis = int(np.sum(disagree_mask))
    plain_right_when_dis = (
        float(np.mean(plain_pred[disagree_mask] == y_exam[disagree_mask])) if n_dis else None
    )
    wm_right_when_dis = (
        float(np.mean(wm_pred[disagree_mask] == y_exam[disagree_mask])) if n_dis else None
    )
    # Ensemble "agree-and-confirm" proxy: when both name the same non-healthy
    # class, how often is that class correct? (the live gate's useful case)
    both_fault = (plain_pred != healthy_idx) & (wm_pred != healthy_idx) & agree
    agree_fault_acc = (
        float(np.mean(plain_pred[both_fault] == y_exam[both_fault]))
        if int(np.sum(both_fault)) else None
    )
    # Spurious-confirm proxy: plain alone calls a fault but is wrong, vs when
    # both must agree (the live hypothesis).
    plain_alone_fault = (plain_pred != healthy_idx) & (plain_pred != y_exam)
    plain_alone_fa = int(np.sum(plain_alone_fault))
    ensemble_fa = int(np.sum(plain_alone_fault & agree & (wm_pred != healthy_idx)))

    exam_report = {
        "exam_seed": args.exam_seed,
        "holdout_frac": args.holdout_frac,
        "holdout_policy": args.holdout_policy,
        "exam_rows": int(len(X_exam)),
        "study_rows": int(len(X_pool)),
        "plain": {
            "macro_f1": round(plain_scored["macro_f1"], 4),
            "mean_rare_recall": round(plain_scored["mean_rare_recall"], 4),
            "per_class_f1": _per_class_f1(plain_scored["report"], le_classes),
        },
        "wm": {
            "macro_f1": round(wm_scored["macro_f1"], 4),
            "mean_rare_recall": round(wm_scored["mean_rare_recall"], 4),
            "per_class_f1": _per_class_f1(wm_scored["report"], le_classes),
        },
        "agreement_rate": round(agree_rate, 4),
        "disagreement_rate": round(disagree_rate, 4),
        "disagree_n": n_dis,
        "plain_right_when_disagree": (
            round(plain_right_when_dis, 4) if plain_right_when_dis is not None else None
        ),
        "wm_right_when_disagree": (
            round(wm_right_when_dis, 4) if wm_right_when_dis is not None else None
        ),
        "agree_fault_accuracy": (
            round(agree_fault_acc, 4) if agree_fault_acc is not None else None
        ),
        "plain_alone_false_faults": plain_alone_fa,
        "ensemble_false_faults_after_agree": ensemble_fa,
        "false_faults_suppressed_by_agree": plain_alone_fa - ensemble_fa,
    }

    print("-" * 68)
    print(f"  plain  exam Macro-F1={exam_report['plain']['macro_f1']:.4f}  "
          f"rare-recall={exam_report['plain']['mean_rare_recall']:.4f}")
    print(f"  wm     exam Macro-F1={exam_report['wm']['macro_f1']:.4f}  "
          f"rare-recall={exam_report['wm']['mean_rare_recall']:.4f}")
    print(f"  agreement={agree_rate:.1%}  disagreement={disagree_rate:.1%}  "
          f"(n_disagree={n_dis})")
    if n_dis:
        print(f"  when they disagree: plain right {plain_right_when_dis:.1%}  "
              f"wm right {wm_right_when_dis:.1%}")
    print(f"  agree-and-fault accuracy: {exam_report['agree_fault_accuracy']}")
    print(f"  plain-alone false faults: {plain_alone_fa}  →  "
          f"after agree gate: {ensemble_fa}  "
          f"(suppressed {plain_alone_fa - ensemble_fa})")
    print("-" * 68)

    if disagree_rate < args.min_disagree:
        raise SystemExit(
            f"ABORT: disagreement {disagree_rate:.1%} < --min-disagree {args.min_disagree:.0%}. "
            "Heads are essentially identical; agreement gating would be useless."
        )
    suppressed = plain_alone_fa - ensemble_fa
    if suppressed <= 0 and plain_alone_fa > 0:
        raise SystemExit(
            "ABORT: agreement gating suppressed 0 of the plain-alone false faults "
            "on the exam — the ensemble hypothesis does not hold on this paper."
        )

    out = args.out or (clf_dir / "fault_classifier_wm.pkl")
    joblib.dump(
        {
            "full_clf": full_clf,
            "head_family": "wm",
            "classes": le_classes,
            "healthy_idx": healthy_idx,
            "features": feats,
            "rare_boost": args.boost,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "exam": exam_report,
            "note": (
                "Companion head for the blind-test plain+wm agreement ensemble. "
                "Trained on the study pool of a stratified School Exam holdout; "
                "exam metrics recorded under 'exam'."
            ),
        },
        out,
    )
    report_path = clf_dir / "ensemble_exam_report.json"
    report_path.write_text(json.dumps(exam_report, indent=2), encoding="utf-8")
    print(f"  Saved wm ensemble head -> {out}")
    print(f"  Exam report            -> {report_path}")
    print("=" * 68)
    if disagree_rate < args.warn_disagree:
        print(
            f"  VERDICT: WARN — disagreement only {disagree_rate:.1%} "
            f"(heads are highly correlated). Agreement gating still suppressed "
            f"{suppressed}/{plain_alone_fa} plain-alone false faults on the exam "
            f"({100 * suppressed / plain_alone_fa:.0f}%), so --ensemble is a mild "
            "false-alarm filter, not a strong independent second opinion. Treat "
            "blind-live gains as small until multi-night A/B confirms them."
        )
    else:
        print(
            f"  VERDICT: wm is a real second opinion "
            f"(disagreement {disagree_rate:.1%}, suppressed {suppressed} false faults). "
            "Safe to lean on --ensemble."
        )
    print("=" * 68)


if __name__ == "__main__":
    main()
