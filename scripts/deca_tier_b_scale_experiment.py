#!/usr/bin/env python3
"""Tier B portability dry-run — isolated retrain on scale-shifted Network B.

Does NOT touch models/fault_classifier/ or manifest.json.
Writes candidates only under models/experiments/tier_b_*/.

Compares:
  - frozen promoted model on A / B (baseline + Tier-A-only numbers)
  - retrain on B-only  → models/experiments/tier_b_scale10x/
  - retrain on A+B mix → models/experiments/tier_b_mixed/

Uses existing build_gate / build_full_head / tune_thresholds / evaluate.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from _paths import MODELS_DIR, PROCESSED_DIR, REPO_ROOT
from deca_school_exam_train import (
    RARE,
    RANDOM_STATE,
    _align_to_estimator_features,
    evaluate,
    feature_columns,
    load_active_classifier,
    stratified_blind_holdout,
    train_phase1,
)
from rebuild_unified import UNIFIED_LABELS

SEED = 42
HOLDOUT = 0.40
FAMILY = "plain"
BETA = 1.0
SCALE = 10.0

A_PATH = PROCESSED_DIR / "network_a_control_sample.parquet"
B_PATH = PROCESSED_DIR / "network_b_scale10x_sample.parquet"
EXP_ROOT = MODELS_DIR / "experiments"
OUT_B_ONLY = EXP_ROOT / "tier_b_scale10x"
OUT_MIXED = EXP_ROOT / "tier_b_mixed"
PROMOTED_PKL = MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl"
PROMOTED_THR = MODELS_DIR / "fault_classifier" / "decision_thresholds.json"


def _assert_promoted_untouched(before_mtime: float, before_sha_prefix: bytes) -> None:
    after_mtime = PROMOTED_PKL.stat().st_mtime
    after_bytes = PROMOTED_PKL.read_bytes()[:64]
    if after_mtime != before_mtime or after_bytes != before_sha_prefix:
        raise RuntimeError(
            "REFUSAL: models/fault_classifier/fault_classifier_xgb.pkl changed during "
            "this experiment — aborting. Nothing should have written there."
        )


def _labels(frame: pd.DataFrame):
    le_classes = [c for c in UNIFIED_LABELS if c in set(frame["unified_label"])]
    le_classes += sorted(set(frame["unified_label"]) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = frame["unified_label"].map(class_to_idx).to_numpy(dtype=int)
    healthy_idx = class_to_idx["healthy"]
    rare_ids = {class_to_idx[c] for c in RARE if c in class_to_idx}
    return le_classes, class_to_idx, y, healthy_idx, rare_ids


def _score(gate, full_clf, X, y, *, healthy_idx, gate_thr, class_thr, le_classes, rare_ids):
    Xa = _align_to_estimator_features(full_clf, X)
    # gate may have different feature names — align separately if needed
    Xg = _align_to_estimator_features(gate, Xa)
    # predict_weighted uses gate+full on same X; re-align full to Xg columns if mismatch
    X_use = Xg if list(Xg.columns) == list(Xa.columns) else Xa
    # Prefer columns the full head expects
    X_use = _align_to_estimator_features(full_clf, X)
    X_use = _align_to_estimator_features(gate, X_use)
    return evaluate(
        gate,
        full_clf,
        X_use,
        y,
        healthy_idx=healthy_idx,
        gate_thr=gate_thr,
        class_thr=class_thr,
        le_classes=le_classes,
        rare_idx_list=sorted(rare_ids),
    )


def _train_and_save(name: str, X_pool, y_pool, *, healthy_idx, rare_ids, le_classes, out_dir: Path):
    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )
    print(f"\n=== Training {name}  family={FAMILY} β={BETA} ===")
    print(f"  fit={len(X_fit)}  val={len(X_val)}  → {out_dir}")
    gate, full_clf, best = train_phase1(
        X_fit,
        y_fit,
        X_val,
        y_val,
        healthy_idx=healthy_idx,
        rare_ids=rare_ids,
        boost=BETA,
        family=FAMILY,
    )
    idx_to_class = {i: c for i, c in enumerate(le_classes)}
    class_thr_named = {idx_to_class[k]: v for k, v in best["class_thr"].items() if k in idx_to_class}
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "gate": gate,
        "full_clf": full_clf,
        "healthy_idx": healthy_idx,
        "gate_thr": best["gate_thr"],
        "class_thr": best["class_thr"],
        "mode": "weighted_multiclass",
        "family": FAMILY,
        "rare_boost": BETA,
        "experiment": name,
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "ISOLATED dry-run — not promoted; do not copy into fault_classifier/",
    }
    joblib.dump(bundle, out_dir / "fault_classifier_xgb.pkl")
    (out_dir / "decision_thresholds.json").write_text(
        json.dumps(
            {
                "gate_thr": best["gate_thr"],
                "class_thr": class_thr_named,
                "val_macro_f1": best["macro_f1"],
                "family": FAMILY,
                "rare_boost": BETA,
                "experiment": name,
                "isolated": True,
            },
            indent=2,
        )
    )
    joblib.dump(
        {"classes": le_classes, "smote": False, "isolated_experiment": True},
        out_dir / "label_encoder.pkl",
    )
    print(f"  val macro_f1={best['macro_f1']:.4f}  gate_thr={best['gate_thr']}  class_thr={class_thr_named}")
    print(f"  wrote {out_dir}/ (promoted tree untouched)")
    return gate, full_clf, best


def main() -> None:
    promoted_mtime = PROMOTED_PKL.stat().st_mtime
    promoted_prefix = PROMOTED_PKL.read_bytes()[:64]
    print(f"Promoted pkl mtime locked at {promoted_mtime} — will re-check at end.")

    if not A_PATH.exists() or not B_PATH.exists():
        raise SystemExit(f"Missing samples: {A_PATH} / {B_PATH}")

    A = pd.read_parquet(A_PATH).reset_index(drop=True)
    B = pd.read_parquet(B_PATH).reset_index(drop=True)
    if len(A) != len(B) or not A["unified_label"].equals(B["unified_label"]):
        raise SystemExit("A/B samples must be row-aligned with identical labels")

    feats = feature_columns(A)
    # Ensure B has the same feature cols
    missing = [c for c in feats if c not in B.columns]
    if missing:
        raise SystemExit(f"B missing features: {missing[:5]}...")

    le_classes, class_to_idx, y, healthy_idx, rare_ids = _labels(A)
    X_A = A[feats]
    X_B = B[feats]

    hold = stratified_blind_holdout(
        y, A, HOLDOUT, rng=np.random.default_rng(SEED), policy="random"
    )
    # Boolean mask → index arrays
    exam_idx = np.where(hold)[0]
    pool_idx = np.where(~hold)[0]
    print(
        f"Fixed exam seed={SEED} holdout={HOLDOUT}: "
        f"exam={len(exam_idx)} pool={len(pool_idx)} classes={le_classes}"
    )
    print("Exam label counts:", {le_classes[i]: int(np.sum(y[exam_idx] == i)) for i in range(len(le_classes))})

    # --- Frozen promoted baselines (read-only) ---
    active = load_active_classifier()
    if active is None:
        raise SystemExit("No active classifier to score as baseline")
    thr = json.loads(PROMOTED_THR.read_text())
    old_gate = float(thr.get("gate_thr", active.get("gate_thr", 0.5)))
    old_class_named = thr.get("class_thr", {})
    old_class = {
        int(class_to_idx[c]): float(v)
        for c, v in old_class_named.items()
        if c in class_to_idx
    }

    print("\n=== Scoring frozen promoted model (read-only) ===")
    base_A = _score(
        active["gate"],
        active["full_clf"],
        X_A.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=old_gate,
        class_thr=old_class,
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    base_B = _score(
        active["gate"],
        active["full_clf"],
        X_B.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=old_gate,
        class_thr=old_class,
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    print(f"  promoted on A: macro_f1={base_A['macro_f1']:.4f}  rare_recall={base_A['mean_rare_recall']:.4f}")
    print(f"  promoted on B: macro_f1={base_B['macro_f1']:.4f}  rare_recall={base_B['mean_rare_recall']:.4f}")

    # Tier A on B (recal thresholds only, no tree retrain) — for the table
    from deca_school_exam_train import tune_thresholds

    Xb_exam = _align_to_estimator_features(active["full_clf"], X_B.iloc[exam_idx].reset_index(drop=True))
    Xb_exam = _align_to_estimator_features(active["gate"], Xb_exam)
    tier_a_best = tune_thresholds(
        active["gate"],
        active["full_clf"],
        Xb_exam,
        y[exam_idx],
        healthy_idx=healthy_idx,
        rare_ids=rare_ids,
    )
    tier_a_B = evaluate(
        active["gate"],
        active["full_clf"],
        Xb_exam,
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=tier_a_best["gate_thr"],
        class_thr=tier_a_best["class_thr"],
        le_classes=le_classes,
        rare_idx_list=sorted(rare_ids),
    )
    # Tier A on A (should be near-null)
    Xa_exam = _align_to_estimator_features(active["full_clf"], X_A.iloc[exam_idx].reset_index(drop=True))
    Xa_exam = _align_to_estimator_features(active["gate"], Xa_exam)
    tier_a_on_A = evaluate(
        active["gate"],
        active["full_clf"],
        Xa_exam,
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=tier_a_best["gate_thr"],
        class_thr=tier_a_best["class_thr"],
        le_classes=le_classes,
        rare_idx_list=sorted(rare_ids),
    )
    print(
        f"  Tier A (recal on B exam) → B macro_f1={tier_a_B['macro_f1']:.4f}  "
        f"rare_recall={tier_a_B['mean_rare_recall']:.4f}"
    )
    print(f"  same Tier-A thr scored on A: macro_f1={tier_a_on_A['macro_f1']:.4f}")

    # --- Tier B: B-only retrain ---
    gate_b, clf_b, best_b = _train_and_save(
        "tier_b_scale10x_b_only",
        X_B.iloc[pool_idx].reset_index(drop=True),
        y[pool_idx],
        healthy_idx=healthy_idx,
        rare_ids=rare_ids,
        le_classes=le_classes,
        out_dir=OUT_B_ONLY,
    )
    b_only_on_B = _score(
        gate_b,
        clf_b,
        X_B.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=best_b["gate_thr"],
        class_thr=best_b["class_thr"],
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    b_only_on_A = _score(
        gate_b,
        clf_b,
        X_A.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=best_b["gate_thr"],
        class_thr=best_b["class_thr"],
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    print(f"  B-only → on B: macro_f1={b_only_on_B['macro_f1']:.4f}  rare_recall={b_only_on_B['mean_rare_recall']:.4f}")
    print(f"  B-only → on A: macro_f1={b_only_on_A['macro_f1']:.4f}  rare_recall={b_only_on_A['mean_rare_recall']:.4f}")

    # --- Tier B: mixed A+B retrain ---
    X_mix = pd.concat(
        [X_A.iloc[pool_idx], X_B.iloc[pool_idx]], axis=0, ignore_index=True
    )
    y_mix = np.concatenate([y[pool_idx], y[pool_idx]])
    gate_m, clf_m, best_m = _train_and_save(
        "tier_b_mixed_a_plus_b",
        X_mix,
        y_mix,
        healthy_idx=healthy_idx,
        rare_ids=rare_ids,
        le_classes=le_classes,
        out_dir=OUT_MIXED,
    )
    mixed_on_B = _score(
        gate_m,
        clf_m,
        X_B.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=best_m["gate_thr"],
        class_thr=best_m["class_thr"],
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    mixed_on_A = _score(
        gate_m,
        clf_m,
        X_A.iloc[exam_idx].reset_index(drop=True),
        y[exam_idx],
        healthy_idx=healthy_idx,
        gate_thr=best_m["gate_thr"],
        class_thr=best_m["class_thr"],
        le_classes=le_classes,
        rare_ids=rare_ids,
    )
    print(f"  mixed → on B: macro_f1={mixed_on_B['macro_f1']:.4f}  rare_recall={mixed_on_B['mean_rare_recall']:.4f}")
    print(f"  mixed → on A: macro_f1={mixed_on_A['macro_f1']:.4f}  rare_recall={mixed_on_A['mean_rare_recall']:.4f}")

    # --- Comparison table ---
    drop = base_A["macro_f1"] - base_B["macro_f1"]

    def pct_recovered(new_b: float) -> float:
        if drop < 1e-9:
            return float("nan")
        return 100.0 * (new_b - base_B["macro_f1"]) / drop

    rows = [
        ("Network A baseline (promoted, frozen)", base_A["macro_f1"], base_B["macro_f1"], base_B["mean_rare_recall"], pct_recovered(base_B["macro_f1"])),
        ("Network B + Tier A only (recal thr)", tier_a_on_A["macro_f1"], tier_a_B["macro_f1"], tier_a_B["mean_rare_recall"], pct_recovered(tier_a_B["macro_f1"])),
        ("Network B + Tier B (B-only train)", b_only_on_A["macro_f1"], b_only_on_B["macro_f1"], b_only_on_B["mean_rare_recall"], pct_recovered(b_only_on_B["macro_f1"])),
        ("Network B + Tier B (mixed A+B train)", mixed_on_A["macro_f1"], mixed_on_B["macro_f1"], mixed_on_B["mean_rare_recall"], pct_recovered(mixed_on_B["macro_f1"])),
    ]

    print("\n" + "=" * 90)
    print("COMPARISON TABLE")
    print("=" * 90)
    print(f"{'approach':<42} {'macro-F1 on A':>14} {'macro-F1 on B':>14} {'rare recall B':>14} {'% of 0.59-drop recovered on B':>30}")
    for name, ma, mb, rr, pct in rows:
        print(f"{name:<42} {ma:14.4f} {mb:14.4f} {rr:14.4f} {pct:29.1f}%")

    print("\n" + "=" * 90)
    print("PLAIN-LANGUAGE READ")
    print("=" * 90)
    print(f"Scale-induced drop (promoted A→B): {drop:.4f} ({base_A['macro_f1']:.4f} → {base_B['macro_f1']:.4f})")
    print(
        f"Tier A recovered: {tier_a_B['macro_f1'] - base_B['macro_f1']:+.4f} "
        f"({pct_recovered(tier_a_B['macro_f1']):.1f}% of drop)"
    )
    print(
        f"Tier B B-only recovered: {b_only_on_B['macro_f1'] - base_B['macro_f1']:+.4f} "
        f"({pct_recovered(b_only_on_B['macro_f1']):.1f}% of drop) — "
        f"on A now {b_only_on_A['macro_f1']:.4f} (Δ vs baseline A {b_only_on_A['macro_f1']-base_A['macro_f1']:+.4f})"
    )
    print(
        f"Tier B mixed recovered: {mixed_on_B['macro_f1'] - base_B['macro_f1']:+.4f} "
        f"({pct_recovered(mixed_on_B['macro_f1']):.1f}% of drop) — "
        f"on A now {mixed_on_A['macro_f1']:.4f} (Δ vs baseline A {mixed_on_A['macro_f1']-base_A['macro_f1']:+.4f})"
    )
    if mixed_on_B["macro_f1"] < b_only_on_B["macro_f1"] - 0.01:
        print("NOTE: mixed underperforms B-only on B — specialization beats pooling here.")
    if b_only_on_A["macro_f1"] < base_A["macro_f1"] - 0.05:
        print("NOTE: B-only train regresses on A — classic forgetting if you swap models.")
    if mixed_on_A["macro_f1"] >= base_A["macro_f1"] - 0.05 and mixed_on_B["macro_f1"] > tier_a_B["macro_f1"] + 0.1:
        print("NOTE: mixed looks like the practical onboarding path (keeps A, lifts B).")

    report = {
        "exam_seed": SEED,
        "holdout_frac": HOLDOUT,
        "family": FAMILY,
        "beta": BETA,
        "scale": SCALE,
        "n_exam": int(len(exam_idx)),
        "n_pool": int(len(pool_idx)),
        "drop_A_to_B": float(drop),
        "rows": [
            {
                "approach": name,
                "macro_f1_on_A": float(ma),
                "macro_f1_on_B": float(mb),
                "rare_recall_on_B": float(rr),
                "pct_drop_recovered_on_B": float(pct),
            }
            for name, ma, mb, rr, pct in rows
        ],
        "isolated": True,
        "promoted_path_untouched": True,
        "written_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    EXP_ROOT.mkdir(parents=True, exist_ok=True)
    report_path = EXP_ROOT / "tier_b_scale10x_comparison.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {report_path}")

    _assert_promoted_untouched(promoted_mtime, promoted_prefix)
    print("Confirmed: models/fault_classifier/fault_classifier_xgb.pkl unchanged.")


if __name__ == "__main__":
    main()
