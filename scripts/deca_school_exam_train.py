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
from deca_model_experts import ClusterAugment, MixtureOfExperts
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
    # Loom Warp‑4 labels — never treat as XGB features
    "circumstance_label",
    "event_phase",
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


def _align_to_estimator_features(estimator, X: pd.DataFrame) -> pd.DataFrame:
    """Reindex X to the exact columns an already-fitted estimator was trained on.

    Feature engineering (rebuild_unified.engineer_features) can grow the lake's
    column set over time (e.g. Tier 5 vrf_route_count_*) before a candidate
    model earns promotion. Without this, an un-promoted champion sees "unseen
    at fit time" columns and sklearn's strict feature-name validation raises —
    scoring code should silently drop what the active model doesn't know about
    and let its imputer fill anything the model expects but the frame lacks.
    """
    known = getattr(estimator, "feature_names_in_", None)
    if known is None:
        return X
    known = list(known)
    if list(X.columns) == known:
        return X
    return X.reindex(columns=known)


def predict_weighted_multiclass(gate, full_clf, X, *, healthy_idx, gate_thr, class_thr):
    preds, _ = predict_weighted_multiclass_with_confidence(
        gate, full_clf, X, healthy_idx=healthy_idx, gate_thr=gate_thr, class_thr=class_thr
    )
    return preds


def predict_weighted_multiclass_with_confidence(
    gate, full_clf, X, *, healthy_idx, gate_thr, class_thr
):
    """Frame labels plus per-frame confidence for the Temporal Loom soft streak.

    Confidence is the threshold-adjusted winning score (same ratio the argmax
    uses). It can exceed 1.0 when a class clears its decision threshold with
    room to spare — a strong single-frame signal can therefore accumulate toward
    entry faster than several weak wobbles around threshold.
    """
    p_anom = gate.predict_proba(_align_to_estimator_features(gate, X))[:, 1]
    p_full = full_clf.predict_proba(_align_to_estimator_features(full_clf, X))
    full_classes = list(full_clf.classes_)
    preds = np.full(len(p_anom), healthy_idx, dtype=int)
    conf = np.zeros(len(p_anom), dtype=np.float64)
    for i in range(len(p_anom)):
        if p_anom[i] < gate_thr:
            conf[i] = float(1.0 - p_anom[i])
            continue
        scores = [
            p_full[i, j] / max(class_thr.get(int(cid), 1.0), 1e-6)
            for j, cid in enumerate(full_classes)
        ]
        best_j = int(np.argmax(scores))
        preds[i] = int(full_classes[best_j])
        conf[i] = float(scores[best_j])
    return preds, conf


def tune_thresholds(gate, full_clf, X_val, y_val, *, healthy_idx, rare_ids):
    gate_grid = [0.20, 0.30, 0.40, 0.50, 0.60]
    thr_grid = [0.50, 0.65, 0.80, 1.00, 1.20]
    best = {"gate_thr": 0.5, "class_thr": {}, "score": -1.0, "macro_f1": -1.0}
    p_full = full_clf.predict_proba(X_val)
    full_classes = list(full_clf.classes_)
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


# Champion config = the simple booster currently promoted. Kept as an explicit
# baseline family so every "improvement" is judged head-to-head on the same paper.
PLAIN_XGB = dict(n_estimators=250, max_depth=5, learning_rate=0.08, subsample=0.9, colsample_bytree=0.9)
# Mildly regularized deeper booster (opt-in). Gentle values so rare-class splits survive.
REG_XGB = dict(
    n_estimators=350, max_depth=5, learning_rate=0.06, subsample=0.9, colsample_bytree=0.85,
    min_child_weight=2, gamma=0.1, reg_alpha=0.2, reg_lambda=1.5,
)

# family → (full-head xgb params, cluster layer?, expert xgb params or None)
FAMILY_CFG = {
    "plain": (PLAIN_XGB, False, None),
    "wm": (REG_XGB, True, None),
    "moe": (REG_XGB, True, dict(REG_XGB, n_estimators=250, max_depth=4)),
}


