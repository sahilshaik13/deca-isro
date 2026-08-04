"""Build Q2 sliding-window feature rows with fault class labels."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_WIN = 30
DEFAULT_STRIDE = 5

# Prefer inject-active segment for positive classes (skip early baseline)
LABEL_NAMES = {
    0: "normal",
    1: "physical_degradation",
    2: "crypto_cpu_exhaustion",
    3: "route_flap",
    4: "loss_progression",
    5: "util_congestion",
    6: "ce_sla_conflict",
}

FEATURE_COLS = [
    "latency_gre_ms",
    "latency_eth0_ms",
    "jitter_gre_ms",
    "loss_gre_pct",
    "util_gre_mbps",
    "cpu_usage_system",
    "cpu_usage_user",
    "mem_used_percent",
    "bgp_flap_count",
    "net_bytes_recv_eth0",
    "net_bytes_sent_eth0",
    "netflow_bulk_bytes",
    "netflow_voice_bytes",
    "ipsec_rekey_events_1h",
    "ipsec_rekey_anomaly",
    "path_asymmetry",
]

# Cumulative counters — never use absolute mean/max/last (session leakage).
CUMULATIVE_COLS = {
    "bgp_flap_count",
    "net_bytes_recv_eth0",
    "net_bytes_sent_eth0",
    "netflow_bulk_bytes",
    "netflow_voice_bytes",
}


def slope(xs: np.ndarray) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    t = np.arange(n, dtype=float)
    return float(np.polyfit(t, xs, 1)[0])


def build_windows(
    df: pd.DataFrame,
    *,
    label: int,
    win: int = DEFAULT_WIN,
    stride: int = DEFAULT_STRIDE,
    skip_head: int = 0,
) -> tuple[pd.DataFrame, dict]:
    cols = [c for c in FEATURE_COLS if c in df.columns]
    rows: list[dict] = []
    start0 = max(0, skip_head)
    for start in range(start0, len(df) - win + 1, stride):
        end = start + win
        sl = df.iloc[start:end]
        feat: dict = {
            "window_id": len(rows),
            "start_idx": start,
            "end_idx": end,
            "start_ts": int(sl["ts_unix"].iloc[0]),
            "end_ts": int(sl["ts_unix"].iloc[-1]),
            "label": int(label),
            "label_name": LABEL_NAMES.get(label, str(label)),
        }
        for c in cols:
            vals = sl[c].astype(float).to_numpy()
            vals = np.nan_to_num(vals, nan=0.0)
            if c in CUMULATIVE_COLS:
                # rate-like: per-sample diff, then summarize (no absolute level)
                d = np.diff(vals, prepend=vals[0])
                feat[f"{c}_delta"] = float(vals[-1] - vals[0])
                feat[f"{c}_slope"] = slope(vals)
                feat[f"{c}_rate_mean"] = float(np.mean(d))
                feat[f"{c}_rate_std"] = float(np.std(d))
                feat[f"{c}_rate_max"] = float(np.max(d))
            else:
                feat[f"{c}_mean"] = float(np.mean(vals))
                feat[f"{c}_max"] = float(np.max(vals))
                feat[f"{c}_std"] = float(np.std(vals))
                feat[f"{c}_last"] = float(vals[-1])
                feat[f"{c}_slope"] = slope(vals)
                feat[f"{c}_delta"] = float(vals[-1] - vals[0])
        # PS13-O2.2 derived: GRE vs eth0 path asymmetry (for next Q2 retrain)
        if "latency_gre_ms" in cols and "latency_eth0_ms" in cols:
            gre = sl["latency_gre_ms"].astype(float).to_numpy()
            eth = sl["latency_eth0_ms"].astype(float).to_numpy()
            gre = np.nan_to_num(gre, nan=0.0)
            eth = np.nan_to_num(eth, nan=0.0)
            diff = gre - eth
            feat["path_asymmetry_ms_last"] = float(diff[-1])
            feat["path_asymmetry_ms_mean"] = float(np.mean(diff))
            feat["path_asymmetry_ms_max"] = float(np.max(np.abs(diff)))
            feat["path_asymmetry_ms_std"] = float(np.std(diff))
            feat["path_asymmetry_ms_slope"] = slope(diff)
        rows.append(feat)

    meta = {
        "n_rows": int(len(df)),
        "n_windows": len(rows),
        "label": int(label),
        "label_name": LABEL_NAMES.get(label, str(label)),
        "win": win,
        "stride": stride,
        "skip_head": skip_head,
        "feature_base_cols": cols,
    }
    return pd.DataFrame(rows), meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--label", type=int, required=True, choices=[0, 1, 2, 3, 4, 5, 6])
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--win", type=int, default=DEFAULT_WIN)
    ap.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    ap.add_argument(
        "--skip-head",
        type=int,
        default=-1,
        help="skip first N samples (default: 0 for label0, 20 for faults)",
    )
    ap.add_argument("--preprocess", action="store_true")
    ap.add_argument("--ema-span", type=int, default=5)
    args = ap.parse_args()

    path = Path(args.capture).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(path).sort_values("ts_unix").reset_index(drop=True)
    if args.preprocess:
        from .preprocess import align_1hz, ema_smooth

        df = ema_smooth(align_1hz(df), span=args.ema_span)
    skip = args.skip_head
    if skip < 0:
        skip = 0 if args.label == 0 else 20

    windows, meta = build_windows(
        df, label=args.label, win=args.win, stride=args.stride, skip_head=skip
    )
    out_csv = out_dir / "q2_windows.csv"
    windows.to_csv(out_csv, index=False)
    meta["wrote"] = str(out_csv)
    (out_dir / "q2_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps({"meta": meta, "wrote": str(out_csv)}, indent=2))


if __name__ == "__main__":
    main()
