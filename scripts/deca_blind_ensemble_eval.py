#!/usr/bin/env python3
"""Honest holdout check: is the `wm` head a real second opinion, or an echo?

The blind-test ensemble (#5) gates confirmed declarations on `plain` and `wm`
*agreeing*. That gate only has value if `wm` is (a) competent on its own and
(b) genuinely **diverse** from `plain` — an echo that always agrees makes the
gate a no-op, and a head that disagrees at random just suppresses good calls.

This reproduces the School Exam methodology for exactly the two ensemble
families: it holds out a stratified, unseen exam split, trains one shared gate +
a `plain` and a `wm` head on the *study* rows only, tunes each head's thresholds
on a validation slice, and scores both on the held-out exam. Then it reports the
numbers that actually decide whether the agreement gate helps:

  - per-head exam macro-F1 / rare recall (is wm competent?),
  - plain↔wm disagreement rate (is wm diverse, i.e. not an echo?),
  - the gate's effect on plain's calls: how many of plain's FALSE positives wm
    would suppress, and how many of plain's TRUE positives wm would keep.

The deployed head (`fault_classifier_wm.pkl`) is trained on the full lake by the
same recipe; this script trains train-only heads purely to get an honest read on
unseen rows. Nothing here is written to models/.

Usage
-----
    python scripts/deca_blind_ensemble_eval.py                 # random exam, 20% holdout
    python scripts/deca_blind_ensemble_eval.py --exam-seed 7 --holdout-frac 0.25
"""
from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_school_exam_train import (
    RANDOM_STATE,
    RARE,
    build_full_head,
    build_gate,
    evaluate,
    feature_columns,
    predict_weighted_multiclass_with_confidence,
    stratified_blind_holdout,
    tune_thresholds,
)
from rebuild_unified import to_unified_label


def _pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser(description="Holdout diversity/echo check for the wm ensemble head")
    parser.add_argument("--exam-seed", type=int, default=20260716, help="Fixed exam draw for reproducibility")
    parser.add_argument("--holdout-frac", type=float, default=0.20, help="Exam fraction per class")
    parser.add_argument("--boost", type=float, default=1.0, help="Rare-class boost (both heads)")
    args = parser.parse_args()

    clf_dir = MODELS_DIR / "fault_classifier"
    le = joblib.load(clf_dir / "label_encoder.pkl")
    le_classes = list(le["classes"])
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    healthy_idx = class_to_idx["healthy"]
    rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}
    rare_idx_list = sorted(rare_ids)

    df = pd.read_parquet(PROCESSED_DIR / "deca_unified_dataset.parquet")
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
    blind = stratified_blind_holdout(y, df, args.holdout_frac, rng=rng, policy="random")
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]
    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )

    print("=" * 70)
    print(f"  ENSEMBLE HOLDOUT CHECK — exam_seed={args.exam_seed} holdout={args.holdout_frac}")
    print("=" * 70)
    print(f"  study rows={len(X_fit):,}  val rows={len(X_val):,}  EXAM rows={len(X_exam):,}")
    print("  exam class counts:",
          {le_classes[i]: int(np.sum(y_exam == i)) for i in range(len(le_classes))})

    gate = build_gate(X_fit, y_fit, healthy_idx=healthy_idx)

    heads = {}
    for fam in ("plain", "wm"):
        clf = build_full_head(fam, X_fit, y_fit, healthy_idx=healthy_idx,
                              rare_ids=rare_ids, boost=args.boost)
        thr = tune_thresholds(gate, clf, X_val, y_val, healthy_idx=healthy_idx, rare_ids=rare_ids)
        ev = evaluate(gate, clf, X_exam, y_exam, healthy_idx=healthy_idx,
                      gate_thr=thr["gate_thr"], class_thr=thr["class_thr"],
                      le_classes=le_classes, rare_idx_list=rare_idx_list)
        heads[fam] = {"clf": clf, "thr": thr, "ev": ev}
        print(f"\n  [{fam}] exam macro-F1={ev['macro_f1']:.4f}  "
              f"weighted-F1={ev['weighted_f1']:.4f}  rare-recall={ev['mean_rare_recall']:.4f}  "
              f"gate_thr={thr['gate_thr']:.2f}")

    plain_pred = heads["plain"]["ev"]["pred"]
    wm_pred = heads["wm"]["ev"]["pred"]

    # ── Diversity: is wm an echo of plain? ────────────────────────────────
    disagree = plain_pred != wm_pred
    print("\n" + "-" * 70)
    print("  DIVERSITY (echo check)")
    print(f"    overall plain↔wm disagreement : {_pct(disagree.sum(), len(plain_pred))} "
          f"({int(disagree.sum())}/{len(plain_pred)})")
    fault_rows = y_exam != healthy_idx
    print(f"    disagreement on true-fault rows: {_pct((disagree & fault_rows).sum(), fault_rows.sum())}")
    print(f"    disagreement on healthy rows   : {_pct((disagree & ~fault_rows).sum(), (~fault_rows).sum())}")
    if disagree.sum() == 0:
        print("    VERDICT: wm is an ECHO — agreement gate would be a no-op.")

    # ── Gate value: applied to PLAIN's would-be confirmed declarations ────
    # The operator confirms only when plain predicts non-healthy AND wm agrees.
    plain_fault = plain_pred != healthy_idx
    plain_correct = plain_fault & (plain_pred == y_exam)          # true positives
    plain_false = plain_fault & (y_exam == healthy_idx)           # false positives (healthy called fault)
    wm_agrees = wm_pred == plain_pred

    tp = int(plain_correct.sum())
    tp_kept = int((plain_correct & wm_agrees).sum())
    fp = int(plain_false.sum())
    fp_suppressed = int((plain_false & ~wm_agrees).sum())

    print("\n  AGREEMENT-GATE VALUE (on plain's would-be confirms)")
    print(f"    plain true positives         : {tp:>5}  kept by gate      : {tp_kept}  "
          f"({_pct(tp_kept, tp)} retained)")
    print(f"    plain false positives        : {fp:>5}  suppressed by gate: {fp_suppressed}  "
          f"({_pct(fp_suppressed, fp)} killed)")
    # Misclassified-fault (wrong class) rows are also partly caught; report them.
    plain_wrongclass = plain_fault & (y_exam != healthy_idx) & (plain_pred != y_exam)
    wc = int(plain_wrongclass.sum())
    wc_suppressed = int((plain_wrongclass & ~wm_agrees).sum())
    print(f"    plain wrong-class faults     : {wc:>5}  suppressed by gate: {wc_suppressed}  "
          f"({_pct(wc_suppressed, wc)})")

    print("\n" + "=" * 70)
    if disagree.sum() > 0 and tp > 0:
        keep_rate = tp_kept / tp
        kill_rate = fp_suppressed / fp if fp else None
        verdict = "USEFUL" if (keep_rate >= 0.9 and (kill_rate is None or kill_rate > 0)) else "MARGINAL"
        print(f"  VERDICT: wm is a genuine, diverse second opinion → gate looks {verdict}.")
        print(f"           keeps {_pct(tp_kept, tp)} of true positives, "
              f"kills {_pct(fp_suppressed, fp)} of false positives.")
    print("  NOTE: this is per-frame on shuffled rows; the blind run measures the")
    print("        same effect on chronologically-loomed declarations. Run one seed")
    print("        with and without --ensemble to confirm on real streams.")
    print("=" * 70)


if __name__ == "__main__":
    main()