def make_xgb(**kw):
    """Thin XGB factory. Only the keys passed are overridden; XGBoost defaults
    otherwise (so PLAIN stays exactly the current champion, no hidden reg)."""
    params = dict(random_state=RANDOM_STATE, n_jobs=-1, eval_metric="mlogloss")
    params.update(kw)
    return XGBClassifier(**params)


def xgb_pipeline(xgb_params: dict, *, cluster: bool) -> Pipeline:
    """Impute → (KMeans cluster layer) → XGB. classes_ delegates to the xgb step."""
    steps = [("imputer", SimpleImputer(strategy="median", keep_empty_features=True))]
    if cluster:
        steps.append(("cluster", ClusterAugment(n_clusters=8, random_state=RANDOM_STATE)))
    steps.append(("xgb", make_xgb(**xgb_params)))
    return Pipeline(steps)


def build_gate(X_fit, y_fit, *, healthy_idx):
    y_bin = (y_fit != healthy_idx).astype(int)
    gate = xgb_pipeline(dict(n_estimators=200, max_depth=4, learning_rate=0.08,
                             subsample=0.9, colsample_bytree=0.9), cluster=False)
    gate.fit(
        X_fit,
        y_bin,
        xgb__sample_weight=inverse_frequency_weights(y_bin, rare_ids=set(), boost=1.0),
    )
    return gate


def build_full_head(family, X_fit, y_fit, *, healthy_idx, rare_ids, boost):
    """plain → current champion booster. wm → cluster + mild reg booster.
    moe → generalist + per-fault expert boosters, gated by a stacked meta-learner."""
    if family not in FAMILY_CFG:
        raise ValueError(f"unknown head family {family!r} (choices: {list(FAMILY_CFG)})")
    xgb_params, cluster, expert_params = FAMILY_CFG[family]
    sw = inverse_frequency_weights(y_fit, rare_ids=rare_ids, boost=boost)
    if expert_params is not None:
        fault_ids = sorted(int(c) for c in np.unique(y_fit) if int(c) != healthy_idx)
        head = MixtureOfExperts(
            base_factory=lambda: xgb_pipeline(xgb_params, cluster=cluster),
            expert_factory=lambda: xgb_pipeline(expert_params, cluster=cluster),
            expert_class_ids=fault_ids,
            random_state=RANDOM_STATE,
        )
        head.fit(X_fit, y_fit, sample_weight=sw)
        return head
    head = xgb_pipeline(xgb_params, cluster=cluster)
    head.fit(X_fit, y_fit, xgb__sample_weight=sw)
    return head


