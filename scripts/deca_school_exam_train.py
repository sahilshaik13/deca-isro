#!/usr/bin/env python3
"""DECA School Exam training (Mode A) — same lake, weight sweep + promotion gate.

Uses the current unified feature matrix. No new campaign data required.
See docs/DECA_MLOps_Continuous_Learning_Pipeline.md.
"""
from __future__ import annotations

import argparse
import json
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, f1_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from _paths import MODELS_DIR, PROCESSED_DIR, REPO_ROOT
from rebuild_unified import UNIFIED_LABELS, to_unified_label

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

RANDOM_STATE = 42
META = {
    "run_id",
    "source",
    "fault_type",
    "unified_label",
    "is_anomaly",
    "time_to_breach_minutes",
    "timestamp",
}
RARE = {"bgp_route_flap", "vrf_leakage"}


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [
        c
        for c in df.columns
        if c not in META
        and (
            c.endswith("_slope")
            or c.endswith("_rolling_std")
            or c.endswith("_rolling_mean")
            or c.endswith("_accel")
        )
    ]


def inverse_frequency_weights(y: np.ndarray, *, rare_ids: set[int], boost: float) -> np.ndarray:
    y = np.asarray(y, dtype=int)
    classes, counts = np.unique(y, return_counts=True)
    freq = {int(c): int(n) for c, n in zip(classes, counts)}
    k, n = len(classes), len(y)
    w = np.array([n / (k * freq[int(yi)]) for yi in y], dtype=np.float64)
    if boost != 1.0 and rare_ids:
        for i, yi in enumerate(y):
            if int(yi) in rare_ids:
                w[i] *= boost
    return w


def predict_weighted_multiclass(gate, full_clf, X, *, healthy_idx, gate_thr, class_thr):
    p_anom = gate.predict_proba(X)[:, 1]
    p_full = full_clf.predict_proba(X)
    full_classes = list(full_clf.named_steps["xgb"].classes_)
    preds = np.full(len(p_anom), healthy_idx, dtype=int)
    for i in range(len(p_anom)):
        if p_anom[i] < gate_thr:
            continue
        scores = [
            p_full[i, j] / max(class_thr.get(int(cid), 1.0), 1e-6)
            for j, cid in enumerate(full_classes)
        ]
        preds[i] = int(full_classes[int(np.argmax(scores))])
    return preds


def tune_thresholds(gate, full_clf, X_val, y_val, *, healthy_idx, rare_ids):
    gate_grid = [0.20, 0.30, 0.40, 0.50, 0.60]
    thr_grid = [0.50, 0.65, 0.80, 1.00, 1.20]
    best = {"gate_thr": 0.5, "class_thr": {}, "score": -1.0, "macro_f1": -1.0}
    p_full = full_clf.predict_proba(X_val)
    full_classes = list(full_clf.named_steps["xgb"].classes_)
    p_anom = gate.predict_proba(X_val)[:, 1]

    def rare_aware(yt, yp):
        macro = f1_score(yt, yp, average="macro", zero_division=0)
        rares = [f1_score(yt == c, yp == c, zero_division=0) for c in rare_ids]
        return 0.4 * macro + 0.6 * float(np.mean(rares) if rares else macro), float(macro)

    for g in gate_grid:
        for rt in thr_grid:
            for ct in thr_grid:
                if rt > ct:
                    continue
                thrs = {int(c): (rt if int(c) in rare_ids else ct) for c in full_classes}
                thrs[int(healthy_idx)] = max(thrs.get(int(healthy_idx), 1.0), 1.0)
                preds = np.full(len(y_val), healthy_idx, dtype=int)
                for i in range(len(y_val)):
                    if p_anom[i] < g:
                        continue
                    scores = [
                        p_full[i, j] / max(thrs[int(cid)], 1e-6)
                        for j, cid in enumerate(full_classes)
                    ]
                    preds[i] = int(full_classes[int(np.argmax(scores))])
                score, macro = rare_aware(y_val, preds)
                if score > best["score"]:
                    best.update(
                        gate_thr=g,
                        class_thr={int(k): float(v) for k, v in thrs.items()},
                        score=score,
                        macro_f1=macro,
                    )
    return best


def make_xgb(**kw):
    return XGBClassifier(
        n_estimators=kw.get("n_estimators", 250),
        max_depth=kw.get("max_depth", 5),
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )


