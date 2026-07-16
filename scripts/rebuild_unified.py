#!/usr/bin/env python3
"""Rebuild deca_unified_{raw,dataset}.parquet from current RPi + public lake.

Bypasses the notebook's stale ./data/raw/network/ + synthetic path so today's
campaign export, Cisco, MAWI, Atlas sample, and BGP rates feed the trainable set.

Synthetic is intentionally omitted — real RPi ground truth makes it noise.

Public IODA/BGP outage CSVs are stored as provenance only: their event windows
(mostly starting ~Jul 5) do not overlap public telemetry used here (Atlas Jul 8–13
etc.), so they cannot label feature rows until overlapping telemetry exists.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from _paths import PROCESSED_DIR, PUBLIC_DIR, RPI_NET_DIR

RPI_RUN = RPI_NET_DIR / "runs" / "20260713_155333"

METRIC_MAP = {
    "throughput_in_bps": "ifInOctets",
    "throughput_out_bps": "ifOutOctets",
    "jitter_ms": "jitter_ms",
    "packet_loss_pct": "packet_loss_pct",
    "latency_ms": "jitter_ms",  # Atlas RTT / lab latency -> volatility channel
    "drop_out_rate": "packet_loss_pct",
    "ifInOctets": "ifInOctets",
    "ifOutOctets": "ifOutOctets",
    "bgp_update_rate": "bgp_update_rate",
}

# Shared classification vocabulary across network + public sources.
# Public rows are healthy context only (no overlapping outage windows today).
HEALTHY_ALIASES = {
    "none",
    "normal",
    "healthy",
    "",
    # Near-miss / aborted onset — looked like a fault, never became one.
    # Mapped to healthy so the classifier learns "false start ≠ fault class".
    "precursor_aborted",
    "near_miss",
    "aborted",
}
UNIFIED_LABELS = (
    "healthy",
    "congestion_breach",
    "tunnel_degradation",
    "bgp_route_flap",
    "vrf_leakage",
)


def to_unified_label(fault_type: str | float | None) -> str:
    if fault_type is None or (isinstance(fault_type, float) and np.isnan(fault_type)):
        return "healthy"
    key = str(fault_type).strip().lower()
    if key in HEALTHY_ALIASES:
        return "healthy"
    return str(fault_type).strip()


def engineer_features(
    df: pd.DataFrame,
    window_minutes: int = 10,
    step_seconds: int = 15,
    short_window_minutes: int = 2,
) -> pd.DataFrame:
    """Build multi-scale rolling features (slow build-up + fast onset).

    Scales
    ------
    - long (default 10 min): ``{metric}_slope`` / ``_rolling_*`` / ``_accel``
      — accumulation / slow congestion structure
    - short (default 2 min): ``{metric}_w2m_slope`` / …
      — instant flaps / onset spikes

    Duration of a labelled fault is **not** a feature (pattern only).
    Never upsample sparse public series past native cadence.
    """
    df = df.sort_values(["run_id", "metric", "timestamp"]).copy()
    scales = [("long", window_minutes, ""), ("short", short_window_minutes, "_w2m")]
    per_run_frames = []

    for run_id, run_group in df.groupby("run_id"):
        source = run_group["source"].iloc[0]
        metric_frames = []
        for metric, mgroup in run_group.groupby("metric"):
            series = mgroup.set_index("timestamp")["value"].sort_index()
            series = series[~series.index.duplicated(keep="last")]
            if len(series) < 3:
                continue

            gaps = series.index.to_series().diff().dt.total_seconds().dropna()
            median_gap = float(gaps.median()) if len(gaps) else step_seconds

            if median_gap <= step_seconds:
                g = series.resample(f"{step_seconds}s").mean().to_frame("value")
                g["value"] = g["value"].interpolate(limit=int(120 / step_seconds))
            else:
                g = series.to_frame("value")

            dt = max(median_gap, step_seconds)
            out = pd.DataFrame(index=g.index)
            for _name, win_min, suffix in scales:
                win = f"{win_min}min"
                slope = g["value"].diff() / dt
                out[f"{metric}{suffix}_slope"] = slope
                out[f"{metric}{suffix}_rolling_std"] = g["value"].rolling(win).std()
                out[f"{metric}{suffix}_rolling_mean"] = g["value"].rolling(win).mean()
                out[f"{metric}{suffix}_accel"] = slope.diff() / dt
            metric_frames.append(out)

        if not metric_frames:
            continue
        run_features = pd.concat(metric_frames, axis=1)
        feat_cols = list(run_features.columns)
        run_features = run_features.dropna(subset=feat_cols)
        run_features["run_id"] = run_id
        run_features["source"] = source
        per_run_frames.append(run_features)

    if not per_run_frames:
        return pd.DataFrame()
    return pd.concat(per_run_frames, axis=0, sort=False)


def label_fault_windows(features: pd.DataFrame, fault_log: pd.DataFrame) -> pd.DataFrame:
    features = features.copy()
    features["time_to_breach_minutes"] = np.nan
    features["fault_type"] = "none"

    fault_log = fault_log.copy()
    fault_log["fault_start"] = pd.to_datetime(fault_log["fault_start"], utc=True)
    fault_log["breach_time"] = pd.to_datetime(fault_log["breach_time"], utc=True)

    for _, row in fault_log.iterrows():
        # Network campaign: continuous scrape — label by time on network source.
        if row["run_id"].startswith("real_"):
            time_mask = (
                (features["source"] == "network")
                & (features.index >= row["fault_start"])
                & (features.index <= row["breach_time"])
            )
            if time_mask.any():
                minutes_to_breach = (row["breach_time"] - features.index[time_mask]).total_seconds() / 60.0
                features.loc[time_mask, "time_to_breach_minutes"] = minutes_to_breach
                features.loc[time_mask, "fault_type"] = row["fault_type"]
            continue

        run_mask = features["run_id"] == row["run_id"]
        if not run_mask.any():
            continue
        time_mask = run_mask & (features.index >= row["fault_start"]) & (features.index <= row["breach_time"])
        minutes_to_breach = (row["breach_time"] - features.index[time_mask]).total_seconds() / 60.0
        features.loc[time_mask, "time_to_breach_minutes"] = minutes_to_breach
        features.loc[time_mask, "fault_type"] = row["fault_type"]

    features["unified_label"] = features["fault_type"].map(to_unified_label)
    features["is_anomaly"] = (features["unified_label"] != "healthy").astype(int)
    return features


def label_circumstance_existence(
    features: pd.DataFrame, run_dirs: list[Path]
) -> pd.DataFrame:
    """Additive existence + phase labels from circumstance campaign logs.

    Does **not** require changing School Exam. When a ``circumstance_log.csv`` is
    present, also aligns ``fault_type`` / ``unified_label`` / TTB on the same
    windows so dual logs do not teach conflicting spans:

    - ``circumstance`` + ``breach`` phases → fault class present (existence)
    - ``time_to_breach_minutes`` relative to true ``breach_time`` (not recovery)

    Absolute durations are never emitted as features — only row labels by time.
    """
    features = features.copy()
    features["circumstance_label"] = "healthy"
    features["event_phase"] = "none"

    net = features["source"] == "network"
    if not net.any():
        return features

    n_events = 0
    for run_dir in run_dirs:
        circ_path = run_dir / "circumstance_log.csv"
        if not circ_path.exists():
            continue
        events = pd.read_csv(circ_path)
        for _, ev in events.iterrows():
            ft = to_unified_label(ev["fault_type"])
            if ft == "healthy":
                continue
            cs = pd.to_datetime(ev["circumstance_start"], utc=True)
            bt = pd.to_datetime(ev["breach_time"], utc=True)
            rt = pd.to_datetime(ev["recovery_time"], utc=True)
            idx = features.index
            circ_mask = net & (idx >= cs) & (idx < bt)
            breach_mask = net & (idx >= bt) & (idx <= rt)
            exist = circ_mask | breach_mask
            features.loc[circ_mask, "event_phase"] = "circumstance"
            features.loc[breach_mask, "event_phase"] = "breach"
            features.loc[exist, "circumstance_label"] = ft
            # Align event labels with existence (override ramp-only injection log)
            features.loc[exist, "fault_type"] = ft
            features.loc[exist, "unified_label"] = ft
            features.loc[exist, "is_anomaly"] = 1
            if exist.any():
                features.loc[exist, "time_to_breach_minutes"] = (
                    bt - features.index[exist]
                ).total_seconds() / 60.0
            n_events += 1

    if n_events:
        print(f"  circumstance existence labels applied for {n_events} events")
        print(features["circumstance_label"].value_counts().to_string())
    else:
        print("  no circumstance_log.csv found — existence labels default to healthy")
    return features


def _clean_telemetry(tele: pd.DataFrame, *, campaign_id: str) -> pd.DataFrame:
    """Drop nulls / non-finite / exact dups; namespace run_id per campaign+host."""
    tele = tele.copy()
    tele["timestamp"] = pd.to_datetime(tele["timestamp"], utc=True, errors="coerce")
    tele["value"] = pd.to_numeric(tele["value"], errors="coerce")
    tele["metric"] = tele["metric"].map(lambda m: METRIC_MAP.get(m, m))
    tele = tele[
        tele["metric"].isin(
            {"ifInOctets", "ifOutOctets", "jitter_ms", "packet_loss_pct", "bgp_update_rate"}
        )
    ]
    before = len(tele)
    tele = tele.dropna(subset=["timestamp", "value", "host", "metric"])
    tele = tele[np.isfinite(tele["value"])]
    # Exact duplicate scrapes → keep last
    tele = tele.sort_values("timestamp").drop_duplicates(
        subset=["timestamp", "host", "metric"], keep="last"
    )
    # Namespace so two campaigns never stitch into one broken host series
    tele["run_id"] = f"rpi_{campaign_id}_" + tele["host"].astype(str)
    tele["source"] = "network"
    tele = tele[["timestamp", "metric", "value", "run_id", "source"]]
    print(f"    clean telemetry {campaign_id}: {before} → {len(tele)} rows")
    return tele


def _clean_faults(faults: pd.DataFrame, *, campaign_id: str) -> pd.DataFrame:
    faults = faults.copy()
    faults["fault_start"] = pd.to_datetime(faults["fault_start"], utc=True, errors="coerce")
    faults["breach_time"] = pd.to_datetime(faults["breach_time"], utc=True, errors="coerce")
    before = len(faults)
    faults = faults.dropna(subset=["fault_type", "fault_start", "breach_time"])
    faults = faults[faults["breach_time"] > faults["fault_start"]]
    # Keep real_ prefix for the labeler; embed campaign id so ids stay unique across merges
    def _rid(x: str) -> str:
        x = str(x)
        if x.startswith("real_"):
            return f"real_{campaign_id}__{x[len('real_'):]}"
        return f"real_{campaign_id}__{x}"

    faults["run_id"] = faults["run_id"].map(_rid)
    print(f"    clean faults {campaign_id}: {before} → {len(faults)} windows")
    return faults


def load_rpi_run(run_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    campaign_id = run_dir.name
    tele = pd.read_csv(run_dir / "network_telemetry.csv", parse_dates=["timestamp"])
    tele = _clean_telemetry(tele, campaign_id=campaign_id)
    faults = pd.read_csv(
        run_dir / "fault_injection_log.csv", parse_dates=["fault_start", "breach_time"]
    )
    faults = _clean_faults(faults, campaign_id=campaign_id)
    return tele, faults


def load_rpi(run_dirs: list[Path] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    dirs = run_dirs or [RPI_RUN]
    teles, faults = [], []
    for d in dirs:
        print(f"  loading campaign {d.name}")
        t, f = load_rpi_run(d)
        teles.append(t)
        faults.append(f)
    tele = pd.concat(teles, ignore_index=True) if teles else pd.DataFrame()
    fault = pd.concat(faults, ignore_index=True) if faults else pd.DataFrame()
    if len(tele):
        tele = tele.sort_values("timestamp").drop_duplicates(
            subset=["timestamp", "run_id", "metric"], keep="last"
        )
    print(f"  merged network rows={len(tele)}  fault windows={len(fault)}")
    return tele, fault


def load_public() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    # MAWI — magnitude calibration only (flat even-split; not a trajectory source)
    mawi = PUBLIC_DIR / "mawi_sample.csv"
    if mawi.exists():
        raw = pd.read_csv(mawi, parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        raw["metric"] = "ifInOctets"
        raw["run_id"] = "mawi_traffic_sample"
        raw["source"] = "public"
        frames.append(raw[["timestamp", "metric", "value", "run_id", "source"]])
        print(f"  mawi_sample: {len(raw)} rows")

    # Cisco sandbox (already timestamp,metric,value)
    cisco = PUBLIC_DIR / "cisco_sandbox_sample.csv"
    if cisco.exists():
        raw = pd.read_csv(cisco, parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        raw["metric"] = raw["metric"].map(lambda m: METRIC_MAP.get(m, m))
        raw["run_id"] = "cisco_sandbox"
        raw["source"] = "public"
        frames.append(raw[["timestamp", "metric", "value", "run_id", "source"]])
        print(f"  cisco_sandbox: {len(raw)} rows")

    # Parsed BGP minute rates
    bgp = PUBLIC_DIR / "bgp_update_rates_full.csv"
    if bgp.exists():
        raw = pd.read_csv(bgp, parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        raw = raw.rename(columns={"bgp_update_rate": "value"})
        raw["metric"] = "bgp_update_rate"
        raw["run_id"] = "bgp_update_rates_full"
        raw["source"] = "public"
        frames.append(raw[["timestamp", "metric", "value", "run_id", "source"]])
        print(f"  bgp_update_rates_full: {len(raw)} rows")

    # Atlas sampled — collapse probes to 1-min mean RTT (+ mean loss) so feature eng stays tractable
    atlas = PUBLIC_DIR / "ripe_atlas_ping_sampled.csv"
    if atlas.exists():
        raw = pd.read_csv(atlas, parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        raw["minute"] = raw["timestamp"].dt.floor("min")
        agg = (
            raw.groupby("minute", as_index=False)
            .agg(rtt_ms=("rtt_ms", "mean"), packet_loss_pct=("packet_loss_pct", "mean"))
        )
        for metric, col in [("jitter_ms", "rtt_ms"), ("packet_loss_pct", "packet_loss_pct")]:
            part = agg[["minute", col]].rename(columns={"minute": "timestamp", col: "value"})
            part["metric"] = metric
            part["run_id"] = "ripe_atlas_ping_sampled"
            part["source"] = "public"
            frames.append(part[["timestamp", "metric", "value", "run_id", "source"]])
        print(f"  ripe_atlas_ping_sampled: {len(raw)} probe rows -> {len(agg)} minute buckets x2 metrics")

    # Baseline snapshot (optional small)
    baseline = PUBLIC_DIR / "ripe_atlas_ping_baseline.csv"
    if baseline.exists():
        raw = pd.read_csv(baseline, parse_dates=["timestamp"])
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        part = raw[["timestamp", "rtt_ms"]].rename(columns={"rtt_ms": "value"})
        part["metric"] = "jitter_ms"
        part["run_id"] = "ripe_atlas_ping_baseline"
        part["source"] = "public"
        frames.append(part[["timestamp", "metric", "value", "run_id", "source"]])
        print(f"  ripe_atlas_ping_baseline: {len(part)} rows")

    if not frames:
        return pd.DataFrame(columns=["timestamp", "metric", "value", "run_id", "source"])
    return pd.concat(frames, ignore_index=True)


def load_public_fault_labels() -> pd.DataFrame:
    """Provenance inventory of ASN outage CSVs — NOT used for feature labeling.

    Event starts are typically ~Jul 5 while public telemetry here (Atlas sample
    Jul 8–13, BGP rates Jul 8–12, …) does not cover those windows, so joining
    them into the labeler produces zero matches. Keep the files; don't pretend.
    """
    rows = []
    for name, path in [
        ("bgp_routing_labels.csv", PUBLIC_DIR / "bgp_routing_labels.csv"),
        ("ioda_outage_labels.csv", PUBLIC_DIR / "ioda_outage_labels.csv"),
    ]:
        if not path.exists():
            continue
        raw = pd.read_csv(path)
        for i, r in raw.iterrows():
            start = r.get("start_time")
            if pd.isna(start):
                continue
            start_ts = pd.to_datetime(start, utc=True)
            dur = float(r.get("duration_sec") or 0)
            end_ts = start_ts + pd.Timedelta(seconds=max(dur, 60))
            rows.append(
                {
                    "fault_type": "bgp_route_flap",
                    "fault_start": start_ts,
                    "breach_time": end_ts,
                    "run_id": f"public_{name}_{i}",
                    "provenance_file": name,
                }
            )
        starts = pd.to_datetime(raw["start_time"], utc=True, errors="coerce")
        print(
            f"  public fault labels from {name}: {len(raw)} events "
            f"(span {starts.min()} → {starts.max()}) — provenance only, not applied"
        )
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["fault_type", "fault_start", "breach_time", "run_id", "provenance_file"]
    )


def main() -> None:
    global RPI_RUN
    parser = argparse.ArgumentParser(description="Rebuild deca_unified_{raw,dataset}.parquet")
    parser.add_argument(
        "--rpi-run",
        type=Path,
        action="append",
        default=None,
        help="Campaign run dir or id under data/rpi-net/runs/ (repeatable; merges all)",
    )
    parser.add_argument(
        "--all-rpi-runs",
        action="store_true",
        help="Merge every campaign directory under data/rpi-net/runs/",
    )
    args = parser.parse_args()

    run_dirs: list[Path] = []
    if args.all_rpi_runs:
        run_dirs = sorted(
            p for p in (RPI_NET_DIR / "runs").iterdir()
            if p.is_dir() and (p / "fault_injection_log.csv").exists()
            and (p / "network_telemetry.csv").exists()
        )
    elif args.rpi_run:
        for run in args.rpi_run:
            run_dirs.append(run if run.is_absolute() else RPI_NET_DIR / "runs" / run.name)
    else:
        run_dirs = [RPI_RUN]

    RPI_RUN = run_dirs[0]
    print(f"RPI_RUNS={[p.name for p in run_dirs]}")

    print("=== Loading RPi campaign(s) ===")
    network_df, network_fault_log = load_rpi(run_dirs)
    print(f"  network_df={len(network_df)}  fault_windows={len(network_fault_log)}")

    print("=== Loading public lake ===")
    public_df = load_public()
    public_fault_log = load_public_fault_labels()
    print(f"  public_df={len(public_df)}")
    print(
        "  NOTE: IODA/BGP outage labels are NOT merged into the training labeler — "
        "no overlapping public telemetry for those Jul-5-centric windows."
    )

    # Synthetic intentionally omitted: real Pi labels make it noise, not signal.
    print("=== Synthetic ===")
    print("  synthetic: 0 rows (deliberate — RPi ground truth replaces synthetic noise)")

    row_counts = {
        "network": len(network_df),
        "synthetic": 0,
        "public": len(public_df),
    }
    unified_raw = pd.concat(
        [f for f in [network_df, public_df] if len(f)],
        ignore_index=True,
    )
    unified_raw["timestamp"] = pd.to_datetime(unified_raw["timestamp"], utc=True)
    unified_raw["value"] = pd.to_numeric(unified_raw["value"], errors="coerce")
    unified_raw = unified_raw.dropna(subset=["timestamp", "value"])

    # Only RPi faults teach the model
    unified_fault_log = network_fault_log.copy()
    if len(public_fault_log):
        public_fault_log.to_csv(PROCESSED_DIR / "public_outage_labels_provenance.csv", index=False)
        print(
            f"  wrote public_outage_labels_provenance.csv ({len(public_fault_log)} rows) — inventory only"
        )

    print("\n=== Provenance audit ===")
    total = sum(row_counts.values())
    for src, n in row_counts.items():
        pct = (n / total * 100) if total else 0
        print(f"  {src:10s}: {n:8d} rows  ({pct:5.1f}%)")
    print(f"  {'TOTAL':10s}: {total:8d} rows (pre-dropna)")
    print(f"  unified_raw after clean: {len(unified_raw)}")
    print(f"  training fault windows (RPi only): {len(unified_fault_log)}")

    # Backup prior parquets
    for name in ("deca_unified_raw.parquet", "deca_unified_dataset.parquet"):
        src = PROCESSED_DIR / name
        if src.exists():
            bak = PROCESSED_DIR / f"{name}.bak_pre_rebuild"
            shutil.copy2(src, bak)
            print(f"  backed up {name} -> {bak.name}")

    raw_path = PROCESSED_DIR / "deca_unified_raw.parquet"
    unified_raw.to_parquet(raw_path, index=False)
    unified_fault_log.to_csv(PROCESSED_DIR / "deca_unified_fault_log.csv", index=False)
    print(f"\nWrote {raw_path} ({len(unified_raw)} rows)")

    print("\n=== Feature engineering ===")
    features = engineer_features(unified_raw)
    print(f"  features={len(features)} rows, cols={len(features.columns)}")
    if len(features) == 0:
        raise SystemExit("Feature matrix empty — abort")

    by_src = features["source"].value_counts().to_dict()
    print(f"  features by source: {by_src}")
    raw_pub = len(unified_raw[unified_raw["source"] == "public"])
    feat_pub = by_src.get("public", 0)
    if feat_pub > raw_pub:
        raise SystemExit(
            f"Public feature rows ({feat_pub}) > raw public ({raw_pub}) — upsampling bug, abort"
        )

    labeled = label_fault_windows(features, unified_fault_log)
    print("\n=== Circumstance existence labels (additive) ===")
    labeled = label_circumstance_existence(labeled, run_dirs)
    out = PROCESSED_DIR / "deca_unified_dataset.parquet"
    labeled.to_parquet(out)
    print(f"Wrote {out} ({len(labeled)} rows)")
    print("\nFault type distribution:")
    print(labeled["fault_type"].value_counts().to_string())
    print("\nUnified label distribution:")
    print(labeled["unified_label"].value_counts().to_string())
    print("\nBy source × unified_label:")
    print(labeled.groupby(["source", "unified_label"]).size().to_string())


if __name__ == "__main__":
    main()
