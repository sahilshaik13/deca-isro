"""Scoped chaos Q1 loss residuals — no eval_chaos import (TF crash)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def schedule_root_at(t_rel: float, schedule: dict) -> int:
    for ph in schedule.get("phases", []):
        if ph["t_start"] <= t_rel < ph["t_end"]:
            faults = ph.get("faults") or []
            if not faults:
                return 0
            if "bgp_flap" in faults and "rain_fade" not in faults:
                return 3
            if "cpu_stress" in faults and "rain_fade" in faults:
                return 1
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


def boot_mae(err, n_boot=2000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(err)
    stats = np.empty(n_boot)
    for i in range(n_boot):
        stats[i] = float(np.mean(err[rng.integers(0, n, n)]))
    lo, hi = np.quantile(stats, [0.025, 0.975])
    return float(lo), float(hi)


def main():
    from predictive.preprocess import align_1hz, ema_smooth
    from predictive.q1_windows import LOSS_COL, build_windows as build_q1_loss
    from predictive.util_schedule import attach_ceil_schedule, load_ceil_schedule
    from tensorflow import keras

    chaos = ROOT / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/chaos_holdout"
    series = pd.read_csv(chaos / "series.csv")
    schedule = json.loads((chaos / "chaos_schedule.json").read_text())
    df = ema_smooth(align_1hz(series), span=5)
    t0 = int(df["ts_unix"].iloc[0])
    df["t_rel"] = df["ts_unix"].astype(int) - t0
    p = chaos / "util_ceil_schedule.jsonl"
    sch = load_ceil_schedule(p) if p.exists() else None
    if sch is not None:
        df = attach_ceil_schedule(df, sch)
    df["gt_root"] = [schedule_root_at(float(t), schedule) for t in df["t_rel"]]
    loss_df = df.loc[df["gt_root"].astype(int) == 4].reset_index(drop=True)
    print("loss rows", len(loss_df), flush=True)
    q1w, meta = build_q1_loss(loss_df, sla=2.0, target_col=LOSS_COL)
    usable = q1w[q1w["label_usable"] == True]  # noqa: E712
    print("usable", len(usable), "breach", meta.get("breach_idx"), flush=True)
    seqs = []
    ys = []
    for _, row in usable.iterrows():
        seq = json.loads(row["seq_json"]) if isinstance(row.get("seq_json"), str) else None
        if seq is None:
            continue
        seqs.append(np.asarray(seq, dtype=np.float32))
        ys.append(float(row["eta_seconds"]))
    X = np.stack(seqs, axis=0) if seqs else np.zeros((0, 1, 1))
    y = np.asarray(ys, dtype=np.float32)
    model = keras.models.load_model(
        ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_tti_lstm.keras",
        compile=False,
    )
    sc = np.load(
        ROOT / "data/deca/predictive/protocol_models/lstm_q1_loss/q1_loss_scaler.npz",
        allow_pickle=True,
    )
    pred = model.predict((X - sc["mean"]) / sc["std"], verbose=0).reshape(-1)
    err = np.abs(pred - y)
    lo, hi = boot_mae(err)
    out = {
        "n": int(len(err)),
        "mae": float(np.mean(err)),
        "cite_mae": 38.798003764947254,
        "cite_n": 15,
        "boot_95": [lo, hi],
        "breach_idx": meta.get("breach_idx"),
        "matches_cite_n": int(len(err)) == 15,
        "matches_cite_mae": abs(float(np.mean(err)) - 38.798003764947254) < 1.0,
    }
    dest = (
        ROOT
        / "data/deca/predictive/protocol/full_variants_pi_20260803T175816Z/train_logs/section_11_1_ci/q1_chaos_loss.json"
    )
    dest.write_text(json.dumps(out, indent=2) + "\n")
    np.save(dest.with_suffix(".npy"), err)
    print(json.dumps(out, indent=2), flush=True)


if __name__ == "__main__":
    main()
