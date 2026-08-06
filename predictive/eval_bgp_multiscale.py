"""Validate BGP multi-scale features on static L3 corpus (no promote / no live wiring).

Rebuilds L3 windows from series with baseline BGP rate feats vs + multi-scale,
trains a small 3A/3B XGB under group holdout, reports exact lift.

Usage:
  python -m predictive.eval_bgp_multiscale \\
    --protocol-dir data/deca/predictive/protocol/full_variants_pi_20260803T175816Z
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import GroupShuffleSplit
from xgboost import XGBClassifier

from .bgp_multiscale import (
    BASELINE_BGP_FEATS,
    WINDOW_FEAT_COLS,
    attach_bgp_multiscale,
    summarize_bgp_multiscale_window,
)
from .q2_windows import DEFAULT_STRIDE, DEFAULT_WIN, slope
from .severity_label import label_rows


def _baseline_bgp_window_feats(sl: pd.DataFrame) -> dict[str, float]:
    """Mirror q2_windows cumulative summarization for bgp_flap_count only."""
    feat: dict[str, float] = {}
    if "bgp_flap_count" not in sl.columns:
        for c in BASELINE_BGP_FEATS:
            feat[c] = 0.0
        return feat
    vals = pd.to_numeric(sl["bgp_flap_count"], errors="coerce").fillna(0.0).to_numpy()
    # positive-diff rates (match multiscale honesty; raw q2 can go negative on resets)
    d = np.diff(vals, prepend=vals[0])
    d = np.clip(d, 0.0, None)
    feat["bgp_flap_count_delta"] = float(vals[-1] - vals[0])
    feat["bgp_flap_count_slope"] = slope(vals)
    feat["bgp_flap_count_rate_mean"] = float(np.mean(d))
    feat["bgp_flap_count_rate_std"] = float(np.std(d))
    feat["bgp_flap_count_rate_max"] = float(np.max(d))
    return feat


def build_l3_window_table(
    protocol_dir: Path,
    *,
    win: int = DEFAULT_WIN,
    stride: int = DEFAULT_STRIDE,
    skip_head: int = 20,
) -> pd.DataFrame:
    rows: list[dict] = []
    for it in sorted((protocol_dir / "L3_bgp_flap").glob("iter_*")):
        series_path = it / "series.csv"
        if not series_path.exists():
            continue
        raw = pd.read_csv(series_path)
        df = attach_bgp_multiscale(raw)
        # severity on full series (10s roll — unchanged)
        sev = label_rows(df, root_label=3)
        df = df.copy()
        df["_severity"] = sev.to_numpy()
        src = f"L3_bgp_flap/{it.name}"
        start0 = max(0, skip_head)
        for start in range(start0, len(df) - win + 1, stride):
            end = start + win
            sl = df.iloc[start:end]
            # window severity = worst-of (mode of non-zero, else 0) — match train helper spirit
            sv = sl["_severity"].astype(str)
            nonzero = [x for x in sv if x != "0"]
            if not nonzero:
                continue  # skip idle windows for 3A/3B specialist eval
            # worst-of: 3B > 3A
            wsev = "3B" if "3B" in nonzero else ("3A" if "3A" in nonzero else nonzero[0])
            if wsev not in ("3A", "3B"):
                continue
            feat = {
                "source_capture": src,
                "start_idx": start,
                "end_idx": end,
                "severity": wsev,
                "y": 1 if wsev == "3B" else 0,
            }
            feat.update(_baseline_bgp_window_feats(sl))
            feat.update(summarize_bgp_multiscale_window(sl))
            rows.append(feat)
    return pd.DataFrame(rows)


def _train_eval(
    df: pd.DataFrame,
    feat_cols: list[str],
    *,
    seed: int,
    test_size: float = 0.3,
) -> dict:
    cols = [c for c in feat_cols if c in df.columns]
    X = df[cols].astype(float).fillna(0.0).to_numpy()
    y = df["y"].astype(int).to_numpy()
    groups = df["source_capture"].astype(str).to_numpy()
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    tr, te = next(gss.split(X, y, groups))
    clf = XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="logloss",
        n_jobs=4,
        random_state=seed,
        tree_method="hist",
    )
    clf.fit(X[tr], y[tr])
    pred = clf.predict(X[te])
    # also majority baseline
    maj = int(np.round(y[tr].mean()))  # if more 3B in train…
    maj = 1 if y[tr].mean() >= 0.5 else 0
    maj_pred = np.full_like(y[te], maj)
    return {
        "feature_cols": cols,
        "n_train": int(len(tr)),
        "n_holdout": int(len(te)),
        "holdout_captures": sorted(set(groups[te])),
        "exact_acc": float(accuracy_score(y[te], pred)),
        "macro_f1": float(f1_score(y[te], pred, average="macro", zero_division=0)),
        "f1_3A": float(f1_score(y[te], pred, pos_label=0, zero_division=0)),
        "f1_3B": float(f1_score(y[te], pred, pos_label=1, zero_division=0)),
        "majority_acc": float(accuracy_score(y[te], maj_pred)),
        "report": classification_report(
            y[te], pred, target_names=["3A", "3B"], zero_division=0, output_dict=True
        ),
        "y_holdout_pos_rate": float(y[te].mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--protocol-dir",
        default="data/deca/predictive/protocol/full_variants_pi_20260803T175816Z",
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    proto = Path(args.protocol_dir)
    if not proto.is_absolute():
        proto = root / proto

    df = build_l3_window_table(proto)
    logs = proto / "train_logs" / "bgp_multiscale"
    logs.mkdir(parents=True, exist_ok=True)
    df.to_csv(logs / "l3_windows_multiscale.csv", index=False)

    base = _train_eval(df, list(BASELINE_BGP_FEATS), seed=args.seed)
    multi = _train_eval(
        df, list(BASELINE_BGP_FEATS) + list(WINDOW_FEAT_COLS), seed=args.seed
    )
    # multi-only (no baseline) — is new signal sufficient alone?
    multi_only = _train_eval(df, list(WINDOW_FEAT_COLS), seed=args.seed)

    lift = float(multi["exact_acc"] - base["exact_acc"])
    if lift >= 0.03:
        verdict = "MULTISCALE_HELPS"
    elif lift <= -0.03:
        verdict = "MULTISCALE_HURTS"
    else:
        verdict = "NO_CLEAR_LIFT"

    receipt = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "protocol_dir": str(proto),
        "n_windows_3A3B": int(len(df)),
        "class_balance": df["severity"].value_counts().to_dict(),
        "baseline": {k: base[k] for k in base if k != "report"},
        "baseline_plus_multiscale": {k: multi[k] for k in multi if k != "report"},
        "multiscale_only": {k: multi_only[k] for k in multi_only if k != "report"},
        "exact_acc_lift": lift,
        "verdict": verdict,
        "note": (
            "Labels unchanged (10s roll). Features only. Group holdout on L3 captures. "
            "Not wired into FEATURE_COLS / Decide / promote."
        ),
        "cite_board": "untouched",
        "reports": {
            "baseline": base["report"],
            "baseline_plus_multiscale": multi["report"],
            "multiscale_only": multi_only["report"],
        },
    }
    (logs / "BGP_MULTISCALE_EVAL.json").write_text(json.dumps(receipt, indent=2) + "\n")
    cand = root / "data/deca/predictive/protocol_models/_candidates" / "bgp_multiscale_skel"
    cand.mkdir(parents=True, exist_ok=True)
    (cand / "BGP_MULTISCALE_EVAL.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in receipt if k != "reports"}, indent=2))


if __name__ == "__main__":
    main()
