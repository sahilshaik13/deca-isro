"""Score presence quieter-leg recall vs single-label Q2 drowning on COMPOUND.

Uses frozen Q2 severity joblib read-only for drowning baseline.
Presence bundle from train_presence_xgb.

Usage:
  python -m predictive.eval_presence_slices \\
    --protocol-dir data/deca/predictive/protocol/full_variants_pi_20260803T175816Z \\
    --presence-bundle data/deca/predictive/protocol_models/_candidates/presence_skel_*/presence_bundle.joblib
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .presence_label import (
    PRESENCE_COLS,
    attach_presence_labels,
    presence_col,
    quieter_root_for_compound,
)


def _predict_presence(bundle: dict, df: pd.DataFrame) -> pd.DataFrame:
    feat_cols = bundle["feature_cols"]
    X = df.reindex(columns=feat_cols, fill_value=0.0).astype(float).fillna(0.0).to_numpy()
    thr = float(bundle.get("threshold", 0.5))
    out = pd.DataFrame(index=df.index)
    for col in bundle["presence_cols"]:
        clf = bundle["models"].get(col)
        if clf is None:
            out[col] = 0
            continue
        proba = clf.predict_proba(X)[:, 1]
        out[col] = (proba >= thr).astype(int)
    return out


def _predict_q2_root(sev_bundle: dict, df: pd.DataFrame) -> np.ndarray:
    from .severity_label import ID_TO_SEVERITY, SEVERITY_TO_ROOT as S2R

    feat_cols = sev_bundle["feature_cols"]
    X = df.reindex(columns=feat_cols, fill_value=0.0).astype(float).fillna(0.0).to_numpy()
    model = sev_bundle["model"]
    contig = model.predict(X)
    id_to_sev = sev_bundle.get("id_to_severity") or {}
    c2r = sev_bundle.get("contig_to_raw") or {}
    sev_to_root = sev_bundle.get("severity_to_root") or dict(S2R)
    roots = []
    for pred_id in contig:
        pred_id = int(pred_id)
        pred_sev = id_to_sev.get(pred_id, id_to_sev.get(str(pred_id), "0"))
        if c2r:
            raw_id = int(c2r.get(pred_id, c2r.get(str(pred_id), pred_id)))
            pred_sev = ID_TO_SEVERITY.get(raw_id, pred_sev)
        if not isinstance(pred_sev, str):
            pred_sev = ID_TO_SEVERITY.get(int(pred_sev), "0")
        roots.append(int(sev_to_root.get(pred_sev, S2R.get(pred_sev, 0))))
    return np.asarray(roots, dtype=int)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--protocol-dir",
        default="data/deca/predictive/protocol/full_variants_pi_20260803T175816Z",
    )
    ap.add_argument("--presence-bundle", required=True)
    ap.add_argument(
        "--q2-bundle",
        default="data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib",
    )
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    proto = Path(args.protocol_dir)
    if not proto.is_absolute():
        proto = root / proto
    p_bundle_path = Path(args.presence_bundle)
    if not p_bundle_path.is_absolute():
        p_bundle_path = root / p_bundle_path
    q2_path = Path(args.q2_bundle)
    if not q2_path.is_absolute():
        q2_path = root / q2_path

    presence = joblib.load(p_bundle_path)
    q2 = joblib.load(q2_path)

    df = attach_presence_labels(pd.read_csv(proto / "dataset" / "q2_windows.csv"), proto)
    # Restrict to holdout captures from training receipt when available
    hold = set(presence.get("holdout_captures") or [])
    if hold:
        df = df[df["source_capture"].astype(str).isin(hold)].copy()

    pred_p = _predict_presence(presence, df)
    q2_root = _predict_q2_root(q2, df)

    slices = []
    for lab in sorted((proto / "COMPOUND").glob("iter_*/label.json")):
        meta = quieter_root_for_compound(proto, lab.parent.name)
        src = meta["source_capture"]
        mask = df["source_capture"].astype(str).eq(src)
        if not mask.any():
            slices.append({**meta, "n": 0, "skipped": "not_in_eval_split"})
            continue
        quiet = int(meta["quieter_root"])
        dom = int(meta["dominant_root"])
        idx = np.where(mask.to_numpy())[0]
        # presence quieter-leg recall
        pcol = presence_col(quiet) if quiet else None
        if pcol and pcol in pred_p.columns:
            presence_hit = float(pred_p.iloc[idx][pcol].mean())
        else:
            presence_hit = float("nan")
        # Q2 drowning: argmax root == quieter?
        q2_quiet_hit = float((q2_root[idx] == quiet).mean()) if quiet else float("nan")
        q2_dom_hit = float((q2_root[idx] == dom).mean()) if dom else float("nan")
        slices.append(
            {
                **meta,
                "n": int(mask.sum()),
                "presence_quieter_recall": presence_hit,
                "q2_quieter_recall": q2_quiet_hit,
                "q2_dominant_recall": q2_dom_hit,
                "delta_presence_minus_q2_quiet": (
                    None
                    if presence_hit != presence_hit or q2_quiet_hit != q2_quiet_hit
                    else presence_hit - q2_quiet_hit
                ),
            }
        )

    scored = [s for s in slices if s.get("n", 0) > 0]
    mean_p = float(np.nanmean([s["presence_quieter_recall"] for s in scored])) if scored else 0.0
    mean_q = float(np.nanmean([s["q2_quieter_recall"] for s in scored])) if scored else 0.0

    receipt = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_dir": str(proto),
        "presence_bundle": str(p_bundle_path),
        "q2_bundle_readonly": str(q2_path),
        "eval_split": "presence holdout captures" if hold else "all windows",
        "n_compound_iters_scored": len(scored),
        "mean_presence_quieter_recall": mean_p,
        "mean_q2_quieter_recall": mean_q,
        "mean_lift_presence_over_q2": mean_p - mean_q,
        "slices": slices,
        "verdict": (
            "PRESENCE_HELPS_QUIET_LEG"
            if mean_p > mean_q + 0.05
            else (
                "NO_CLEAR_LIFT"
                if abs(mean_p - mean_q) <= 0.05
                else "Q2_STILL_BETTER_ON_THIS_SPLIT"
            )
        ),
        "cite_board": "untouched",
        "live_wiring": "none — skeleton only",
    }

    out = Path(args.out) if args.out else (
        proto / "train_logs" / "presence_skel" / "SLICE_EVAL.json"
    )
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    # also beside bundle
    side = p_bundle_path.parent / "SLICE_EVAL.json"
    side.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in receipt if k != "slices"}, indent=2))
    print("--- per-iter ---")
    for s in slices:
        if s.get("n", 0) == 0:
            print(f"  {s['iter']}: skipped ({s.get('skipped')})")
            continue
        print(
            f"  {s['iter']}: quiet=L{s['quieter_root']} dom=L{s['dominant_root']} "
            f"presence={s['presence_quieter_recall']:.3f} "
            f"q2_quiet={s['q2_quieter_recall']:.3f} q2_dom={s['q2_dominant_recall']:.3f} n={s['n']}"
        )


if __name__ == "__main__":
    main()
