#!/usr/bin/env python3
"""Score the live fault classifier on a chronological network stream + loom.

Random exam papers are not time series. This script walks network rows in time
order, runs the promoted gate+head, applies sticky hysteresis (Temporal Loom),
writes ``models/temporal_persist_score.json``, and **patches** the promoted
artifacts with loom knobs + measured boost metrics.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score, recall_score

from _paths import MODELS_DIR, PROCESSED_DIR
from deca_inference import (
    DEFAULT_EXIT_K,
    DEFAULT_ENTER_K,
    apply_loom,
    loom_config_from_bundle,
    summarize_persistence,
    write_loom_into_promoted,
)
from deca_school_exam_train import RARE, feature_columns, predict_weighted_multiclass
from rebuild_unified import UNIFIED_LABELS, to_unified_label


def main() -> int:
    p = argparse.ArgumentParser(description="Temporal score + loom hysteresis")
    p.add_argument("--enter-k", type=int, default=None, help="Override enter_k (default: promoted loom)")
    p.add_argument("--exit-k", type=int, default=None, help="Override exit_k (default: promoted loom)")
    p.add_argument("--tail-frac", type=float, default=0.25, help="Score last fraction of network timeline")
    p.add_argument(
        "--no-write-promoted",
        action="store_true",
        help="Do not patch decision_thresholds.json / pickles with loom metrics",
    )
    args = p.parse_args()

    df = pd.read_parquet(PROCESSED_DIR / "deca_unified_dataset.parquet")
    if "unified_label" not in df.columns:
        df["unified_label"] = df["fault_type"].map(to_unified_label)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    feats = feature_columns(df)

    net = df[df["source"] == "network"].copy()
    cut = net.index[int(len(net) * (1.0 - args.tail_frac))]
    te = net.loc[net.index >= cut]
    print(f"Network rows={len(net):,}  temporal test tail={len(te):,}  from {cut}")

    y_raw = te["unified_label"].astype(str)
    le_classes = [c for c in UNIFIED_LABELS if c in set(df["unified_label"].astype(str))]
    le_classes += sorted(set(y_raw) - set(le_classes))
    class_to_idx = {c: i for i, c in enumerate(le_classes)}
    y = y_raw.map(class_to_idx).astype(int).values
    X = te[feats]

    bundle = joblib.load(MODELS_DIR / "fault_classifier" / "fault_classifier_xgb.pkl")
    healthy_idx = int(bundle["healthy_idx"])
    loom = loom_config_from_bundle(bundle)
    if args.enter_k is not None:
        loom["enter_k"] = int(args.enter_k)
    if args.exit_k is not None:
        loom["exit_k"] = int(args.exit_k)
    loom.setdefault("enter_k", DEFAULT_ENTER_K)
    loom.setdefault("exit_k", DEFAULT_EXIT_K)
    loom["enabled"] = True

    raw = predict_weighted_multiclass(
        bundle["gate"],
        bundle["full_clf"],
        X,
        healthy_idx=healthy_idx,
        gate_thr=float(bundle["gate_thr"]),
        class_thr={int(k): float(v) for k, v in bundle.get("class_thr", {}).items()},
    )
    sticky = apply_loom(raw, healthy_idx=healthy_idx, loom=loom)

    def pack(name, pred):
        rare_ids = [class_to_idx[c] for c in RARE if c in class_to_idx]
        rare = float(
            np.mean([recall_score(y == c, pred == c, zero_division=0) for c in rare_ids])
        ) if rare_ids else 0.0
        report = classification_report(
            y, pred, labels=list(range(len(le_classes))), target_names=le_classes,
            zero_division=0, output_dict=True,
        )
        return {
            "name": name,
            "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
            "accuracy": float(accuracy_score(y, pred)),
            "mean_rare_recall": rare,
            "per_class_f1": {c: float(report[c]["f1-score"]) for c in le_classes if c in report},
        }

    raw_m = pack("raw_frame", raw)
    sticky_m = pack("persistent", sticky)
    summary = summarize_persistence(raw, sticky, healthy_idx=healthy_idx)
    delta = float(sticky_m["macro_f1"] - raw_m["macro_f1"])

    print("\n=== Temporal Loom score (chronological network tail) ===")
    print(f"  loom enter_k={loom['enter_k']}  exit_k={loom['exit_k']}")
    for m in (raw_m, sticky_m):
        print(
            f"  {m['name']:12s}  Macro-F1={m['macro_f1']:.4f}  Acc={m['accuracy']:.4f}  "
            f"rareR={m['mean_rare_recall']:.4f}"
        )
        for c in RARE:
            if c in m["per_class_f1"]:
                print(f"    {c}: F1={m['per_class_f1'][c]:.3f}")
    print(
        f"  boost ΔMacro-F1={delta:+.4f}  frames_changed={summary['frames_changed']}  "
        f"fault frames {summary['raw_fault_frames']} → {summary['sticky_fault_frames']} "
        f"(suppressed {summary['fault_frames_suppressed']})"
    )

    out = {
        "date": datetime.now(timezone.utc).isoformat(),
        "enter_k": int(loom["enter_k"]),
        "exit_k": int(loom["exit_k"]),
        "tail_frac": args.tail_frac,
        "n_test": int(len(te)),
        "raw": raw_m,
        "persistent": sticky_m,
        "delta_macro_f1": delta,
        "persistence_summary": summary,
        "note": "Duration is not a feature — persistence is consecutive pattern agreement only",
    }
    path = MODELS_DIR / "temporal_persist_score.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {path}")

    if not args.no_write_promoted:
        thr = write_loom_into_promoted(
            loom,
            metrics={
                "date": out["date"],
                "tail_frac": args.tail_frac,
                "n_test": out["n_test"],
                "delta_macro_f1": delta,
                "raw": {
                    "macro_f1": raw_m["macro_f1"],
                    "accuracy": raw_m["accuracy"],
                    "mean_rare_recall": raw_m["mean_rare_recall"],
                    "per_class_f1": raw_m["per_class_f1"],
                },
                "persistent": {
                    "macro_f1": sticky_m["macro_f1"],
                    "accuracy": sticky_m["accuracy"],
                    "mean_rare_recall": sticky_m["mean_rare_recall"],
                    "per_class_f1": sticky_m["per_class_f1"],
                },
                "persistence_summary": summary,
            },
        )
        print(f"Patched loom into promoted artifacts ({thr})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