def train_phase1(X_fit, y_fit, X_val, y_val, *, healthy_idx, rare_ids, boost: float):
    y_bin = (y_fit != healthy_idx).astype(int)
    gate = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("xgb", make_xgb(n_estimators=200, max_depth=4)),
        ]
    )
    gate.fit(
        X_fit,
        y_bin,
        xgb__sample_weight=inverse_frequency_weights(y_bin, rare_ids=set(), boost=1.0),
    )

    full_clf = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("xgb", make_xgb()),
        ]
    )
    full_clf.fit(
        X_fit,
        y_fit,
        xgb__sample_weight=inverse_frequency_weights(y_fit, rare_ids=rare_ids, boost=boost),
    )
    best = tune_thresholds(
        gate, full_clf, X_val, y_val, healthy_idx=healthy_idx, rare_ids=rare_ids
    )
    return gate, full_clf, best


def evaluate(gate, full_clf, X, y, *, healthy_idx, gate_thr, class_thr, le_classes, rare_idx_list):
    pred = predict_weighted_multiclass(
        gate,
        full_clf,
        X,
        healthy_idx=healthy_idx,
        gate_thr=gate_thr,
        class_thr=class_thr,
    )
    macro = float(f1_score(y, pred, average="macro", zero_division=0))
    weighted = float(f1_score(y, pred, average="weighted", zero_division=0))
    rare_recalls = []
    for c in rare_idx_list:
        rare_recalls.append(
            float(recall_score(y == c, pred == c, zero_division=0))
        )
    mean_rare_recall = float(np.mean(rare_recalls)) if rare_recalls else 0.0
    report = classification_report(
        y,
        pred,
        labels=list(range(len(le_classes))),
        target_names=le_classes,
        zero_division=0,
        output_dict=True,
    )
    return {
        "macro_f1": macro,
        "weighted_f1": weighted,
        "mean_rare_recall": mean_rare_recall,
        "report": report,
        "pred": pred,
    }


def load_baseline_macro(override: float | None) -> float:
    if override is not None:
        return float(override)
    man = MODELS_DIR / "manifest.json"
    if man.exists():
        data = json.loads(man.read_text())
        for m in data.get("models", []):
            if m.get("name") == "fault_classifier_xgb":
                return float(m.get("metrics", {}).get("macro_f1", 0.721))
        for row in data.get("scoreboard", {}).get("summary", []):
            if "XGBoost" in row.get("Component", ""):
                # "Macro-F1 0.721, Acc 0.94"
                text = row.get("Primary score", "")
                for tok in text.replace(",", " ").split():
                    try:
                        v = float(tok)
                        if 0.5 < v < 1.0:
                            return v
                    except ValueError:
                        continue
    return 0.721


def stratified_blind_holdout(
    y: np.ndarray,
    df: pd.DataFrame,
    holdout_frac: float,
    *,
    rng: np.random.Generator,
    policy: str = "random",
) -> np.ndarray:
    """True = exam/blind rows. Stratify by label so rare faults stay in the exam.

    policy:
      - random — new questions each run (default): random sample per class
      - time_tail — latest holdout_frac by timestamp within each class (harder drift quiz)
    """
    idx = np.zeros(len(df), dtype=bool)
    for c in np.unique(y):
        pos = np.where(y == c)[0]
        if len(pos) < 5:
            continue
        n_blind = max(1, int(round(len(pos) * holdout_frac)))
        n_blind = min(n_blind, len(pos) - 1)  # leave ≥1 for study
        if policy == "time_tail":
            pos_sorted = pos[np.argsort(df.index.values[pos])]
            pick = pos_sorted[-n_blind:]
        else:
            pick = rng.choice(pos, size=n_blind, replace=False)
        idx[pick] = True
    return idx


