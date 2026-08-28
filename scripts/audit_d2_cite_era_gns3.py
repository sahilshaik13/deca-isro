"""GNS3 transfer + note raw_to_contig for cite-era d2."""
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

MODEL = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/q2_fix_sweep/d2_e100_l6_mcw3/q2_severity.joblib"
GNS = ROOT / "data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/dataset/q2_windows.csv"
CITE = 0.6546600630346691
CITE_F1 = 0.5741334412131454


def main():
    print("xgboost", __import__("xgboost").__version__)
    b = joblib.load(MODEL)
    print("raw_to_contig", b.get("raw_to_contig"))
    print("n_feat", len(b["feature_cols"]))
    df = pd.read_csv(GNS)
    df = df[~df["source_capture"].astype(str).str.contains("chaos", case=False)].copy()
    r2c = b.get("raw_to_contig") or {}
    feat = b["feature_cols"]
    X = df.reindex(columns=feat).astype(float).fillna(0.0)
    pred = np.asarray(b["model"].predict(X.to_numpy()))
    y = df["severity_id"].astype(int).map(lambda v: r2c.get(int(v), -1))
    mask = y.to_numpy() >= 0
    acc = float(accuracy_score(y[mask], pred[mask]))
    labels = sorted(set(y[mask].tolist()) | set(pred[mask].tolist()))
    mf1 = float(f1_score(y[mask], pred[mask], average="macro", labels=labels, zero_division=0))
    acc_all = float(accuracy_score(df["severity_id"].astype(int), pred))
    out = {
        "n_no_chaos": int(len(df)),
        "n_mask": int(mask.sum()),
        "missing_feat": [c for c in feat if c not in df.columns],
        "acc_cite_style": acc,
        "macro_f1": mf1,
        "acc_unmapped_raw": acc_all,
        "cite_acc": CITE,
        "cite_f1": CITE_F1,
        "matches_acc": abs(acc - CITE) < 1e-12,
        "matches_f1": abs(mf1 - CITE_F1) < 1e-9,
        "k": int((y[mask].to_numpy() == pred[mask]).sum()),
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