def train_phase1(
    X_fit, y_fit, X_val, y_val, *, healthy_idx, rare_ids, boost: float,
    family: str = "plain", gate=None,
):
    if gate is None:
        gate = build_gate(X_fit, y_fit, healthy_idx=healthy_idx)
    full_clf = build_full_head(
        family, X_fit, y_fit, healthy_idx=healthy_idx, rare_ids=rare_ids, boost=boost
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


def load_active_classifier() -> dict | None:
    path = MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl"
    if not path.exists():
        return None
    return joblib.load(path)


def score_active_classifier(
    bundle: dict,
    X_exam: pd.DataFrame,
    y_exam: np.ndarray,
    *,
    le_classes: list[str],
    rare_idx_list: list[int],
) -> dict | None:
    full_clf = bundle.get("full_clf")
    if full_clf is None:
        return None
    # Feature schema may have changed (e.g. multi-scale rebuild) — skip unit test
    try:
        n_expected = getattr(
            bundle["gate"].named_steps.get("imputer"), "n_features_in_", None
        )
        if n_expected is not None and X_exam.shape[1] != int(n_expected):
            print(
                f"  Active model expects {n_expected} features, lake has {X_exam.shape[1]} "
                "— skip unit test (schema drift)"
            )
            return None
        return evaluate(
            bundle["gate"],
            full_clf,
            X_exam,
            y_exam,
            healthy_idx=int(bundle["healthy_idx"]),
            gate_thr=float(bundle["gate_thr"]),
            class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
            le_classes=le_classes,
            rare_idx_list=rare_idx_list,
        )
    except ValueError as exc:
        print(f"  Active model incompatible with lake features — skip unit test ({exc})")
        return None



def promote_candidate(
    best: dict,
    *,
    baseline: float,
    class_to_idx: dict[str, int],
    cand: float,
    rare: float,
    loom: dict | None = None,
) -> None:
    from deca_inference import DEFAULT_LOOM

    le_classes = best["le_classes"]
    healthy_idx = best["healthy_idx"]
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
    loom_cfg = dict(DEFAULT_LOOM)
    if loom:
        loom_cfg.update(loom)

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
            "head_family": best.get("family", "wm"),
            "rare_boost": best["row"]["rare_boost"],
            "loom": loom_cfg,
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
            "loom": loom_cfg,
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
                "head_family": best.get("family", "wm"),
                "loom": loom_cfg,
            },
            indent=2,
        )
    )

    man_path = MODELS_DIR / "manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        man["school_exam"] = {
            "date": datetime.now(timezone.utc).isoformat(),
            "head_family": best.get("family", "wm"),
            "rare_boost": best["row"]["rare_boost"],
            "exam_macro_f1": cand,
            "exam_mean_rare_recall": rare,
            "baseline_macro_f1": baseline,
            "promoted": True,
            "loom": {
                "enabled": loom_cfg.get("enabled", True),
                "enter_k": loom_cfg.get("enter_k"),
                "exit_k": loom_cfg.get("exit_k"),
            },
        }
        for m in man.get("models", []):
            if m.get("name") == "fault_classifier_xgb":
                m["metrics"] = {
                    "phase": "school_exam_A",
                    "mode": "weighted_multiclass",
                    "head_family": best.get("family", "wm"),
                    "macro_f1": cand,
                    "weighted_f1": best["exam"]["weighted_f1"],
                    "mean_rare_recall": rare,
                    "gate_thr": thr["gate_thr"],
                    "rare_boost": best["row"]["rare_boost"],
                    "per_class_f1": best["row"]["per_class_f1"],
                    "smote": False,
                    "loom": man["school_exam"]["loom"],
                }
        man_path.write_text(json.dumps(man, indent=2))
        print(f"  Updated {man_path}")

    print("  PROMOTED school-exam classifier into models/fault_classifier/")
    print(
        f"  Loom defaults baked in: enter_k={loom_cfg.get('enter_k')} "
        f"exit_k={loom_cfg.get('exit_k')} — run deca_score_temporal.py to attach boost metrics"
    )


