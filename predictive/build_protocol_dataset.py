"""Build train windows from a protocol directory (preprocess + severity).

Skips chaos/ (train=false). Includes L* and COMPOUND/ (dominant root label).
Writes:
  protocol_dir/dataset/q2_windows.csv
  protocol_dir/dataset/q1_windows_train.csv (from L1 only)
  protocol_dir/dataset/preprocess_scaler.npz
"""
from __future__ import annotations

import argparse
import json
from glob import glob
from pathlib import Path

import pandas as pd

from .preprocess import align_1hz, balance_windows, ema_smooth, fit_zscore, save_scaler
from .q1_windows import build_windows as build_q1
from .q2_windows import build_windows as build_q2
from .severity_label import SEVERITY_NAMES, SEVERITY_TO_ID, stamp_series, window_severity


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol-dir", required=True)
    ap.add_argument("--ema-span", type=int, default=5)
    ap.add_argument("--balance", action="store_true", default=True)
    ap.add_argument("--no-balance", action="store_true")
    ap.add_argument("--smote", action="store_true")
    ap.add_argument("--max-per-class", type=int, default=0)
    args = ap.parse_args()

    root = Path(args.protocol_dir).resolve()
    out_dir = root / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)

    series_files = sorted(
        Path(p)
        for p in glob(str(root / "L*" / "iter_*" / "series.csv"))
        if "chaos" not in p
    )
    # also accept flat q2-style paths under protocol
    series_files += sorted(Path(p) for p in glob(str(root / "L*" / "**/series.csv")))
    # Compound train captures (dominant root label — see compound_label.py)
    series_files += sorted(
        Path(p) for p in glob(str(root / "COMPOUND" / "iter_*" / "series.csv"))
    )
    # unique
    seen = set()
    uniq = []
    for p in series_files:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    series_files = uniq
    if not series_files:
        raise SystemExit(f"no series.csv under {root}/L* or COMPOUND/")

    from .compound_label import dominant_root_label

    # Infer root label from path L{n}_ (compound → dominant fault signature)
    prepared: list[tuple[Path, int, pd.DataFrame, bool]] = []
    raw_for_scaler: list[pd.DataFrame] = []
    for path in series_files:
        parts = path.parts
        lab = None
        is_compound = "COMPOUND" in parts
        for part in parts:
            if part.startswith("L") and "_" in part and part[1].isdigit():
                lab = int(part[1])
                break
        df = pd.read_csv(path)
        cleaned = ema_smooth(align_1hz(df), span=args.ema_span)
        if is_compound:
            lj = path.parent / "label.json"
            faults: list[str] = []
            if lj.exists():
                meta = json.loads(lj.read_text())
                faults = list((meta.get("recipe") or meta).get("faults") or [])
            lab, dbg = dominant_root_label(cleaned, faults)
            (path.parent / "compound_label.json").write_text(
                json.dumps(dbg, indent=2) + "\n"
            )
        elif lab is None:
            lj = path.parent / "label.json"
            if lj.exists():
                raw = json.loads(lj.read_text()).get("label", -1)
                try:
                    lab = int(raw)
                except (TypeError, ValueError):
                    lab = -1
        if lab is None or lab < 0:
            continue
        raw_for_scaler.append(cleaned)
        prepared.append((path, lab, cleaned, is_compound))

    mean, std, cols = fit_zscore(raw_for_scaler)
    save_scaler(out_dir / "preprocess_scaler.npz", mean, std, cols)

    q2_frames = []
    q1_frames = []
    for path, lab, cleaned, is_compound in prepared:
        stamped = stamp_series(cleaned, lab)
        cleaned = cleaned.copy()
        cleaned["severity"] = stamped["severity"]

        # Features from cleaned (unscaled) series
        win_df, meta = build_q2(cleaned, label=lab, skip_head=0 if lab == 0 else 15)
        if win_df.empty:
            continue
        sevs = []
        for _, row in win_df.iterrows():
            sl = cleaned.iloc[int(row["start_idx"]) : int(row["end_idx"])]
            sev = window_severity(sl["severity"].astype(str).tolist())
            sevs.append(sev)
        win_df["severity"] = sevs
        win_df["severity_name"] = [SEVERITY_NAMES.get(s, s) for s in sevs]
        win_df["severity_id"] = [SEVERITY_TO_ID[s] for s in sevs]
        win_df["root_label"] = lab
        win_df["is_compound"] = int(is_compound)
        # Unique per series: L{n}_name/iter_xx (iter alone collides across labels)
        win_df["source_capture"] = f"{path.parent.parent.name}/{path.parent.name}"
        q2_frames.append(win_df)

        if lab == 1:
            q1_df, q1_meta = build_q1(cleaned)
            if not q1_df.empty:
                # keep usable train rows
                train = q1_df[q1_df.get("label_usable", True) == True] if "label_usable" in q1_df.columns else q1_df
                if not train.empty:
                    train = train.copy()
                    train["source_capture"] = f"{path.parent.parent.name}/{path.parent.name}"
                    q1_frames.append(train)

        # write per-capture cleaned
        cleaned_path = path.parent / "series_clean.csv"
        cleaned.to_csv(cleaned_path, index=False)

    if not q2_frames:
        raise SystemExit("no Q2 windows built")

    q2 = pd.concat(q2_frames, ignore_index=True)
    q2["window_id"] = range(len(q2))
    do_balance = args.balance and not args.no_balance
    if do_balance:
        max_c = args.max_per_class or None
        q2_bal = balance_windows(
            q2,
            label_col="severity",
            max_per_class=max_c,
            smote=args.smote,
        )
    else:
        q2_bal = q2

    q2_path = out_dir / "q2_windows.csv"
    q2_bal.to_csv(q2_path, index=False)
    q2.to_csv(out_dir / "q2_windows_raw.csv", index=False)

    q1_path = None
    if q1_frames:
        q1 = pd.concat(q1_frames, ignore_index=True)
        q1_path = out_dir / "q1_windows_train.csv"
        q1.to_csv(q1_path, index=False)

    summary = {
        "protocol_dir": str(root),
        "n_series": len(prepared),
        "n_q2_raw": int(len(q2)),
        "n_q2_balanced": int(len(q2_bal)),
        "severity_counts": q2_bal["severity"].value_counts().to_dict() if "severity" in q2_bal.columns else {},
        "q2": str(q2_path),
        "q1": str(q1_path) if q1_path else None,
        "scaler": str(out_dir / "preprocess_scaler.npz"),
    }
    (out_dir / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
