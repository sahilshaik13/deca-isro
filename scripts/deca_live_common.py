#!/usr/bin/env python3
"""Shared helpers for the DECA blind live-network test.

The blind test has three actors that must agree on a handful of primitives:

- ``deca_blind_chaos.py``   — randomly stresses the lab against a sealed truth.
- ``deca_live_operator.py`` — polls Prometheus, runs the models, streams alerts.
- ``deca_blind_scorecard.py`` — reconciles what the net did vs what was caught.

This module owns the things all three need to define **identically** so the
comparison is honest: the Prometheus queries, how raw telemetry is shaped into
the long form the training pipeline expects, the physical-severity definition,
and the on-disk layout of a live run. Nothing here loads a model or TensorFlow,
so the scorecard can import it without paying that cost.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from _paths import RPI_NET_DIR

# ── Lab wiring (mirror of deca_fault_campaign.py) ─────────────────────────
PROMETHEUS_RANGE_URL = "http://localhost:9090/api/v1/query_range"
PROMETHEUS_STEP_SECONDS = 15

# Same PromQL the campaign export uses — raw metric names are renamed into the
# model's feature vocabulary by rebuild_unified.METRIC_MAP downstream.
PROM_QUERIES: dict[str, str] = {
    "throughput_in_bps": 'sum by (host) (rate(net_bytes_recv{interface="eth0"}[1m]))',
    "throughput_out_bps": 'sum by (host) (rate(net_bytes_sent{interface="eth0"}[1m]))',
    "packet_loss_pct": "avg by (host) (ping_percent_packet_loss)",
    "jitter_ms": "avg by (host) (ping_standard_deviation_ms)",
    "latency_ms": "avg by (host) (ping_average_response_ms)",
    "drop_out_rate": 'sum by (host) (rate(net_drop_out{interface="eth0"}[1m]))',
    # Tier 5 — orthogonal control-plane fingerprint (docs/TIER5_VRF_ROUTE_COUNT.md).
    # vrf-admin route count on station2; a wrong-RT import (vrf_leakage) inflates
    # it regardless of how loud a co-occurring PE1 tunnel/congestion fault is.
    # Prometheus series is "vrf_route_count_value" (Telegraf suffixes the exec
    # field name "value" onto name_override) — confirmed live on :9273.
    "vrf_route_count": 'max by (host) (vrf_route_count_value{vrf="vrf-admin"})',
    # Tier 5b — live control-plane fingerprint for bgp_route_flap (docs/DECA_ROI_TIERS.md
    # Tier 5). Diagnosed 2026-07-21: bgp_route_flap's only prior signal was a fabricated
    # stamp_bgp_update_pulse() scalar with no live scrape — the anomaly gate barely
    # separated it from healthy (p(anom)=0.52 vs 0.74-0.86 for every other fault).
    # `clear bgp soft` (the injector's actual command) is a route-refresh, not a
    # session reset, so connectionsDropped never moves; routeRefreshSent+Recv from
    # `show bgp neighbor 10.1.3.1 json` on station1 does (verified live). Prometheus
    # series is "bgp_flap_count_value" (same Telegraf exec "value" suffix as VRF).
    "bgp_flap_count": 'max by (host) (bgp_flap_count_value{neighbor="10.1.3.1"})',
}

# Which physical host runs each fault (from deca_fault_campaign injectors):
# congestion/tunnel/bgp stress PE1 (station1); vrf leak stresses PE2 (station2).
FAULT_HOST = {
    "congestion_breach": "station1",
    "tunnel_degradation": "station1",
    "bgp_route_flap": "station1",
    "vrf_leakage": "station2",
    "precursor_aborted": "station1",
    "near_miss": "station1",
}

SEVERITY_BUCKETS = ("low", "medium", "high")


# ── Live run layout ───────────────────────────────────────────────────────
def live_run_dir(run_id: str) -> Path:
    """Directory for one blind run under data/rpi-net/live/<run_id>/."""
    d = RPI_NET_DIR / "live" / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def ground_truth_path(run_id: str) -> Path:
    """Sealed truth. The operator MUST NOT read this — that is the whole point."""
    return live_run_dir(run_id) / "ground_truth.sealed.jsonl"


def declarations_path(run_id: str) -> Path:
    """Everything the model declared, appended live by the operator."""
    return live_run_dir(run_id) / "declarations.jsonl"


def bgp_pulses_path(run_id: str) -> Path:
    """BGP update-rate telemetry (a real signal, not a label) the operator merges."""
    return live_run_dir(run_id) / "bgp_update_samples.csv"


def run_meta_path(run_id: str) -> Path:
    return live_run_dir(run_id) / "run_meta.json"


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Prometheus ──────────────────────────────────────────────────────────────
def query_range(promql: str, start: datetime, end: datetime, *, step: int = PROMETHEUS_STEP_SECONDS,
                timeout: int = 60) -> list[dict[str, Any]]:
    """Run one range query; return Prometheus ``result`` list (empty on failure)."""
    import requests

    try:
        resp = requests.get(
            PROMETHEUS_RANGE_URL,
            params={
                "query": promql,
                "start": int(start.timestamp()),
                "end": int(end.timestamp()),
                "step": str(step),
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return []
    if payload.get("status") != "success":
        return []
    return payload.get("data", {}).get("result", [])


def fetch_telemetry_long(start: datetime, end: datetime, *, step: int = PROMETHEUS_STEP_SECONDS):
    """Pull all PROM_QUERIES over [start, end] into a long-form DataFrame.

    Columns: timestamp (UTC), host, metric (raw name), value. Empty frame when
    Prometheus is unreachable or has no samples in the window.
    """
    import pandas as pd

    rows = []
    for metric_name, promql in PROM_QUERIES.items():
        for series in query_range(promql, start, end, step=step):
            host = series.get("metric", {}).get("host", "unknown")
            for ts, val in series.get("values", []):
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                if v != v:  # NaN
                    continue
                rows.append(
                    {
                        "timestamp": datetime.fromtimestamp(float(ts), tz=timezone.utc),
                        "host": host,
                        "metric": metric_name,
                        "value": v,
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "host", "metric", "value"])
    return pd.DataFrame(rows)


def load_bgp_pulses(run_id: str, start: datetime, end: datetime):
    """Read the chaos-stamped bgp_update_rate pulses (telemetry) within the window."""
    import pandas as pd

    path = bgp_pulses_path(run_id)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=["timestamp", "host", "metric", "value"])
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["timestamp", "value"])
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    return df[["timestamp", "host", "metric", "value"]]


def densify_bgp_pulses(bgp_long, raw_long, *, step_seconds: int = PROMETHEUS_STEP_SECONDS):
    """Expand sparse flap pulses onto the Prom 15s grid (0 = no flap).

    ``engineer_features`` dropna's on *all* feature columns. A host that only has
    a handful of stamped ``bgp_update_rate`` pulses otherwise gets mostly-NaN BGP
    feature columns, and the dropna wipes that host's *entire* frame (station1
    vanishing mid-flap on the live operator). Densifying with an explicit zero
    baseline matches the telemetry meaning: no pulse stamped ⇒ update rate 0.

    Calm / control path: when *no* pulses were stamped at all, still emit a zero
    grid for every host present in ``raw_long``. Skipping densify on empty
    ``bgp_long`` leaves BGP feature columns absent → NaN after ``reindex`` → the
    classifier invents ``bgp_route_flap`` on healthy baselines (control cry-wolf).
    """
    import pandas as pd

    empty = pd.DataFrame(columns=["timestamp", "host", "metric", "value"])
    if raw_long is None or len(raw_long) == 0:
        # No Prom grid to densify onto — keep sparse pulses if any.
        if bgp_long is None or len(bgp_long) == 0:
            return empty
        return bgp_long.copy()

    if bgp_long is None or len(bgp_long) == 0:
        bgp_long = empty

    hosts = set(raw_long["host"].astype(str).unique()) | set(
        bgp_long["host"].astype(str).unique() if len(bgp_long) else []
    )
    rows = []
    for host in sorted(hosts):
        pulses = bgp_long[bgp_long["host"].astype(str) == host] if len(bgp_long) else empty
        host_raw = raw_long[raw_long["host"].astype(str) == host]
        if len(host_raw) == 0:
            # No Prom series for this host in-window — keep sparse pulses as-is.
            if len(pulses):
                rows.append(pulses)
            continue
        t0 = host_raw["timestamp"].min().floor(f"{step_seconds}s")
        t1 = host_raw["timestamp"].max().ceil(f"{step_seconds}s")
        grid = pd.date_range(t0, t1, freq=f"{step_seconds}s", tz=timezone.utc)
        series = pd.Series(0.0, index=grid, dtype=float)
        for _, p in pulses.iterrows():
            # Snap each pulse to the nearest grid bin (max if several land in one).
            ts = pd.Timestamp(p["timestamp"]).tz_convert(timezone.utc)
            snap = ts.round(f"{step_seconds}s")
            if snap < grid[0] or snap > grid[-1]:
                continue
            series.loc[snap] = max(float(series.loc[snap]), float(p["value"]))
        rows.append(
            pd.DataFrame(
                {
                    "timestamp": series.index,
                    "host": host,
                    "metric": "bgp_update_rate",
                    "value": series.values,
                }
            )
        )
    return pd.concat(rows, ignore_index=True) if rows else empty


def bgp_pulse_evidence(bgp_long, *, eps: float = 0.0) -> dict[str, bool]:
    """Per-host: True iff any stamped ``bgp_update_rate`` pulse exceeds ``eps``.

    Used by the live operator as a hard evidence gate: do not *confirm*
    ``bgp_route_flap`` when the lab stamped zero BGP activity in-window. Advisory
    may still flicker; confirmed alarms require telemetry that a flap occurred.
    """
    out: dict[str, bool] = {}
    if bgp_long is None or len(bgp_long) == 0:
        return out
    for host, pulses in bgp_long.groupby(bgp_long["host"].astype(str)):
        vals = pulses["value"].astype(float)
        out[str(host)] = bool((vals > eps).any())
    return out


# ── Physical severity (model-side + ground-truth-side, one definition) ────────
@dataclass
class Severity:
    score: float
    bucket: str
    detail: dict[str, float]


def _pct(series, q: float, default: float = 0.0) -> float:
    try:
        v = float(series.quantile(q))
        return v if v == v else default
    except Exception:
        return default


def physical_severity(window_df, *, recent_seconds: int = 120) -> Severity | None:
    """Score physical impact from a per-host telemetry window (raw metric names).

    ``window_df`` is long-form (timestamp, metric, value) for a **single host**.
    Severity is how far the recent state deviates from a robust healthy baseline
    drawn from the same window, taken as the worst of three channels:

    - packet loss (absolute; ~5% ≈ score 1.0)
    - jitter / latency rise above baseline (~30 ms ≈ 1.0)
    - throughput collapse below baseline (fractional drop; 100% drop ≈ 1.0)

    Bucketed low / medium / high. Both the operator (live, at declaration time)
    and the scorecard (over the actual breach window) call this identically, so
    "what severity did the model expect" and "what actually happened" are on the
    same ruler. Returns ``None`` when the window has no usable telemetry.
    """
    import pandas as pd

    if window_df is None or len(window_df) == 0:
        return None
    window_df = window_df.copy()
    window_df["timestamp"] = pd.to_datetime(window_df["timestamp"], utc=True, errors="coerce")
    t_end = window_df["timestamp"].max()
    if pd.isna(t_end):
        return None
    recent_cut = t_end - pd.Timedelta(seconds=recent_seconds)

    def channel(metric: str):
        s = window_df.loc[window_df["metric"] == metric].sort_values("timestamp")
        if s.empty:
            return None, None
        recent = s.loc[s["timestamp"] >= recent_cut, "value"]
        recent_val = float(recent.mean()) if len(recent) else float(s["value"].iloc[-1])
        return s["value"], recent_val

    detail: dict[str, float] = {}

    loss_series, loss_now = channel("packet_loss_pct")
    loss_dev = 0.0
    if loss_now is not None:
        loss_dev = max(loss_now, 0.0) / 5.0
        detail["loss_pct"] = round(loss_now, 3)

    jit_series, jit_now = channel("jitter_ms")
    jit_dev = 0.0
    if jit_now is not None and jit_series is not None:
        base = _pct(jit_series, 0.20, default=jit_now)
        jit_dev = max(jit_now - base, 0.0) / 30.0
        detail["jitter_ms"] = round(jit_now, 3)
        detail["jitter_base_ms"] = round(base, 3)

    # Throughput collapse — use inbound octets/bps (either raw name may be present)
    tput_dev = 0.0
    for metric in ("throughput_in_bps", "ifInOctets"):
        tp_series, tp_now = channel(metric)
        if tp_now is not None and tp_series is not None:
            base = _pct(tp_series, 0.80, default=tp_now)
            if base > 1e-6:
                tput_dev = max(base - tp_now, 0.0) / base
                detail["tput_now"] = round(tp_now, 1)
                detail["tput_base"] = round(base, 1)
            break

    score = max(loss_dev, jit_dev, tput_dev, 0.0)
    if score >= 0.75:
        bucket = "high"
    elif score >= 0.33:
        bucket = "medium"
    else:
        bucket = "low"
    detail["loss_dev"] = round(loss_dev, 3)
    detail["jitter_dev"] = round(jit_dev, 3)
    detail["tput_dev"] = round(tput_dev, 3)
    return Severity(score=round(score, 3), bucket=bucket, detail=detail)


def _selfcheck_densify() -> None:
    """Offline asserts for the calm-path densify + evidence gate (no Prom)."""
    import pandas as pd

    t0 = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc)
    raw_rows = []
    for k in range(20):
        ts = t0 + timedelta(seconds=15 * k)
        for host in ("station1", "station2"):
            raw_rows.append(
                {"timestamp": ts, "host": host, "metric": "packet_loss_pct", "value": 0.0}
            )
    raw = pd.DataFrame(raw_rows)
    empty_bgp = pd.DataFrame(columns=["timestamp", "host", "metric", "value"])

    dense = densify_bgp_pulses(empty_bgp, raw)
    assert len(dense) > 0, "calm path must emit a zero BGP grid"
    assert set(dense["host"].unique()) == {"station1", "station2"}
    assert float(dense["value"].max()) == 0.0
    assert (dense["metric"] == "bgp_update_rate").all()

    # Sparse pulse overlays on the zero grid.
    pulse = pd.DataFrame(
        [
            {
                "timestamp": t0 + timedelta(seconds=60),
                "host": "station1",
                "metric": "bgp_update_rate",
                "value": 12.0,
            }
        ]
    )
    dense2 = densify_bgp_pulses(pulse, raw)
    s1 = dense2[dense2["host"] == "station1"]["value"]
    assert float(s1.max()) == 12.0
    assert float(dense2[dense2["host"] == "station2"]["value"].max()) == 0.0

    assert bgp_pulse_evidence(empty_bgp) == {}
    assert bgp_pulse_evidence(pulse) == {"station1": True}
    print("deca_live_common densify/evidence selfcheck: OK")


if __name__ == "__main__":
    import sys

    if "--selfcheck" in sys.argv:
        _selfcheck_densify()
    else:
        print("Usage: python scripts/deca_live_common.py --selfcheck")
