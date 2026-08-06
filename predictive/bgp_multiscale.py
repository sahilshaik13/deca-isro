"""BGP multi-scale texture features (Phase-2 candidate — beside 10s label roll).

Derived from cumulative ``bgp_flap_count`` at 1 Hz (positive diffs only):

- ``bgp_rate_{5,30,60}s`` — rolling mean flaps/s (multi-horizon texture)
- ``bgp_time_since_flap`` — seconds since last positive flap step (cap 600)
- ``bgp_burst_len`` — run length of consecutive positive-rate samples

Does not change severity labels (still 10s roll in severity_label) or promoted Q2.
Offline validation: ``python -m predictive.eval_bgp_multiscale``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RATE_WINDOWS: tuple[int, ...] = (5, 30, 60)
TIME_SINCE_CAP_SEC = 600.0

# Series columns attached by attach_bgp_multiscale
SERIES_COLS: tuple[str, ...] = (
    "bgp_rate_5s",
    "bgp_rate_30s",
    "bgp_rate_60s",
    "bgp_time_since_flap",
    "bgp_burst_len",
)

# Window aggregations produced by summarize_bgp_multiscale_window
WINDOW_FEAT_COLS: tuple[str, ...] = (
    "bgp_rate_5s_mean",
    "bgp_rate_5s_max",
    "bgp_rate_30s_mean",
    "bgp_rate_30s_max",
    "bgp_rate_60s_mean",
    "bgp_rate_60s_max",
    "bgp_time_since_flap_last",
    "bgp_time_since_flap_min",
    "bgp_burst_len_max",
    "bgp_burst_len_last",
)

# Existing Q2 BGP rate features (baseline for ablation)
BASELINE_BGP_FEATS: tuple[str, ...] = (
    "bgp_flap_count_delta",
    "bgp_flap_count_slope",
    "bgp_flap_count_rate_mean",
    "bgp_flap_count_rate_std",
    "bgp_flap_count_rate_max",
)


def instant_flap_rate(count: pd.Series) -> pd.Series:
    """Positive 1 Hz flap steps (counter resets → 0, not large negatives)."""
    v = pd.to_numeric(count, errors="coerce").ffill().fillna(0.0)
    return v.diff().fillna(0.0).clip(lower=0.0)


def time_since_last_flap(rate: pd.Series, *, cap: float = TIME_SINCE_CAP_SEC) -> pd.Series:
    """Seconds since last positive flap; grows by 1 each quiet sample; capped."""
    r = rate.to_numpy(dtype=float)
    out = np.empty(len(r), dtype=float)
    t = cap
    for i, x in enumerate(r):
        if x > 0:
            t = 0.0
        else:
            t = min(cap, t + 1.0)
        out[i] = t
    return pd.Series(out, index=rate.index)


def burst_length(rate: pd.Series) -> pd.Series:
    """Current consecutive positive-rate run length (0 when quiet)."""
    r = rate.to_numpy(dtype=float)
    out = np.zeros(len(r), dtype=float)
    run = 0
    for i, x in enumerate(r):
        if x > 0:
            run += 1
        else:
            run = 0
        out[i] = float(run)
    return pd.Series(out, index=rate.index)


def attach_bgp_multiscale(df: pd.DataFrame, *, count_col: str = "bgp_flap_count") -> pd.DataFrame:
    """Return copy with multi-scale BGP series columns. No-op columns if count missing."""
    out = df.copy()
    if count_col not in out.columns:
        for c in SERIES_COLS:
            out[c] = 0.0
        return out
    rate1 = instant_flap_rate(out[count_col])
    for w in RATE_WINDOWS:
        out[f"bgp_rate_{w}s"] = rate1.rolling(int(w), min_periods=1).mean()
    out["bgp_time_since_flap"] = time_since_last_flap(rate1)
    out["bgp_burst_len"] = burst_length(rate1)
    return out


def summarize_bgp_multiscale_window(sl: pd.DataFrame) -> dict[str, float]:
    """Aggregate multi-scale series cols over a window slice → feature dict."""
    feat: dict[str, float] = {}
    for w in RATE_WINDOWS:
        col = f"bgp_rate_{w}s"
        if col not in sl.columns:
            feat[f"{col}_mean"] = 0.0
            feat[f"{col}_max"] = 0.0
            continue
        vals = pd.to_numeric(sl[col], errors="coerce").fillna(0.0).to_numpy()
        feat[f"{col}_mean"] = float(np.mean(vals))
        feat[f"{col}_max"] = float(np.max(vals))
    if "bgp_time_since_flap" in sl.columns:
        ts = pd.to_numeric(sl["bgp_time_since_flap"], errors="coerce").fillna(TIME_SINCE_CAP_SEC)
        feat["bgp_time_since_flap_last"] = float(ts.iloc[-1])
        feat["bgp_time_since_flap_min"] = float(ts.min())  # most recent flap in window
    else:
        feat["bgp_time_since_flap_last"] = TIME_SINCE_CAP_SEC
        feat["bgp_time_since_flap_min"] = TIME_SINCE_CAP_SEC
    if "bgp_burst_len" in sl.columns:
        b = pd.to_numeric(sl["bgp_burst_len"], errors="coerce").fillna(0.0)
        feat["bgp_burst_len_max"] = float(b.max())
        feat["bgp_burst_len_last"] = float(b.iloc[-1])
    else:
        feat["bgp_burst_len_max"] = 0.0
        feat["bgp_burst_len_last"] = 0.0
    return feat
