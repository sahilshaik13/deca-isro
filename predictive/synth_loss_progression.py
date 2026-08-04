"""Overlay synthetic packet-loss progression onto a capture for Q1-loss training.

Live protocol corpus is latency-dominant (rain netem rarely produces loss_gre_pct>0).
This builds an honest training scaffold: loss ramps to --sla-pct correlated with the
latency rise so the loss-TTI LSTM pipeline can be trained/evaluated. Replace with
real loss-inject captures when available.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def overlay_loss(
    df: pd.DataFrame,
    *,
    sla_pct: float = 2.0,
    breach_at_latency_ms: float = 25.0,
) -> pd.DataFrame:
    d = df.copy()
    if "latency_gre_ms" not in d.columns:
        raise SystemExit("need latency_gre_ms")
    lat = d["latency_gre_ms"].astype(float).to_numpy()
    # Map latency [0, breach] → loss [0, sla]; then saturate above
    scale = np.clip(lat / max(breach_at_latency_ms, 1e-6), 0.0, 1.5)
    loss = np.clip(scale * sla_pct, 0.0, sla_pct * 1.5)
    # Keep any real non-zero loss spikes (e.g. 100% probe fails) as max
    if "loss_gre_pct" in d.columns:
        existing = d["loss_gre_pct"].astype(float).to_numpy()
        loss = np.maximum(loss, np.where(existing >= 100, 0.0, existing))
    d["loss_gre_pct"] = loss
    d["loss_synth"] = 1
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sla-pct", type=float, default=2.0, help="Payload loss SLA %")
    ap.add_argument("--breach-at-latency-ms", type=float, default=25.0)
    args = ap.parse_args()
    src = Path(args.capture).resolve()
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(src)
    out_df = overlay_loss(df, sla_pct=args.sla_pct, breach_at_latency_ms=args.breach_at_latency_ms)
    out_df.to_csv(out, index=False)
    print(
        {
            "wrote": str(out),
            "n": len(out_df),
            "loss_max": float(out_df["loss_gre_pct"].max()),
            "breach_rows": int((out_df["loss_gre_pct"] >= args.sla_pct).sum()),
        }
    )


if __name__ == "__main__":
    main()
