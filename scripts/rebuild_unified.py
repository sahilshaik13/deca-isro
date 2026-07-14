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
}

# Shared classification vocabulary across network + public sources.
# Public rows are healthy context only (no overlapping outage windows today).
HEALTHY_ALIASES = {"none", "normal", "healthy", ""}
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


def engineer_features(df: pd.DataFrame, window_minutes: int = 10, step_seconds: int = 15) -> pd.DataFrame:
    """Build rolling features. Never upsample: only downfill to step when native
    cadence is denser than step. Minute/sparse series (Atlas, BGP rates, MAWI)
    keep their native timestamps — older native*4 guard still upsampled Atlas
    1-min → 15s (~4x row inflation)."""
    df = df.sort_values(["run_id", "metric", "timestamp"]).copy()
    window = f"{window_minutes}min"
    per_run_frames = []

    for run_id, run_group in df.groupby("run_id"):
        source = run_group["source"].iloc[0]
        metric_frames = []
        for metric, mgroup in run_group.groupby("metric"):
            series = mgroup.set_index("timestamp")["value"].sort_index()
            # Drop exact-duplicate timestamps (keep last)
            series = series[~series.index.duplicated(keep="last")]
            if len(series) < 3:
                continue

            gaps = series.index.to_series().diff().dt.total_seconds().dropna()
            median_gap = float(gaps.median()) if len(gaps) else step_seconds

            # Upsample only when native points are denser than target step
            if median_gap <= step_seconds:
                g = series.resample(f"{step_seconds}s").mean().to_frame("value")
                g["value"] = g["value"].interpolate(limit=int(120 / step_seconds))
            else:
                g = series.to_frame("value")

            g[f"{metric}_slope"] = g["value"].diff() / max(median_gap, step_seconds)
            g[f"{metric}_rolling_std"] = g["value"].rolling(window).std()
            g[f"{metric}_rolling_mean"] = g["value"].rolling(window).mean()
            g[f"{metric}_accel"] = g[f"{metric}_slope"].diff() / max(median_gap, step_seconds)
            metric_frames.append(g[[c for c in g.columns if c != "value"]])

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


def load_rpi() -> tuple[pd.DataFrame, pd.DataFrame]:
    tele = pd.read_csv(RPI_RUN / "network_telemetry.csv", parse_dates=["timestamp"])
    tele["timestamp"] = pd.to_datetime(tele["timestamp"], utc=True)
    tele["metric"] = tele["metric"].map(lambda m: METRIC_MAP.get(m, m))
    tele = tele[tele["metric"].isin({"ifInOctets", "ifOutOctets", "jitter_ms", "packet_loss_pct"})]
    # One run_id per host keeps time-series continuity for feature eng
    tele["run_id"] = "rpi_" + tele["host"].astype(str)
    tele["source"] = "network"
    tele = tele[["timestamp", "metric", "value", "run_id", "source"]]

    faults = pd.read_csv(RPI_RUN / "fault_injection_log.csv", parse_dates=["fault_start", "breach_time"])
    return tele, faults


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
    print("=== Loading RPi campaign ===")
    network_df, network_fault_log = load_rpi()
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
