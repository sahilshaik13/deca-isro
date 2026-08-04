"""Merge Q1 window CSVs from multiple rain-fade captures."""
from __future__ import annotations

import argparse
import json
from glob import glob
from pathlib import Path

import pandas as pd


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--glob",
        default="data/deca/predictive/captures/*/q1_windows_train.csv",
        help="glob of q1_windows_train.csv files (repo-relative or absolute)",
    )
    ap.add_argument("--out", required=True, help="merged CSV path")
    ap.add_argument(
        "--min-eta",
        type=float,
        default=0.0,
        help="drop windows with eta_seconds below this",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    pattern = args.glob
    if not Path(pattern).is_absolute():
        pattern = str(root / pattern)
    paths = [Path(p) for p in sorted(glob(pattern))]
    if not paths:
        raise SystemExit(f"no files matched {args.glob}")

    frames = []
    sources = []
    for p in paths:
        df = pd.read_csv(p)
        if df.empty:
            continue
        df = df.copy()
        df["source_capture"] = p.parent.name
        if args.min_eta > 0:
            df = df[df["eta_seconds"] >= args.min_eta]
        frames.append(df)
        sources.append({"path": str(p), "n": int(len(df))})

    if not frames:
        raise SystemExit("all matched files empty after filters")

    merged = pd.concat(frames, ignore_index=True)
    merged["window_id"] = range(len(merged))
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False)
    meta = {
        "n_total": int(len(merged)),
        "n_sources": len(sources),
        "sources": sources,
        "eta_min": float(merged["eta_seconds"].min()),
        "eta_max": float(merged["eta_seconds"].max()),
        "eta_median": float(merged["eta_seconds"].median()),
        "n_eta_ge_120": int((merged["eta_seconds"] >= 120).sum()),
        "out": str(out),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