def main() -> None:
    parser = argparse.ArgumentParser(description="DECA School Exam train (Mode A)")
    parser.add_argument("--holdout-frac", type=float, default=0.20)
    parser.add_argument(
        "--holdout-policy",
        choices=("random", "time_tail"),
        default="random",
        help="random = new exam paper each run (anti-memorization); time_tail = latest per class",
    )
    parser.add_argument(
        "--exam-seed",
        type=int,
        default=None,
        help="Exam RNG seed. Default: fresh each run (UTC epoch seconds) so questions change",
    )
    parser.add_argument(
        "--rare-boosts",
        type=str,
        default="1,1.5,2,3",
        help="Comma-separated β multipliers for BGP/VRF sample weights",
    )
    parser.add_argument("--promote", action="store_true", help="Write best candidate if gate passes")
    parser.add_argument("--baseline-macro-f1", type=float, default=None)
    parser.add_argument(
        "--min-rare-recall-drop",
        type=float,
        default=0.03,
        help="Allow candidate mean rare recall to be at most this much below unit-test baseline of best effort",
    )
    args = parser.parse_args()
    boosts = [float(x) for x in args.rare_boosts.split(",") if x.strip()]
    exam_seed = args.exam_seed if args.exam_seed is not None else int(datetime.now(timezone.utc).timestamp())
    rng = np.random.default_rng(exam_seed)

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
    rare_idx_list = sorted(rare_ids)

    blind = stratified_blind_holdout(
        y, df, args.holdout_frac, rng=rng, policy=args.holdout_policy
    )
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]

    print(f"Exam paper seed={exam_seed}  policy={args.holdout_policy}  (new questions each run unless --exam-seed fixed)")
    print("Exam label counts:", {le_classes[i]: int(np.sum(y_exam == i)) for i in range(len(le_classes))})

    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )

    baseline = load_baseline_macro(args.baseline_macro_f1)
    print(f"Lake rows={len(df):,}  features={len(feats)}  exam rows={len(X_exam):,}")
    print(f"Baseline Macro-F1 to beat: {baseline:.4f}")
    print(f"Rare boosts β={boosts}")
    print(f"Classes: {le_classes}")

    results = []
    best = None

    for beta in boosts:
        print(f"\n=== Study hall  β={beta} ===")
        gate, full_clf, thr = train_phase1(
            X_fit,
            y_fit,
            X_val,
            y_val,
            healthy_idx=healthy_idx,
            rare_ids=rare_ids,
            boost=beta,
        )
        exam = evaluate(
            gate,
            full_clf,
            X_exam,
            y_exam,
            healthy_idx=healthy_idx,
            gate_thr=thr["gate_thr"],
            class_thr=thr["class_thr"],
            le_classes=le_classes,
            rare_idx_list=rare_idx_list,
        )
        row = {
            "rare_boost": beta,
            "gate_thr": thr["gate_thr"],
            "val_macro_f1": thr["macro_f1"],
            "exam_macro_f1": exam["macro_f1"],
            "exam_weighted_f1": exam["weighted_f1"],
            "exam_mean_rare_recall": exam["mean_rare_recall"],
            "per_class_f1": {
                c: float(exam["report"][c]["f1-score"]) for c in le_classes
            },
        }
        print(
            f"  val macro-F1={thr['macro_f1']:.4f}  "
            f"EXAM macro-F1={exam['macro_f1']:.4f}  "
            f"rare-recall={exam['mean_rare_recall']:.4f}  "
            f"gate_thr={thr['gate_thr']:.2f}"
        )
        for c in RARE:
            if c in exam["report"]:
                print(
                    f"    {c}: P={exam['report'][c]['precision']:.2f} "
                    f"R={exam['report'][c]['recall']:.2f} "
                    f"F1={exam['report'][c]['f1-score']:.2f}"
                )
        results.append(row)
        payload = {
            "gate": gate,
            "full_clf": full_clf,
            "thr": thr,
            "exam": exam,
            "row": row,
            "le_classes": le_classes,
            "healthy_idx": healthy_idx,
            "rare_ids": list(rare_ids),
            "class_to_idx": class_to_idx,
            "feats": feats,
        }
        if best is None or exam["macro_f1"] > best["exam"]["macro_f1"]:
            best = payload

    assert best is not None
    summary = pd.DataFrame(
        [
            {
                "rare_boost": r["rare_boost"],
                "exam_macro_f1": r["exam_macro_f1"],
                "exam_mean_rare_recall": r["exam_mean_rare_recall"],
                "val_macro_f1": r["val_macro_f1"],
                "gate_thr": r["gate_thr"],
            }
            for r in results
        ]
    )
    out_dir = MODELS_DIR / "school_exam"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "weight_sweep.csv"
    summary.to_csv(summary_path, index=False)
    report_path = out_dir / "latest_exam.json"
    report_path.write_text(
        json.dumps(
            {
                "training_date": datetime.now(timezone.utc).isoformat(),
                "mode": "school_exam_A",
                "exam_seed": exam_seed,
                "holdout_policy": args.holdout_policy,
                "baseline_macro_f1": baseline,
                "holdout_frac": args.holdout_frac,
                "best": best["row"],
                "sweep": results,
                "anti_memorization": "fresh stratified exam draw each run unless --exam-seed is fixed",
            },
            indent=2,
        )
    )
    print(f"\nWrote {summary_path}")
    print(f"Wrote {report_path}")

    cand = best["exam"]["macro_f1"]
    rare = best["exam"]["mean_rare_recall"]
    # unit-test floor: mean rare recall among sweep as soft guard
    rare_floor = max(r["exam_mean_rare_recall"] for r in results) - args.min_rare_recall_drop
    gate_ok = cand >= baseline and rare >= rare_floor
    print("\n=== Great Exam / promotion gate ===")
    print(f"  candidate Macro-F1={cand:.4f}  baseline={baseline:.4f}")
    print(f"  candidate rare-recall={rare:.4f}  floor≈{rare_floor:.4f}")
    print(f"  GATE: {'PASS' if gate_ok else 'FAIL'}")

    if not args.promote:
        print("  (dry run — pass --promote to overwrite models/fault_classifier if PASS)")
        return

    if not gate_ok:
        print("  Refuse promote — keeping active models/")
        return

    # Persist Phase-1 classifier compatible with notebook artifacts (weighted_multiclass)
    clf_dir = MODELS_DIR / "fault_classifier"
    bak = MODELS_DIR / f"fault_classifier.bak_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    if clf_dir.exists():
        if bak.exists():
            shutil.rmtree(bak)
        shutil.move(str(clf_dir), str(bak))
        print(f"  Backed up previous classifier → {bak.name}")
    clf_dir.mkdir(parents=True, exist_ok=True)

    thr = best["thr"]
    idx_to_class = {i: c for c, i in class_to_idx.items()}
    thr_named = {
        (idx_to_class[k] if k in idx_to_class else str(k)): v for k, v in thr["class_thr"].items()
    }
    joblib.dump(
        {
            "gate": best["gate"],
            "fault_clf": None,
            "full_clf": best["full_clf"],
            "mode": "weighted_multiclass",
            "gate_thr": thr["gate_thr"],
            "class_thr": thr["class_thr"],
            "healthy_idx": healthy_idx,
            "fault_class_ids": [i for i in range(len(le_classes)) if i != healthy_idx],
            "local_to_global": {},
            "global_to_local": {},
            "rare_global_ids": best["rare_ids"],
            "phase": "school_exam_A",
            "rare_boost": best["row"]["rare_boost"],
        },
        clf_dir / "fault_classifier_xgb.pkl",
    )
    joblib.dump(
        {
            "classes": le_classes,
            "mode": "weighted_multiclass",
            "gate_thr": thr["gate_thr"],
            "class_thr": thr_named,
            "smote": False,
            "smote_policy": "refused_tier4_temporal_integrity",
            "school_exam": True,
            "rare_boost": best["row"]["rare_boost"],
        },
        clf_dir / "label_encoder.pkl",
    )
    (clf_dir / "decision_thresholds.json").write_text(
        json.dumps(
            {
                "mode": "weighted_multiclass",
                "gate_thr": thr["gate_thr"],
                "class_thr": thr_named,
                "exam_macro_f1": cand,
                "exam_mean_rare_recall": rare,
                "rare_boost": best["row"]["rare_boost"],
            },
            indent=2,
        )
    )

    # Patch manifest classifier metrics if present
    man_path = MODELS_DIR / "manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        man["school_exam"] = {
            "date": datetime.now(timezone.utc).isoformat(),
            "rare_boost": best["row"]["rare_boost"],
            "exam_macro_f1": cand,
            "exam_mean_rare_recall": rare,
            "baseline_macro_f1": baseline,
            "promoted": True,
        }
        for m in man.get("models", []):
            if m.get("name") == "fault_classifier_xgb":
                m["metrics"] = {
                    "phase": "school_exam_A",
                    "mode": "weighted_multiclass",
                    "macro_f1": cand,
                    "weighted_f1": best["exam"]["weighted_f1"],
                    "mean_rare_recall": rare,
                    "gate_thr": thr["gate_thr"],
                    "rare_boost": best["row"]["rare_boost"],
                    "per_class_f1": best["row"]["per_class_f1"],
                    "smote": False,
                }
        man_path.write_text(json.dumps(man, indent=2))
        print(f"  Updated {man_path}")

    print("  PROMOTED school-exam classifier into models/fault_classifier/")


if __name__ == "__main__":
    main()
