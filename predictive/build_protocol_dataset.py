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

from .fabric_baseline import (
    apply_idle_baseline,
    apply_util_ceiling_df,
    fabric_util_ceiling_mbps,
    fit_idle_baseline_from_protocol,
    save_idle_baseline,
    util_ceiling_meta,
)
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
    ap.add_argument(
        "--idle-baseline",
        choices=("none", "delta", "z"),
        default="none",
        help="fabric L0 idle norm for Q2 level features (labels stay absolute)",
    )
    ap.add_argument(
        "--idle-baseline-json",
        default="",
        help="optional precomputed idle_baseline.json (else fit from protocol L0)",
    )
    ap.add_argument(
        "--util-ceiling-pct",
        action="store_true",
        help="scale util_gre_mbps by fabric HTB ceiling (feature-only; labels absolute)",
    )
    ap.add_argument(
        "--fabric",
        default="pi",
        choices=("pi", "gns3"),
        help="fabric for util ceiling lookup (applied HTB rates)",
    )
    ap.add_argument(
        "--util-ceiling-mbps",
        type=float,
        default=0.0,
        help="override util ceiling Mbps (0 = fabric default)",
    )
    ap.add_argument(
        "--severity-bands-json",
        default="",
        help="optional fabric severity bands JSON (GNS3-native CPU/util/CE cuts)",
    )
    ap.add_argument(
        "--fit-gns3-severity-bands",
        action="store_true",
        help="fit GNS3 bands from this stamp's L0/L2/L5/L6 and use for labeling",
    )
    ap.add_argument(
        "--dataset-subdir",
        default="",
        help="override dataset output folder name (default: dataset / dataset_idle_* / …)",
    )
    args = ap.parse_args()

    root = Path(args.protocol_dir).resolve()
    idle_mode = args.idle_baseline
    util_pct = bool(args.util_ceiling_pct)
    # Never overwrite canonical absolute `dataset/` when feature norms are on.
    if args.dataset_subdir:
        out_dir = root / args.dataset_subdir
    elif idle_mode == "none" and not util_pct:
        out_dir = root / "dataset"
    elif util_pct and idle_mode == "none":
        out_dir = root / "dataset_util_pct"
    elif util_pct:
        out_dir = root / f"dataset_idle_{idle_mode}_util_pct"
    else:
        out_dir = root / f"dataset_idle_{idle_mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sev_bands = None
    if args.severity_bands_json:
        from .severity_bands import load_bands

        sev_bands = load_bands(Path(args.severity_bands_json), fabric=args.fabric)
    elif args.fit_gns3_severity_bands or args.fabric == "gns3":
        # Default for GNS3 builds: fabric-native CPU/util/CE label cuts (LABEL-TIME only).
        from .severity_bands import fit_gns3_bands

        band_path = out_dir / "severity_bands_gns3.json"
        try:
            sev_bands = fit_gns3_bands(root, out_path=band_path)
        except SystemExit as exc:
            print(f"WARN: could not fit GNS3 severity bands ({exc}); using Pi defaults", flush=True)
            sev_bands = None

    idle_bl = None
    if idle_mode != "none":
        if args.idle_baseline_json:
            idle_bl = json.loads(Path(args.idle_baseline_json).read_text())
        else:
            idle_bl = fit_idle_baseline_from_protocol(root)
        idle_bl["mode"] = idle_mode
        save_idle_baseline(out_dir / "idle_baseline.json", idle_bl)

    util_meta = None
    util_ceil = 0.0
    if util_pct:
        util_ceil = fabric_util_ceiling_mbps(
            args.fabric, args.util_ceiling_mbps or None
        )
        util_meta = util_ceiling_meta(args.fabric, util_ceil)
        (out_dir / "util_ceiling.json").write_text(json.dumps(util_meta, indent=2) + "\n")

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
    # unique + never train quarantines / archives (path part starts with _)
    seen = set()
    uniq = []
    for p in series_files:
        if p in seen:
            continue
        if any(part.startswith("_") for part in p.parts):
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
                recipe = meta.get("recipe")
                if isinstance(recipe, str):
                    # eff-pack stores recipe as a path string
                    try:
                        recipe = json.loads(Path(recipe).read_text())
                    except (OSError, json.JSONDecodeError, TypeError):
                        recipe = {}
                elif not isinstance(recipe, dict):
                    recipe = meta if isinstance(meta, dict) else {}
                faults = list((recipe or {}).get("faults") or meta.get("faults") or [])
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
    q1_util_frames = []
    n_util_schedule_stamped = 0
    n_util_mbps_fallback = 0
    n_ceil_feature_from_schedule = 0
    n_ceil_feature_nominal = 0
    from .util_schedule import (
        attach_ceil_for_features,
        attach_ceil_schedule,
        load_ceil_schedule,
    )

    for path, lab, cleaned, is_compound in prepared:
        # Labels on absolute metrics; Q2 features optionally util-% / idle-normalized.
        sched_path = path.parent / "util_ceil_schedule.jsonl"
        sch = load_ceil_schedule(sched_path) if sched_path.exists() else None
        stamp_df = cleaned
        if int(lab) == 5:
            if sch is not None:
                stamp_df = attach_ceil_schedule(cleaned, sch)
                n_util_schedule_stamped += 1
            else:
                n_util_mbps_fallback += 1
                print(
                    f"WARN: L5 {path.parent} missing util_ceil_schedule.jsonl — "
                    "Q2 util severity falls back to Mbps bands",
                    flush=True,
                )
        stamped = stamp_series(stamp_df, lab, bands=sev_bands)
        abs_df = stamp_df.copy()
        abs_df["severity"] = stamped["severity"]
        # Live-parity HTB ceil feature (schedule during inject; nominal idle elsewhere).
        feat_df = attach_ceil_for_features(cleaned, sch)
        if sch is not None:
            n_ceil_feature_from_schedule += 1
        else:
            n_ceil_feature_nominal += 1
        if util_meta is not None:
            feat_df = apply_util_ceiling_df(feat_df, util_ceil)
        if idle_bl is not None:
            feat_df = apply_idle_baseline(feat_df, idle_bl, mode=idle_mode)
        # BGP multi-scale series cols (rate 5/30/60 · time-since · burst).
        from .bgp_multiscale import attach_bgp_multiscale

        feat_df = attach_bgp_multiscale(feat_df)

        win_df, meta = build_q2(feat_df, label=lab, skip_head=0 if lab == 0 else 15)
        if win_df.empty:
            continue
        sevs = []
        for _, row in win_df.iterrows():
            sl = abs_df.iloc[int(row["start_idx"]) : int(row["end_idx"])]
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

        if lab == 5:
            if sch is not None:
                from .util_schedule import build_util_windows_contract

                u_df, u_meta = build_util_windows_contract(cleaned, sched_path)
                train_u = (
                    u_df[u_df.get("label_usable", True) == True]
                    if "label_usable" in u_df.columns
                    else u_df
                )
                if not train_u.empty:
                    train_u = train_u.copy()
                    train_u["source_capture"] = f"{path.parent.parent.name}/{path.parent.name}"
                    q1_util_frames.append(train_u)
                (path.parent / "q1_util_meta.json").write_text(
                    json.dumps(u_meta, indent=2) + "\n"
                )
            else:
                print(
                    f"WARN: L5 {path.parent} missing util_ceil_schedule.jsonl — "
                    "skipping util TTI windows (CAPTURE_CONTRACT)",
                    flush=True,
                )

        # Absolute series_clean only for canonical builds (avoid clobber on norm runs)
        if idle_mode == "none" and not util_pct:
            cleaned_path = path.parent / "series_clean.csv"
            # Persist severity on the stamp frame (may include ceil cols for L5)
            abs_df.to_csv(cleaned_path, index=False)

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

    q1_util_path = None
    if q1_util_frames:
        q1u = pd.concat(q1_util_frames, ignore_index=True)
        q1_util_path = out_dir / "q1_util_windows_train.csv"
        q1u.to_csv(q1_util_path, index=False)

    summary = {
        "protocol_dir": str(root),
        "n_series": len(prepared),
        "n_q2_raw": int(len(q2)),
        "n_q2_balanced": int(len(q2_bal)),
        "severity_counts": q2_bal["severity"].value_counts().to_dict() if "severity" in q2_bal.columns else {},
        "q2": str(q2_path),
        "q1": str(q1_path) if q1_path else None,
        "q1_util": str(q1_util_path) if q1_util_path else None,
        "n_q1_util_windows": int(sum(len(f) for f in q1_util_frames)),
        "scaler": str(out_dir / "preprocess_scaler.npz"),
        "idle_baseline": idle_mode,
        "idle_baseline_json": str(out_dir / "idle_baseline.json") if idle_bl is not None else None,
        "idle_l0_means": (idle_bl or {}).get("mean") if idle_bl else None,
        "util_ceiling_pct": util_pct,
        "util_ceiling": util_meta,
        "fabric": args.fabric,
        "util_severity_schedule_stamped": n_util_schedule_stamped,
        "util_severity_mbps_fallback": n_util_mbps_fallback,
        "htb_ceil_feature_from_schedule": n_ceil_feature_from_schedule,
        "htb_ceil_feature_nominal": n_ceil_feature_nominal,
        "severity_bands": (
            {
                k: sev_bands.get(k)
                for k in (
                    "fabric",
                    "source",
                    "cpu_2a",
                    "cpu_2b",
                    "util_5a",
                    "util_5b",
                    "util_5a_frac_of_end",
                    "util_5b_frac_of_end",
                    "ce_6a",
                    "ce_6b",
                    "note",
                )
            }
            if sev_bands
            else {
                "fabric": args.fabric,
                "source": "schedule_ceil_vs_end_mbit",
                "util_5a_frac_of_end": 0.50,
                "util_5b_frac_of_end": 1.00,
                "util_5a_mbps_fallback": 20.0,
                "util_5b_mbps_fallback": 35.0,
                "note": (
                    "Q2 util 5A/5B from util_ceil_schedule end_mbit residency when "
                    "present; absolute Mbps bands are no-schedule fallback only"
                ),
            }
        ),
    }
    (out_dir / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
