"""Score candidate joblibs on cite holdout (pre_bgp_roll + score.json groups)."""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(r"e:\deca-isro")
sys.path.insert(0, str(ROOT))
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score

warnings.filterwarnings("ignore")

SCORE = json.loads(
    (ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/score.json").read_text()
)
PRE = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
GROUPS = set(SCORE["holdout_groups"])
CITE = 0.8836565096952909

MODELS = [
    ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_fix_sweep/d2_e100_l6_mcw3/q2_severity.joblib",
    ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_form_sweep_current_abs/d2_e100_l6_mcw3/q2_severity.joblib",
    ROOT / "data/deca/predictive/protocol_models/_candidates/util_clean_retrain_20260806T093000Z/d2_e100_l6_mcw3/q2_severity.joblib",
    ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib",
    ROOT / "data/deca/predictive/protocol_models/archive_20260804T075114Z/xgb_q2_sev_unified/q2_severity.joblib",
]


def eval_model(path, df_te):
    b = joblib.load(path)
    feat = b["feature_cols"]
    r2c = b.get("raw_to_contig") or {}
    m = b["model"]
    X = df_te.reindex(columns=feat).astype(float).fillna(0.0).to_numpy()
    pred = np.asarray(m.predict(X))
    y_raw = df_te["severity_id"].astype(int).to_numpy()
    y_c = np.array([int(r2c.get(int(v), r2c.get(str(int(v)), -1))) for v in y_raw])
    mask = y_c >= 0
    acc = float(accuracy_score(y_c[mask], pred[mask])) if mask.any() else float("nan")
    # 0.101-style: pred contig vs raw ids
    acc_bug = float((pred == y_raw).mean())
    labels = sorted(set(y_c[mask].tolist()) | set(pred[mask].tolist()))
    mf1 = float(f1_score(y_c[mask], pred[mask], average="macro", labels=labels, zero_division=0))
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "mtime": path.stat().st_mtime,
        "split_mode": b.get("split_mode"),
        "n_feat": len(feat),
        "max_depth": getattr(m, "max_depth", None),
        "n_estimators": getattr(m, "n_estimators", None),
        "reg_lambda": getattr(m, "reg_lambda", None),
        "min_child_weight": getattr(m, "min_child_weight", None),
        "learning_rate": getattr(m, "learning_rate", None),
        "n_holdout": int(mask.sum()),
        "missing_feat": [c for c in feat if c not in df_te.columns],
        "acc_contig": acc,
        "acc_no_map_bugpath": acc_bug,
        "macro_f1": mf1,
        "delta_vs_cite": acc - CITE,
        "matches_cite": abs(acc - CITE) < 1e-12,
        "raw_to_contig": b.get("raw_to_contig"),
        "holdout_groups_in_bundle": b.get("holdout_groups") if "holdout_groups" not in b else b.get("holdout_groups"),
    }


def main():
    df = pd.read_csv(PRE)
    te = df[df["source_capture"].astype(str).isin(GROUPS)].copy()
    print("holdout n", len(te), "xgboost", __import__("xgboost").__version__)
    out = []
    for p in MODELS:
        if not p.exists():
            out.append({"path": str(p), "error": "missing"})
            continue
        try:
            r = eval_model(p, te)
        except Exception as exc:
            r = {"path": str(p), "error": f"{type(exc).__name__}: {exc}"}
        out.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "raw_to_contig"}, default=str))
    dest = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci/d2_candidate_holdout_scores.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
