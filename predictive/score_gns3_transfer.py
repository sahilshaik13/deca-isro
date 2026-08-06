#!/usr/bin/env python3
"""Score GNS3 transfer for Q2 (no remaps — competition path).

Default model is the per-fabric GNS3 d3 route (cite ~0.721). Pass
``--q2-model`` explicitly to score Pi d2 on the twin for A/B.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import accuracy_score

from .q2_fabric_route import GNS3_Q2_DEFAULT, resolve_q2_model


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--q2-model",
        default="",
        help="override model (default: fabric-routed GNS3 d3)",
    )
    ap.add_argument(
        "--windows",
        default="data/deca/predictive/protocol_gns3/full_variants_gns3_20260803T175816Z/dataset/q2_windows.csv",
    )
    ap.add_argument("--out-json", default="")
    args = ap.parse_args()

    model_path = (
        Path(args.q2_model)
        if args.q2_model
        else resolve_q2_model(fabric="gns3", q2_model_gns3=GNS3_Q2_DEFAULT)
    )
    bundle = joblib.load(model_path)
    model = bundle["model"]
    feat = bundle["feature_cols"]
    r2c = bundle.get("raw_to_contig") or {}

    df = pd.read_csv(args.windows)
    df = df[~df["source_capture"].astype(str).str.contains("chaos", case=False)].copy()
    X = df.reindex(columns=feat).astype(float).fillna(0.0)
    pred = model.predict(X)
    y = df["severity_id"].astype(int).map(lambda v: r2c.get(int(v), -1))
    mask = y.to_numpy() >= 0
    acc = float(accuracy_score(y[mask], pred[mask]))
    out = {
        "model": str(model_path),
        "windows": args.windows,
        "gns3_transfer_cite_style": acc,
        "n": int(mask.sum()),
        "note": "cite-style excludes severity_ids absent from model contig (e.g. 3A). No remaps.",
    }
    text = json.dumps(out, indent=2) + "\n"
    if args.out_json:
        Path(args.out_json).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
