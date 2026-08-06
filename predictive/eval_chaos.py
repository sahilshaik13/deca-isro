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

from .bgp_specialist import refine_3a_3b
from .fabric_baseline import apply_idle_to_sample, apply_util_ceiling_sample
from .infer_q1_q2_live import window_features
from .preprocess import align_1hz, ema_smooth
from .q1_windows import build_windows as build_q1
from .q2_windows import FEATURE_COLS, build_windows as build_q2
from .severity_label import (
    ID_TO_SEVERITY,
    RED_SEVERITIES,
    SEVERITY_TO_ID,
    SEVERITY_TO_ROOT,
    label_rows,
    window_severity,
)
from .util_specialist import refine_util


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
    ap.add_argument(
        "--t-rel-min",
        type=float,
        default=None,
        help="optional: only evaluate windows whose midpoint t_rel >= this (chaos split)",
    )
    ap.add_argument(
        "--t-rel-max",
        type=float,
        default=None,
        help="optional: only evaluate windows whose midpoint t_rel < this (chaos split)",
    )
    ap.add_argument(
        "--out-json",
        default="",
        help="optional path for eval json (default: chaos_dir/eval_chaos.json)",
    )
    ap.add_argument(
        "--idle-baseline-json",
        default="",
        help="override idle baseline (default: embed from q2 model bundle if present)",
    )
    ap.add_argument(
        "--bgp-specialist",
        default="",
        help="optional bgp_3a3b.joblib to refine 3B→3A (locked thresh; not default)",
    )
    ap.add_argument(
        "--util-specialist",
        default="",
        help="optional util_5a5b.joblib to promote 0→5A/5B when util texture is clear",
    )
    ap.add_argument(
        "--promote-0-to-3a-min-proba",
        type=float,
        default=None,
        help=(
            "If Q2 argmax is healthy/0 and P(3A)≥this, emit 3A before specialist. "
            "Calibration for MS 3A→0 under-call; tune off oneshot seal."
        ),
    )
    ap.add_argument(
        "--severity-bands-json",
        default="",
        help="LABEL-TIME bands for chaos GT severity (GNS3-native fit). Not an inference remap.",
    )
    args = ap.parse_args()

    chaos = Path(args.chaos_dir).resolve()
    series = pd.read_csv(chaos / "series.csv")
    schedule = json.loads((chaos / "chaos_schedule.json").read_text())
    df = ema_smooth(align_1hz(series), span=args.ema_span)
    t0 = int(df["ts_unix"].iloc[0])
    df["t_rel"] = df["ts_unix"].astype(int) - t0

    sev_bands = None
    if args.severity_bands_json:
        from .severity_bands import load_bands

        sev_bands = load_bands(Path(args.severity_bands_json), fabric="gns3")

    # CAPTURE_CONTRACT: join util ceil schedule before stamping util severity
    # (label-time only — same path as build_protocol_dataset).
    from .util_schedule import attach_ceil_for_features, attach_ceil_schedule, load_ceil_schedule

    util_sched_path = chaos / "util_ceil_schedule.jsonl"
    sch = load_ceil_schedule(util_sched_path) if util_sched_path.exists() else None
    if sch is not None:
        df = attach_ceil_schedule(df, sch)

    # Ground-truth root from schedule; severity from metrics under that root.
    # Stamp on the full series (not row-by-row): BGP severity uses a rolling
    # flap rate, and single-row stamp_series() collapses the roll to instant.
    roots = [schedule_root_at(float(t), schedule) for t in df["t_rel"]]
    df["gt_root"] = roots
    root_arr = np.asarray(roots, dtype=int)
    sev = pd.Series(["0"] * len(df), index=df.index, dtype=object)
    for lab in sorted(set(int(x) for x in root_arr)):
        mask = root_arr == lab
        if not mask.any():
            continue
        labeled = label_rows(df, int(lab), bands=sev_bands)
        sev.loc[mask] = labeled.loc[mask].to_numpy()
    df["gt_severity"] = sev

    # Feature path: live-parity HTB ceil (nominal outside inject window).
    # Overwrites label-time 0-fill so Q2 does not see artificial zeros.
    df = attach_ceil_for_features(df, sch)
    # BGP multi-scale (no-op zeros if flap count missing; frozen bundles ignore extras).
    from .bgp_multiscale import attach_bgp_multiscale

    df = attach_bgp_multiscale(df)

    # Load model early so idle baseline can reshape features to train parity.
    bundle = joblib.load(args.q2_model)
    model = bundle["model"]
    feat_cols = bundle["feature_cols"]
    mode = bundle.get("mode", "root")
    id_to_sev = bundle.get("id_to_severity") or ID_TO_SEVERITY
    idle_bl = bundle.get("idle_baseline")
    if args.idle_baseline_json:
        idle_bl = json.loads(Path(args.idle_baseline_json).read_text())
    util_ceil_bl = bundle.get("util_ceiling")
    bgp_bundle = None
    if args.bgp_specialist:
        bgp_bundle = joblib.load(args.bgp_specialist)
    util_bundle = None
    if args.util_specialist:
        util_bundle = joblib.load(args.util_specialist)

    win_df, _ = build_q2(df, label=0, skip_head=0)  # label unused; we overwrite
    if win_df.empty:
        raise SystemExit("no windows")

    # Optional temporal split for tune vs final (selection-trap hygiene)
    if args.t_rel_min is not None or args.t_rel_max is not None:
        mid = []
        for _, row in win_df.iterrows():
            sl = df.iloc[int(row["start_idx"]) : int(row["end_idx"])]
            mid.append(float(sl["t_rel"].mean()) if len(sl) else -1.0)
        win_df = win_df.copy()
        win_df["_t_rel_mid"] = mid
        if args.t_rel_min is not None:
            win_df = win_df[win_df["_t_rel_mid"] >= float(args.t_rel_min)]
        if args.t_rel_max is not None:
            win_df = win_df[win_df["_t_rel_mid"] < float(args.t_rel_max)]
        win_df = win_df.drop(columns=["_t_rel_mid"])
        if win_df.empty:
            raise SystemExit("no windows after t_rel filter")

    y_true = []
    y_pred = []
    red_pred = 0
    red_true = 0
    for _, row in win_df.iterrows():
        sl = df.iloc[int(row["start_idx"]) : int(row["end_idx"])]
        gt_sev = window_severity(sl["gt_severity"].astype(str).tolist())
        gt_root = int(sl["gt_root"].mode().iloc[0]) if len(sl) else 0
        buf = []
        for _, r in sl.iterrows():
            samp = {
                c: float(r[c]) if c in sl.columns and pd.notna(r[c]) else 0.0
                for c in FEATURE_COLS
            }
            if util_ceil_bl is not None and float(util_ceil_bl.get("ceil_mbps") or 0) > 0:
                samp = apply_util_ceiling_sample(samp, float(util_ceil_bl["ceil_mbps"]))
            if idle_bl is not None:
                samp = apply_idle_to_sample(samp, idle_bl)
            buf.append(samp)
        feats = window_features(buf, feat_cols)
        X = np.asarray([[feats.get(c, 0.0) for c in feat_cols]], dtype=np.float32)
        pred_id = int(model.predict(X)[0])
        if mode == "severity":
            # Model emits contiguous class ids; map back to severity string / raw id
            # before comparing to GT (raw SEVERITY_TO_ID). Mixing contig vs raw
            # silently collapses accuracy (was the 0.101 chaos_final false alarm).
            pred_sev = id_to_sev.get(pred_id, "0")
            c2r = bundle.get("contig_to_raw") or {}
            if c2r:
                raw_id = int(c2r.get(pred_id, pred_id))
                pred_sev = ID_TO_SEVERITY.get(raw_id, pred_sev)
            # Optional 3A/0 calibration: promote healthy→3A when P(3A) clears tau.
            if (
                args.promote_0_to_3a_min_proba is not None
                and pred_sev == "0"
                and hasattr(model, "predict_proba")
            ):
                proba = model.predict_proba(X)[0]
                classes = list(getattr(model, "classes_", []))
                p_3a = 0.0
                for ci, cid in enumerate(classes):
                    sev_c = id_to_sev.get(int(cid), "0")
                    if c2r:
                        sev_c = ID_TO_SEVERITY.get(
                            int(c2r.get(int(cid), c2r.get(str(int(cid)), cid))), sev_c
                        )
                    if sev_c == "3A":
                        p_3a = float(proba[ci])
                        break
                if p_3a >= float(args.promote_0_to_3a_min_proba):
                    pred_sev = "3A"
            # Util specialist before BGP: congestion texture must not become "mild flap"
            if util_bundle is not None:
                pred_sev = refine_util(pred_sev, feats, bundle=util_bundle)
            if bgp_bundle is not None:
                pred_sev = refine_3a_3b(pred_sev, feats, bundle=bgp_bundle)
            pred_root = SEVERITY_TO_ROOT.get(pred_sev, 0)
            y_true.append(SEVERITY_TO_ID.get(gt_sev, 0))
            y_pred.append(SEVERITY_TO_ID.get(pred_sev, 0))
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

    # Per-root / family phase metrics (for PROMOTE_BAR; not for selection)
    bgp_exact = bgp_family = loss_exact = util_exact = cpu_exact = None
    bgp_n = loss_n = util_n = cpu_n = 0
    if mode == "severity" and len(y_true_a):
        true_roots = np.asarray(
            [SEVERITY_TO_ROOT.get(ID_TO_SEVERITY.get(int(t), "0"), -1) for t in y_true_a]
        )
        pred_roots = np.asarray(
            [SEVERITY_TO_ROOT.get(ID_TO_SEVERITY.get(int(p), "0"), -1) for p in y_pred_a]
        )
        for root, setter in (
            (2, "cpu"),
            (3, "bgp"),
            (4, "loss"),
            (5, "util"),
        ):
            mask = true_roots == root
            if not mask.any():
                continue
            exact = float((y_true_a[mask] == y_pred_a[mask]).mean())
            n = int(mask.sum())
            if setter == "bgp":
                bgp_exact = exact
                bgp_n = n
                bgp_family = float((pred_roots[mask] == 3).mean())
            elif setter == "loss":
                loss_exact = exact
                loss_n = n
            elif setter == "util":
                util_exact = exact
                util_n = n
            else:
                cpu_exact = exact
                cpu_n = n

    result = {
        "chaos_dir": str(chaos),
        "mode": mode,
        "n_windows": int(len(win_df)),
        "accuracy": acc,
        "red_severity_true_windows": red_true,
        "red_severity_pred_windows": red_pred,
        "t_rel_min": args.t_rel_min,
        "t_rel_max": args.t_rel_max,
        "idle_baseline_mode": (idle_bl or {}).get("mode") if idle_bl else None,
        "severity_bands_json": args.severity_bands_json or None,
        "bgp_exact": bgp_exact,
        "bgp_family": bgp_family,
        "loss_phase_exact": loss_exact,
        "util_phase_exact": util_exact,
        "cpu_phase_exact": cpu_exact,
        "phase_n": {"cpu": cpu_n, "bgp": bgp_n, "loss": loss_n, "util": util_n},
        "ce_sla_note": (
            "CE-SLA (L6) is not in this chaos schedule — score L6 windows separately"
        ),
        "bgp_specialist": args.bgp_specialist or None,
        "bgp_min_3a_proba": (
            float(bgp_bundle["min_3a_proba"])
            if bgp_bundle is not None and "min_3a_proba" in bgp_bundle
            else None
        ),
        "util_specialist": args.util_specialist or None,
        "promote_0_to_3a_min_proba": args.promote_0_to_3a_min_proba,
    }

    if args.q1_loss_model and args.q1_loss_scaler:
        try:
            from tensorflow import keras
            from .q1_windows import LOSS_COL, build_windows as build_q1_loss

            q1l = keras.models.load_model(args.q1_loss_model)
            sc = np.load(args.q1_loss_scaler, allow_pickle=True)
            mean, std = sc["mean"], sc["std"]
            # Scope to loss-schedule windows only. Building ETA against the
            # first full-series loss breach (often ~t=3700 in chaos) made every
            # rain/CPU window look like a ~1800s lead — MAE ~1838 was an eval
            # artifact, not model quality (same class of bug as BGP row-stamp).
            loss_mask = df["gt_root"].astype(int) == 4
            if loss_mask.any():
                loss_df = df.loc[loss_mask].reset_index(drop=True)
            else:
                loss_df = df
            q1w, meta = build_q1_loss(
                loss_df, sla=float(args.loss_sla_pct), target_col=LOSS_COL
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
            result["q1_loss_eval_scope"] = "gt_root==4" if loss_mask.any() else "full_series"
            if not usable.empty:
                result["q1_loss_mean_lead_s"] = float(usable["eta_seconds"].mean())
            result["q1_loss_mae_full_series_DO_NOT_CITE"] = 1838.32
        except Exception as exc:  # noqa: BLE001
            result["q1_loss_error"] = str(exc)

    if args.q1_model and args.q1_scaler:
        try:
            from tensorflow import keras

            q1 = keras.models.load_model(args.q1_model)
            sc = np.load(args.q1_scaler, allow_pickle=True)
            mean, std = sc["mean"], sc["std"]
            # Latency TTI: scope to rain (root=1) phases — same full-series trap.
            rain_mask = df["gt_root"].astype(int) == 1
            rain_df = df.loc[rain_mask].reset_index(drop=True) if rain_mask.any() else df
            q1w, meta = build_q1(rain_df)
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
            result["q1_eval_scope"] = "gt_root==1" if rain_mask.any() else "full_series"
        except Exception as exc:  # noqa: BLE001
            result["q1_error"] = str(exc)

    out = Path(args.out_json).resolve() if args.out_json else (chaos / "eval_chaos.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
