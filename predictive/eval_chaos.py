"""Evaluate Q1/Q2 on a chaos capture (never used for training).

Reports:
  - Q2 severity/root predictions vs schedule-derived ground truth
  - Optional Q1 ETA MAE when rain phases present and SLA breached
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .infer_q1_q2_live import window_features
from .preprocess import align_1hz, ema_smooth
from .q1_windows import build_windows as build_q1
from .q2_windows import FEATURE_COLS, build_windows as build_q2
from .severity_label import (
    ID_TO_SEVERITY,
    RED_SEVERITIES,
    SEVERITY_TO_ID,
    SEVERITY_TO_ROOT,
    stamp_series,
    window_severity,
)


def schedule_root_at(t_rel: float, schedule: dict) -> int:
    """Map relative second → expected root fault (0 if healthy / ambiguous)."""
    for ph in schedule.get("phases", []):
        if ph["t_start"] <= t_rel < ph["t_end"]:
            faults = ph.get("faults") or []
            if not faults:
                return 0
            if "bgp_flap" in faults and "rain_fade" not in faults:
                return 3
            if "cpu_stress" in faults and "rain_fade" in faults:
                return 1  # physical dominates for latency gate; note multi-fault
            if "rain_fade" in faults:
                return 1
            if "loss_progression" in faults:
                return 4
            if "util_congestion" in faults:
                return 5
            if "cpu_stress" in faults:
                return 2
            if "bgp_flap" in faults:
                return 3
            return 0
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chaos-dir", required=True)
    ap.add_argument("--q2-model", required=True)
    ap.add_argument("--q1-model", default="")
    ap.add_argument("--q1-scaler", default="")
    ap.add_argument("--q1-loss-model", default="", help="optional loss-TTI LSTM (.keras)")
    ap.add_argument("--q1-loss-scaler", default="", help="optional loss-TTI scaler.npz")
    ap.add_argument("--loss-sla-pct", type=float, default=2.0)
    ap.add_argument("--ema-span", type=int, default=5)
    args = ap.parse_args()

    chaos = Path(args.chaos_dir).resolve()
    series = pd.read_csv(chaos / "series.csv")
    schedule = json.loads((chaos / "chaos_schedule.json").read_text())
    df = ema_smooth(align_1hz(series), span=args.ema_span)
    t0 = int(df["ts_unix"].iloc[0])
    df["t_rel"] = df["ts_unix"].astype(int) - t0

    # Ground-truth root from schedule; severity from metrics under that root
    roots = [schedule_root_at(float(t), schedule) for t in df["t_rel"]]
    df["gt_root"] = roots
    sev_rows = []
    for i, lab in enumerate(roots):
        row_df = df.iloc[[i]]
        sev_rows.append(stamp_series(row_df, int(lab))["severity"].iloc[0])
    df["gt_severity"] = sev_rows

    win_df, _ = build_q2(df, label=0, skip_head=0)  # label unused; we overwrite
    if win_df.empty:
        raise SystemExit("no windows")

    bundle = joblib.load(args.q2_model)
    model = bundle["model"]
    feat_cols = bundle["feature_cols"]
    mode = bundle.get("mode", "root")
    id_to_sev = bundle.get("id_to_severity") or ID_TO_SEVERITY

    y_true = []
    y_pred = []
    red_pred = 0
    red_true = 0
    for _, row in win_df.iterrows():
        sl = df.iloc[int(row["start_idx"]) : int(row["end_idx"])]
        gt_sev = window_severity(sl["gt_severity"].astype(str).tolist())
        gt_root = int(sl["gt_root"].mode().iloc[0]) if len(sl) else 0
        buf = [
            {c: float(r[c]) if c in sl.columns and pd.notna(r[c]) else 0.0 for c in FEATURE_COLS}
            for _, r in sl.iterrows()
        ]
        feats = window_features(buf, feat_cols)
        X = np.asarray([[feats.get(c, 0.0) for c in feat_cols]], dtype=np.float32)
        pred_id = int(model.predict(X)[0])
        if mode == "severity":
            pred_sev = id_to_sev.get(pred_id, "0")
            pred_root = SEVERITY_TO_ROOT.get(pred_sev, 0)
            y_true.append(SEVERITY_TO_ID.get(gt_sev, 0))
            y_pred.append(pred_id)
            if gt_sev in RED_SEVERITIES:
                red_true += 1
            if pred_sev in RED_SEVERITIES:
                red_pred += 1
        else:
            y_true.append(gt_root)
            y_pred.append(pred_id)

    y_true_a = np.asarray(y_true)
    y_pred_a = np.asarray(y_pred)
    acc = float((y_true_a == y_pred_a).mean()) if len(y_true_a) else 0.0

    # Simple per-class recall for roots if severity mode collapse
    result = {
        "chaos_dir": str(chaos),
        "mode": mode,
        "n_windows": int(len(win_df)),
        "accuracy": acc,
        "red_severity_true_windows": red_true,
        "red_severity_pred_windows": red_pred,
    }

    if args.q1_model and args.q1_scaler:
        try:
            from tensorflow import keras

            q1 = keras.models.load_model(args.q1_model)
            sc = np.load(args.q1_scaler, allow_pickle=True)
            mean, std = sc["mean"], sc["std"]
            q1_cols = [str(c) for c in sc["feature_cols"].tolist()]
            q1w, meta = build_q1(df)
            usable = q1w[q1w["label_usable"] == True] if not q1w.empty else q1w  # noqa: E712
            errs = []
            for _, row in usable.iterrows():
                seq = json.loads(row["seq_json"]) if isinstance(row.get("seq_json"), str) else None
                if seq is None:
                    continue
                X = np.asarray([seq], dtype=np.float32)
                X = (X - mean) / std
                pred = float(q1.predict(X, verbose=0)[0][0])
                errs.append(abs(pred - float(row["eta_seconds"])))
            result["q1_n"] = len(errs)
            result["q1_mae"] = float(np.mean(errs)) if errs else None
            result["q1_breach_idx"] = meta.get("breach_idx")
        except Exception as exc:  # noqa: BLE001
            result["q1_error"] = str(exc)

    if args.q1_loss_model and args.q1_loss_scaler:
        try:
            from tensorflow import keras
            from .q1_windows import LOSS_COL, build_windows as build_q1_loss

            q1l = keras.models.load_model(args.q1_loss_model)
            sc = np.load(args.q1_loss_scaler, allow_pickle=True)
            mean, std = sc["mean"], sc["std"]
            q1w, meta = build_q1_loss(
                df, sla=float(args.loss_sla_pct), target_col=LOSS_COL
            )
            usable = q1w[q1w["label_usable"] == True] if not q1w.empty else q1w  # noqa: E712
            errs = []
            for _, row in usable.iterrows():
                seq = json.loads(row["seq_json"]) if isinstance(row.get("seq_json"), str) else None
                if seq is None:
                    continue
                X = np.asarray([seq], dtype=np.float32)
                X = (X - mean) / std
                pred = float(q1l.predict(X, verbose=0)[0][0])
                errs.append(abs(pred - float(row["eta_seconds"])))
            result["q1_loss_n"] = len(errs)
            result["q1_loss_mae"] = float(np.mean(errs)) if errs else None
            result["q1_loss_breach_idx"] = meta.get("breach_idx")
            result["q1_loss_sla_pct"] = float(args.loss_sla_pct)
            # crude lead-time: mean true ETA on usable windows
            if not usable.empty:
                result["q1_loss_mean_lead_s"] = float(usable["eta_seconds"].mean())
        except Exception as exc:  # noqa: BLE001
            result["q1_loss_error"] = str(exc)

    out = chaos / "eval_chaos.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
