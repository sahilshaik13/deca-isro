"""Verify restored live d2 joblib reproduces cite holdout exactly."""
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

CITE = 0.8836565096952909
CITE_F1 = 0.7962964694531476


def main():
    import sklearn
    import xgboost

    live = ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
    score = json.loads((live.parent / "score.json").read_text())
    groups = set(score["holdout_groups"])
    csv = (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
    )
    df = pd.read_csv(csv)
    te = df[df["source_capture"].astype(str).isin(groups)].copy()
    caught = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        b = joblib.load(live)
        caught = [str(i.message) for i in w]
    m = b["model"]
    feat = b["feature_cols"]
    r2c = b.get("raw_to_contig") or {}
    X = te.reindex(columns=feat).astype(float).fillna(0.0).to_numpy()
    pred = np.asarray(m.predict(X))
    y_raw = te["severity_id"].astype(int).to_numpy()
    y_c = np.array([int(r2c.get(int(v), -1)) for v in y_raw])
    mask = y_c >= 0
    acc = float(accuracy_score(y_c[mask], pred[mask]))
    labels = sorted(set(y_c[mask].tolist()) | set(pred[mask].tolist()))
    mf1 = float(f1_score(y_c[mask], pred[mask], average="macro", labels=labels, zero_division=0))
    out = {
        "xgboost": xgboost.__version__,
        "sklearn": sklearn.__version__,
        "n_warnings": len(caught),
        "warnings": caught,
        "n": int(mask.sum()),
        "k": int((y_c[mask] == pred[mask]).sum()),
        "accuracy": acc,
        "macro_f1": mf1,
        "n_feat": len(feat),
        "split_mode": b.get("split_mode"),
        "max_depth": getattr(m, "max_depth", None),
        "n_estimators": getattr(m, "n_estimators", None),
        "reg_lambda": getattr(m, "reg_lambda", None),
        "min_child_weight": getattr(m, "min_child_weight", None),
        "learning_rate": getattr(m, "learning_rate", None),
        "missing_feat": [c for c in feat if c not in te.columns],
        "pass_acc": abs(acc - CITE) < 1e-12,
        "pass_f1": abs(mf1 - CITE_F1) < 1e-12,
        "pass_hparams": (
            getattr(m, "max_depth", None) == 2
            and getattr(m, "n_estimators", None) == 100
            and float(getattr(m, "reg_lambda", 0)) == 6.0
            and float(getattr(m, "min_child_weight", 0)) == 3.0
            and abs(float(getattr(m, "learning_rate", 0)) - 0.06) < 1e-9
            and len(feat) == 97
            and b.get("split_mode") == "group_holdout"
        ),
    }
    dest = (
        ROOT
        / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/RESTORE_VERIFY.json"
    )
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print("PASS" if out["pass_acc"] and out["pass_f1"] and out["pass_hparams"] else "FAIL")


if __name__ == "__main__":
    main()
