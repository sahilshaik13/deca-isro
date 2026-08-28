"""Audit frozen d2 joblib vs cite 0.884 — dump versions, warning, features, split."""
from __future__ import annotations

import hashlib
import json
import sys
import warnings
from pathlib import Path

ROOT = Path(r"e:\deca-isro")
sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost

MODEL = ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
SCORE = json.loads(
    (ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/score.json").read_text()
)
PRE = (
    ROOT
    / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/bgp_roll_retrain/q2_windows_pre_bgp_roll.csv"
)
CUR = (
    ROOT
    / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/dataset/q2_windows.csv"
)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def score_df(bundle, df, name):
    from sklearn.metrics import accuracy_score, f1_score

    model = bundle["model"]
    feat = bundle["feature_cols"]
    r2c = bundle.get("raw_to_contig") or {}
    X = df.reindex(columns=feat).astype(float).fillna(0.0)
    missing = [c for c in feat if c not in df.columns]
    extra = [c for c in df.columns if c not in feat and pd.api.types.is_numeric_dtype(df[c])]
    pred = np.asarray(model.predict(X.to_numpy()))
    if "severity_id" in df.columns:
        y_raw = df["severity_id"].astype(int).to_numpy()
    else:
        y_raw = df["severity"].map(lambda s: int(s) if str(s).isdigit() else -1).to_numpy()
    y_contig = np.array([int(r2c.get(int(v), r2c.get(str(int(v)), -1))) for v in y_raw])
    mask = y_contig >= 0
    acc_c = float(accuracy_score(y_contig[mask], pred[mask])) if mask.any() else float("nan")
    # contig vs raw (the 0.101 bug): compare pred contig ids to y_raw
    acc_bug = float((pred == y_raw).mean()) if len(pred) else float("nan")
    return {
        "name": name,
        "n": int(len(df)),
        "n_masked": int(mask.sum()),
        "n_feat_expected": len(feat),
        "n_feat_present": int(sum(c in df.columns for c in feat)),
        "missing_feat": missing,
        "n_numeric_extra": len(extra),
        "acc_contig_mapped": acc_c,
        "acc_pred_vs_raw_NO_MAP": acc_bug,
        "k_contig": int((y_contig[mask] == pred[mask]).sum()) if mask.any() else 0,
        "pred_unique": sorted(set(pred.tolist())),
        "y_contig_unique": sorted(set(y_contig[mask].tolist())),
        "fillna_cells": int(df.reindex(columns=feat).isna().sum().sum()) if feat else 0,
    }


def main():
    print("=== VERSIONS (this process) ===")
    print("xgboost.__version__ =", xgboost.__version__)
    print("sklearn.__version__ =", sklearn.__version__)
    print("joblib", joblib.__version__)
    print("python", sys.version)

    print("\n=== PICKLE WARNING (verbatim captured) ===")
    caught = []
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        bundle = joblib.load(MODEL)
        for item in w:
            caught.append(
                {
                    "category": item.category.__name__,
                    "message": str(item.message),
                }
            )
    print("n_warnings", len(caught))
    for i, c in enumerate(caught):
        print("--- warning", i, c["category"], "---")
        print(c["message"])
        print("--- end warning", i, "---")

    print("\n=== BUNDLE KEYS ===")
    print(sorted(bundle.keys()))
    for k in (
        "backend",
        "mode",
        "split_mode",
        "feature_cols",
        "raw_to_contig",
        "contig_to_raw",
        "id_to_severity",
        "class_ids",
    ):
        v = bundle.get(k)
        if k == "feature_cols":
            print("n_feature_cols", len(v) if v else None)
            print("feature_cols", v)
        else:
            print(k, v)

    model = bundle["model"]
    print("model type", type(model))
    print("n_estimators_", getattr(model, "n_estimators", None), "max_depth", getattr(model, "max_depth", None))
    booster = None
    try:
        booster = model.get_booster()
        print("booster.attributes", booster.attributes())
        cfg = json.loads(booster.save_config())
        print("booster learner/objective snapshot keys", list(cfg.keys())[:20])
        # version often in config
        print("json snippet learner", json.dumps(cfg.get("learner", {}) if isinstance(cfg.get("learner"), dict) else str(cfg)[:500])[:2000])
    except Exception as exc:
        print("booster inspect error", type(exc).__name__, exc)

    print("\n=== ARTIFACT TIMESTAMPS / HASHES ===")
    files = [
        MODEL,
        MODEL.parent / "score.json",
        MODEL.parent / "train_metrics.json",
        PRE,
        CUR,
        ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/ALL_MODEL_SCORES.json",
    ]
    for p in files:
        if not p.exists():
            print("MISSING", p)
            continue
        st = p.stat()
        print(
            json.dumps(
                {
                    "path": str(p),
                    "bytes": st.st_size,
                    "mtime": st.st_mtime,
                    "sha256": sha256(p) if p.suffix in {".json", ".csv", ".joblib", ".txt"} or True else None,
                }
            )
        )

    groups = set(SCORE["holdout_groups"])
    print("\n=== HOLDOUT GROUPS FROM score.json ===")
    print(SCORE["holdout_groups"])

    for label, path in (("pre_bgp_roll", PRE), ("current_dataset_q2_windows", CUR)):
        if not path.exists():
            print("missing csv", path)
            continue
        df = pd.read_csv(path)
        print(f"\n=== CSV {label} ===")
        print("n_rows", len(df), "n_cols", len(df.columns))
        print("columns", list(df.columns)[:40], "... total", len(df.columns))
        if "source_capture" in df.columns:
            te = df[df["source_capture"].astype(str).isin(groups)]
            print("holdout_n", len(te), "groups_found", sorted(te["source_capture"].astype(str).unique().tolist()))
            missing_g = sorted(groups - set(df["source_capture"].astype(str)))
            print("groups_missing_from_csv", missing_g)
            print("score", score_df(bundle, te, label + "_holdout"))
        print("full_csv_score", score_df(bundle, df, label + "_all"))

    # GNS3
    gns = ROOT / "data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/dataset/q2_windows.csv"
    if gns.exists():
        gdf = pd.read_csv(gns)
        gdf2 = gdf[~gdf["source_capture"].astype(str).str.contains("chaos", case=False)].copy()
        print("\n=== GNS3 non-chaos ===")
        print("n", len(gdf2))
        print(score_df(bundle, gdf2, "gns3_no_chaos"))
        r2c = bundle.get("raw_to_contig") or {}
        y = gdf2["severity_id"].astype(int).map(lambda v: r2c.get(int(v), -1))
        mask = y.to_numpy() >= 0
        print("cite_style_n_mask", int(mask.sum()))
        print(score_df(bundle, gdf2.loc[mask.values], "gns3_masked"))

    out = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci/d2_repro_audit.json"
    print("\ndone dump to stdout; writing summary path", out)


if __name__ == "__main__":
    main()
