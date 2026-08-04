"""Merge Q2 window CSVs from multiple labeled campaigns."""
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
        default="data/deca/predictive/q2_captures/*/q2_windows.csv",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    pattern = args.glob if Path(args.glob).is_absolute() else str(root / args.glob)
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
        frames.append(df)
        sources.append({"path": str(p), "n": int(len(df)), "labels": df["label"].value_counts().to_dict()})

    merged = pd.concat(frames, ignore_index=True)
    merged["window_id"] = range(len(merged))
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False)
    meta = {
        "n_total": int(len(merged)),
        "label_counts": {str(k): int(v) for k, v in merged["label"].value_counts().sort_index().items()},
        "n_sources": len(sources),
        "sources": sources,
        "out": str(out),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
