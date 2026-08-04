"""Build Q1 sliding windows + time-to-impact labels from a rain-fade capture CSV."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# TT&C hard SLA — docs/DECA_PREDICTIVE_ENGINE_PLAN.md
DEFAULT_SLA_MS = 25.0
DEFAULT_LOSS_SLA_PCT = 2.0  # Payload loss SLA; TT&C loss SLA is 0.1
DEFAULT_WIN = 30
DEFAULT_STRIDE = 5
LATENCY_COL = "latency_gre_ms"
LOSS_COL = "loss_gre_pct"


def load_series(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "ts_unix" not in df.columns:
        raise SystemExit(f"missing ts_unix in {path}")
    df = df.sort_values("ts_unix").reset_index(drop=True)
    return df


def find_breach_idx(values: np.ndarray, sla: float) -> int | None:
    hits = np.where(values >= sla)[0]
    if len(hits) == 0:
        return None
    return int(hits[0])


def slope(xs: np.ndarray) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    t = np.arange(n, dtype=float)
    return float(np.polyfit(t, xs, 1)[0])


def build_windows(
    df: pd.DataFrame,
    *,
    win: int = DEFAULT_WIN,
    stride: int = DEFAULT_STRIDE,
    sla: float = DEFAULT_SLA_MS,
    target_col: str = LATENCY_COL,
) -> tuple[pd.DataFrame, dict]:
    if target_col not in df.columns:
        raise SystemExit(f"missing {target_col} in series")
    series = df[target_col].astype(float).to_numpy()
    breach = find_breach_idx(series, sla)
    meta = {
        "n_rows": int(len(df)),
        "sla": sla,
        "sla_ms": sla if target_col == LATENCY_COL else None,
        "sla_pct": sla if target_col == LOSS_COL else None,
        "target_col": target_col,
        "breach_idx": breach,
        "breach_ts": int(df.loc[breach, "ts_unix"]) if breach is not None else None,
        "breach_value": float(series[breach]) if breach is not None else None,
        "win": win,
        "stride": stride,
        "latency_col": target_col,
    }

    feature_cols = [
        c
        for c in (
            "latency_gre_ms",
            "latency_eth0_ms",
            "jitter_gre_ms",
            "loss_gre_pct",
            "util_gre_mbps",
            "path_asymmetry_ms",
            "net_bytes_recv_eth0",
            "net_bytes_sent_eth0",
        )
        if c in df.columns
    ]

    rows: list[dict] = []
    for start in range(0, len(df) - win + 1, stride):
        end = start + win
        sl = df.iloc[start:end]
        tgt_w = sl[target_col].astype(float).to_numpy()
        # ETA label: seconds until first breach (only defined before breach)
        if breach is None:
            eta = float(len(df) - end)
            usable = False
        elif end <= breach:
            eta = float(breach - end + 1)  # seconds remaining after window end
            usable = True
        else:
            continue

        feat: dict = {
            "window_id": len(rows),
            "start_idx": start,
            "end_idx": end,
            "start_ts": int(sl["ts_unix"].iloc[0]),
            "end_ts": int(sl["ts_unix"].iloc[-1]),
            "target_mean": float(np.nanmean(tgt_w)),
            "target_max": float(np.nanmax(tgt_w)),
            "target_slope": slope(np.nan_to_num(tgt_w, nan=0.0)),
            "latency_mean": float(np.nanmean(tgt_w)),
            "latency_max": float(np.nanmax(tgt_w)),
            "latency_slope": slope(np.nan_to_num(tgt_w, nan=0.0)),
            "eta_seconds": eta,
            "label_usable": usable,
        }
        for c in feature_cols:
            vals = sl[c].astype(float).to_numpy()
            feat[f"{c}_mean"] = float(np.nanmean(vals))
            feat[f"{c}_last"] = float(vals[-1]) if np.isfinite(vals[-1]) else 0.0
            feat[f"{c}_slope"] = slope(np.nan_to_num(vals, nan=0.0))
        seq = sl[feature_cols].astype(float).fillna(0.0).to_numpy().tolist()
        feat["seq_json"] = json.dumps(seq)
        feat["seq_feature_cols"] = json.dumps(feature_cols)
        rows.append(feat)

    return pd.DataFrame(rows), meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True, help="series.csv from a campaign")
    ap.add_argument("--out-dir", default="", help="default: alongside capture")
    ap.add_argument("--win", type=int, default=DEFAULT_WIN)
    ap.add_argument("--stride", type=int, default=DEFAULT_STRIDE)
    ap.add_argument("--sla-ms", type=float, default=DEFAULT_SLA_MS, help="latency SLA (ms)")
    ap.add_argument(
        "--sla-pct",
        type=float,
        default=None,
        help="loss SLA percent (sets target to loss_gre_pct)",
    )
    ap.add_argument(
        "--target-col",
        default="",
        help="override target column (default latency_gre_ms or loss_gre_pct)",
    )
    ap.add_argument("--preprocess", action="store_true", help="1 Hz align + EMA before windows")
    ap.add_argument("--ema-span", type=int, default=5)
    ap.add_argument("--prefix", default="q1", help="output file prefix (q1 or q1_loss)")
    args = ap.parse_args()

    capture = Path(args.capture).resolve()
    out_dir = Path(args.out_dir).resolve() if args.out_dir else capture.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    target_col = args.target_col or (LOSS_COL if args.sla_pct is not None else LATENCY_COL)
    sla = float(args.sla_pct) if args.sla_pct is not None else float(args.sla_ms)

    df = load_series(capture)
    if target_col not in df.columns:
        raise SystemExit(f"missing {target_col} in {capture}")
    if args.preprocess:
        from .preprocess import align_1hz, ema_smooth

        df = ema_smooth(align_1hz(df), span=args.ema_span)
    windows, meta = build_windows(
        df, win=args.win, stride=args.stride, sla=sla, target_col=target_col
    )
    usable = windows[windows["label_usable"] == True] if not windows.empty else windows  # noqa: E712

    prefix = args.prefix
    series_out = out_dir / "series_clean.csv"
    windows_out = out_dir / f"{prefix}_windows.csv"
    usable_out = out_dir / f"{prefix}_windows_train.csv"
    meta_out = out_dir / f"{prefix}_meta.json"

    df.to_csv(series_out, index=False)
    windows.to_csv(windows_out, index=False)
    usable.to_csv(usable_out, index=False)
    meta["n_windows"] = int(len(windows))
    meta["n_train_windows"] = int(len(usable))
    meta_out.write_text(json.dumps(meta, indent=2) + "\n")

    print(json.dumps({"meta": meta, "wrote": str(usable_out)}, indent=2))
    if meta["breach_idx"] is None:
        print(
            f"WARN: {target_col} never reached SLA={sla} — lower SLA or use synth_loss_progression",
            flush=True,
        )


if __name__ == "__main__":
    main()