def run_school_exam(
    *,
    holdout_frac: float = 0.20,
    holdout_policy: str = "random",
    exam_seed: int | None = None,
    rare_boosts: list[float] | None = None,
    families: list[str] | None = None,
    auto_promote: bool = False,
    baseline_macro_f1: float | None = None,
    min_rare_recall_drop: float = 0.03,
    mode_label: str = "school_exam_A",
    unit_test_active: bool = True,
) -> dict:
    """Run full School Exam pipeline; optionally auto-promote when gate passes."""
    boosts = rare_boosts or [1.0, 1.5, 2.0, 3.0]
    fams = families or ["plain", "wm", "moe"]
    seed = exam_seed if exam_seed is not None else int(datetime.now(timezone.utc).timestamp())
    rng = np.random.default_rng(seed)

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

    blind = stratified_blind_holdout(y, df, holdout_frac, rng=rng, policy=holdout_policy)
    X_exam, y_exam = X.iloc[blind], y[blind]
    X_pool, y_pool = X.iloc[~blind], y[~blind]

    print(f"Exam paper seed={seed}  policy={holdout_policy}  (new questions each run unless --exam-seed fixed)")
    print("Exam label counts:", {le_classes[i]: int(np.sum(y_exam == i)) for i in range(len(le_classes))})

    unit_test = None
    if unit_test_active:
        active = load_active_classifier()
        if active is None:
            print("\n=== Unit test (active model) ===")
            print("  No active classifier — skip")
        else:
            scored = score_active_classifier(
                active, X_exam, y_exam, le_classes=le_classes, rare_idx_list=rare_idx_list
            )
            if scored is None:
                print("\n=== Unit test (active model) ===")
                print("  Active model is not weighted_multiclass — skip")
            else:
                unit_test = {
                    "macro_f1": scored["macro_f1"],
                    "weighted_f1": scored["weighted_f1"],
                    "mean_rare_recall": scored["mean_rare_recall"],
                    "per_class_f1": {
                        c: float(scored["report"][c]["f1-score"]) for c in le_classes
                    },
                }
                print("\n=== Unit test (active model on new paper) ===")
                print(
                    f"  Macro-F1={unit_test['macro_f1']:.4f}  "
                    f"rare-recall={unit_test['mean_rare_recall']:.4f}"
                )

    X_fit, X_val, y_fit, y_val = train_test_split(
        X_pool, y_pool, test_size=0.2, random_state=RANDOM_STATE, stratify=y_pool
    )

    baseline = load_baseline_macro(baseline_macro_f1)
    print(f"Lake rows={len(df):,}  features={len(feats)}  exam rows={len(X_exam):,}")
    print(f"Baseline Macro-F1 to beat: {baseline:.4f}")
    print(f"Rare boosts β={boosts}")
    print(f"Heads (families): {fams}  [plain=champion, wm=cluster booster, moe=cluster + per-fault experts]")
    print(f"Classes: {le_classes}")

    # Gate is family- and β-independent → train once (cluster-augmented, regularized).
    print("\n=== Teaching the anomaly gate (once) ===")
    gate = build_gate(X_fit, y_fit, healthy_idx=healthy_idx)

    results = []
    best = None

    for family in fams:
        for beta in boosts:
            print(f"\n=== Study hall  head={family}  β={beta} ===")
            _, full_clf, thr = train_phase1(
                X_fit,
                y_fit,
                X_val,
                y_val,
                healthy_idx=healthy_idx,
                rare_ids=rare_ids,
                boost=beta,
                family=family,
                gate=gate,
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
                "family": family,
                "rare_boost": beta,
                "gate_thr": thr["gate_thr"],
                "val_macro_f1": thr["macro_f1"],
                "exam_macro_f1": exam["macro_f1"],
                "exam_weighted_f1": exam["weighted_f1"],
                "exam_mean_rare_recall": exam["mean_rare_recall"],
                "per_class_f1": {c: float(exam["report"][c]["f1-score"]) for c in le_classes},
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
                "family": family,
                "le_classes": le_classes,
                "healthy_idx": healthy_idx,
                "rare_ids": list(rare_ids),
                "class_to_idx": class_to_idx,
                "feats": feats,
            }
            if best is None or exam["macro_f1"] > best["exam"]["macro_f1"]:
                best = payload

    assert best is not None
    out_dir = MODELS_DIR / "school_exam"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "weight_sweep.csv"
    pd.DataFrame(
        [
            {
                "family": r.get("family", "wm"),
                "rare_boost": r["rare_boost"],
                "exam_macro_f1": r["exam_macro_f1"],
                "exam_mean_rare_recall": r["exam_mean_rare_recall"],
                "val_macro_f1": r["val_macro_f1"],
                "gate_thr": r["gate_thr"],
            }
            for r in results
        ]
    ).to_csv(summary_path, index=False)

    cand = best["exam"]["macro_f1"]
    rare = best["exam"]["mean_rare_recall"]

    # --- Promotion gate (apples-to-apples on THIS paper) --------------------
    # The bar is the *honest* incumbent, scored on the same fresh paper — NOT
    # the stale manifest number. The honest incumbent is the champion config
    # (`plain` family) retrained on the same blind pool; the *deployed* artifact
    # is also scored (unit test) but is leakage-inflated (it trained on ~80% of
    # the lake, so today's random rows mostly leaked in), so it is reported for
    # transparency, not used as the bar. Stale manifest is a floor only.
    plain_rows = [r for r in results if r.get("family") == "plain"]
    if plain_rows:
        champ = max(plain_rows, key=lambda r: r["exam_macro_f1"])
        champ_macro = float(champ["exam_macro_f1"])
        champ_rare = float(champ["exam_mean_rare_recall"])
        gate_basis = "honest_same_paper_champion_config"
    elif unit_test is not None:
        champ_macro = float(unit_test["macro_f1"])
        champ_rare = float(unit_test["mean_rare_recall"])
        gate_basis = "active_same_paper_leakage_inflated"
    else:
        champ_macro = baseline
        champ_rare = max(r["exam_mean_rare_recall"] for r in results) - min_rare_recall_drop
        gate_basis = "manifest_baseline_cold_start"

    active_macro = float(unit_test["macro_f1"]) if unit_test else None
    active_rare = float(unit_test["mean_rare_recall"]) if unit_test else None

    bar_macro = max(champ_macro, baseline)  # never promote below the historical honest number
    rare_floor = champ_rare - min_rare_recall_drop
    gate_ok = cand >= bar_macro and rare >= rare_floor

    report = {
        "training_date": datetime.now(timezone.utc).isoformat(),
        "mode": mode_label,
        "exam_seed": seed,
        "holdout_policy": holdout_policy,
        "baseline_macro_f1": baseline,
        "holdout_frac": holdout_frac,
        "unit_test_active": unit_test,
        "best": best["row"],
        "sweep": results,
        "gate_ok": gate_ok,
        "gate": {
            "candidate_macro_f1": cand,
            "candidate_mean_rare_recall": rare,
            "basis": gate_basis,
            "bar_macro_f1": bar_macro,
            "champion_same_paper_macro_f1": champ_macro,
            "champion_same_paper_rare_recall": champ_rare,
            "active_same_paper_macro_f1": active_macro,
            "active_same_paper_rare_recall": active_rare,
            "manifest_baseline_macro_f1": baseline,
            "rare_recall_floor": rare_floor,
            "passed": gate_ok,
        },
        "anti_memorization": "fresh stratified exam draw each run unless --exam-seed is fixed",
    }
    report_path = out_dir / "latest_exam.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {summary_path}")
    print(f"Wrote {report_path}")

    print("\n=== Great Exam / promotion gate (repeated-holdout validation) ===")
    print(f"  candidate Macro-F1={cand:.4f}")
    print(
        f"  bar={bar_macro:.4f} = max(honest champion same-paper {champ_macro:.4f}, "
        f"manifest floor {baseline:.4f})   [basis={gate_basis}]"
    )
    if active_macro is not None:
        print(f"  deployed artifact (same paper, leakage-inflated)={active_macro:.4f}  [informational only]")
    print(f"  candidate rare-recall={rare:.4f}  floor≈{rare_floor:.4f}")
    print(f"  GATE: {'PASS' if gate_ok else 'FAIL'}")

    promoted = False
    action = "dry_run"
    if auto_promote:
        if gate_ok:
            promote_candidate(
                best,
                baseline=baseline,
                class_to_idx=class_to_idx,
                cand=cand,
                rare=rare,
            )
            promoted = True
            action = "promoted"
        else:
            print("  Auto-promote: gate FAIL — keeping active models/")
            action = "kept_active"
    else:
        print("  (dry run — orchestrator or --auto-promote to apply gate decision)")

    return {
        **report,
        "promoted": promoted,
        "action": action,
        "best_payload": best,
        "class_to_idx": class_to_idx,
    }


def _agg(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    return {
        "mean": float(a.mean()),
        "std": float(a.std(ddof=0)),
        "min": float(a.min()),
        "max": float(a.max()),
        "n": int(a.size),
    }


def run_seed_report(
    *,
    n_seeds: int = 5,
    families: list[str] | None = None,
    rare_boosts: list[float] | None = None,
    holdout_frac: float = 0.20,
    holdout_policy: str = "random",
    base_seed: int | None = None,
) -> dict:
    """Repeated-holdout validation across N fresh papers.

    Reports the *spread* (mean / std / min / max) of macro-F1, mean rare recall
    and per rare-class F1 — for both the honest champion config (`plain`) and the
    overall best family each paper. This answers "is the VRF/BGP gain real or
    just one lucky seed?" far more defensibly than a single number.
    """
    fams = families or ["plain", "wm", "moe"]
    boosts = rare_boosts or [1.0, 1.5, 2.0, 3.0]
    ss = np.random.default_rng(
        base_seed if base_seed is not None else int(datetime.now(timezone.utc).timestamp())
    )
    seeds = [int(ss.integers(1, 2**31 - 1)) for _ in range(n_seeds)]

    rare_names = [c for c in RARE]
    per_seed: list[dict] = []
    champ_series: dict[str, list[float]] = {"macro_f1": [], "mean_rare_recall": []}
    best_series: dict[str, list[float]] = {"macro_f1": [], "mean_rare_recall": []}
    for c in rare_names:
        champ_series[f"f1_{c}"] = []
        best_series[f"f1_{c}"] = []
    challenger_wins = 0
    gate_pass = 0

    for i, s in enumerate(seeds, 1):
        print(f"\n{'#' * 60}\n# SEED {i}/{n_seeds}  exam_seed={s}\n{'#' * 60}")
        rep = run_school_exam(
            holdout_frac=holdout_frac,
            holdout_policy=holdout_policy,
            exam_seed=s,
            rare_boosts=boosts,
            families=fams,
            auto_promote=False,
            unit_test_active=True,
            mode_label="seed_report",
        )
        sweep = rep["sweep"]
        plain_rows = [r for r in sweep if r.get("family") == "plain"]
        champ = max(plain_rows, key=lambda r: r["exam_macro_f1"]) if plain_rows else rep["best"]
        best = rep["best"]
        if best.get("family") != "plain":
            challenger_wins += 1
        if rep["gate_ok"]:
            gate_pass += 1

        champ_series["macro_f1"].append(champ["exam_macro_f1"])
        champ_series["mean_rare_recall"].append(champ["exam_mean_rare_recall"])
        best_series["macro_f1"].append(best["exam_macro_f1"])
        best_series["mean_rare_recall"].append(best["exam_mean_rare_recall"])
        for c in rare_names:
            champ_series[f"f1_{c}"].append(float(champ["per_class_f1"].get(c, 0.0)))
            best_series[f"f1_{c}"].append(float(best["per_class_f1"].get(c, 0.0)))

        per_seed.append(
            {
                "seed": s,
                "champion_family": champ.get("family", "plain"),
                "champion_macro_f1": champ["exam_macro_f1"],
                "champion_rare_f1": {c: float(champ["per_class_f1"].get(c, 0.0)) for c in rare_names},
                "best_family": best.get("family"),
                "best_macro_f1": best["exam_macro_f1"],
                "best_rare_f1": {c: float(best["per_class_f1"].get(c, 0.0)) for c in rare_names},
                "gate_ok": rep["gate_ok"],
            }
        )

    summary = {
        "champion_plain": {k: _agg(v) for k, v in champ_series.items()},
        "best_family": {k: _agg(v) for k, v in best_series.items()},
    }
    report = {
        "report_date": datetime.now(timezone.utc).isoformat(),
        "technique": "repeated holdout validation (fresh stratified paper per seed) + promotion gate",
        "n_seeds": n_seeds,
        "seeds": seeds,
        "families": fams,
        "rare_boosts": boosts,
        "holdout_frac": holdout_frac,
        "holdout_policy": holdout_policy,
        "challenger_wins_over_plain": challenger_wins,
        "gate_pass_count": gate_pass,
        "summary": summary,
        "per_seed": per_seed,
    }

    out_dir = MODELS_DIR / "school_exam"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "seed_report.json").write_text(json.dumps(report, indent=2))

    def fmt(a: dict) -> str:
        return f"{a['mean']:.3f} ± {a['std']:.3f}  [{a['min']:.3f}, {a['max']:.3f}]"

    lines = [
        "# DECA repeated-holdout validation — rare-class stability",
        "",
        f"- **When:** `{report['report_date']}`",
        f"- **Seeds:** {n_seeds} fresh stratified papers `{seeds}`",
        f"- **Families:** {fams} · β={boosts}",
        f"- **Challenger (wm/moe) beat plain on:** {challenger_wins}/{n_seeds} papers",
        f"- **Gate PASS:** {gate_pass}/{n_seeds} papers",
        "",
        "Technique: **repeated holdout validation** with an automated **promotion gate** "
        "(demo name: \"School Exam\"). Ranges below are mean ± std [min, max] across seeds.",
        "",
        "## Honest champion config (`plain`, retrained per paper)",
        "",
        "| Metric | Range across seeds |",
        "| --- | --- |",
        f"| Macro-F1 | {fmt(summary['champion_plain']['macro_f1'])} |",
        f"| Mean rare recall | {fmt(summary['champion_plain']['mean_rare_recall'])} |",
    ]
    for c in rare_names:
        lines.append(f"| {c} F1 | {fmt(summary['champion_plain'][f'f1_{c}'])} |")
    lines += [
        "",
        "## Best family per paper (challenger allowed)",
        "",
        "| Metric | Range across seeds |",
        "| --- | --- |",
        f"| Macro-F1 | {fmt(summary['best_family']['macro_f1'])} |",
        f"| Mean rare recall | {fmt(summary['best_family']['mean_rare_recall'])} |",
    ]
    for c in rare_names:
        lines.append(f"| {c} F1 | {fmt(summary['best_family'][f'f1_{c}'])} |")
    lines += [
        "",
        "## Per-seed detail",
        "",
        "| Seed | Champion Macro | Best family | Best Macro | Gate |",
        "| --- | ---: | --- | ---: | --- |",
    ]
    for r in per_seed:
        lines.append(
            f"| {r['seed']} | {r['champion_macro_f1']:.3f} | {r['best_family']} | "
            f"{r['best_macro_f1']:.3f} | {'PASS' if r['gate_ok'] else 'FAIL'} |"
        )
    lines += [
        "",
        "> Reading: a wide std or low min on a rare class means that class's F1 is "
        "**seed-sensitive (noise)**; a tight band means the number is **real**. "
        "Promote only when the challenger wins consistently, not on one lucky paper.",
        "",
    ]
    (out_dir / "seed_report.md").write_text("\n".join(lines))

    print(f"\n{'=' * 60}")
    print("REPEATED-HOLDOUT SUMMARY")
    print(f"{'=' * 60}")
    print(f"  champion plain  Macro-F1 : {fmt(summary['champion_plain']['macro_f1'])}")
    for c in rare_names:
        print(f"  champion plain  {c} F1 : {fmt(summary['champion_plain'][f'f1_{c}'])}")
    print(f"  challenger beat plain on {challenger_wins}/{n_seeds} papers; gate PASS {gate_pass}/{n_seeds}")
    print(f"  Wrote {out_dir / 'seed_report.md'}")
    return report


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
    parser.add_argument(
        "--families",
        type=str,
        default="plain,wm,moe",
        help="Head families: plain=champion booster, wm=cluster booster, moe=cluster + per-fault experts",
    )
    parser.add_argument(
        "--auto-promote",
        "--promote",
        dest="auto_promote",
        action="store_true",
        help="Apply gate decision: promote if PASS, else keep active models",
    )
    parser.add_argument("--baseline-macro-f1", type=float, default=None)
    parser.add_argument(
        "--min-rare-recall-drop",
        type=float,
        default=0.03,
        help="Allow candidate mean rare recall to be at most this much below sweep best",
    )
    parser.add_argument(
        "--skip-unit-test",
        action="store_true",
        help="Skip scoring the active classifier on the new exam paper",
    )
    parser.add_argument(
        "--report-seeds",
        type=int,
        default=0,
        help="Repeated-holdout validation: run N fresh papers and report rare-class spread (no promote)",
    )
    args = parser.parse_args()
    boosts = [float(x) for x in args.rare_boosts.split(",") if x.strip()]
    fams = [x.strip() for x in args.families.split(",") if x.strip()]
    if args.report_seeds and args.report_seeds > 1:
        run_seed_report(
            n_seeds=args.report_seeds,
            families=fams,
            rare_boosts=boosts,
            holdout_frac=args.holdout_frac,
            holdout_policy=args.holdout_policy,
            base_seed=args.exam_seed,
        )
        return
    run_school_exam(
        holdout_frac=args.holdout_frac,
        holdout_policy=args.holdout_policy,
        exam_seed=args.exam_seed,
        rare_boosts=boosts,
        families=fams,
        auto_promote=args.auto_promote,
        baseline_macro_f1=args.baseline_macro_f1,
        min_rare_recall_drop=args.min_rare_recall_drop,
        unit_test_active=not args.skip_unit_test,
    )


if __name__ == "__main__":
    main()
