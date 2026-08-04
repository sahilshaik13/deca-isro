"""Dominant root-label for compound captures (single-class Q2).

Compound injects overlap several faults; XGBoost still needs one root label.
Policy: score each fault's primary Prom signature and pick the max
(normalized to SLA / full-scale). Windows are tagged ``is_compound=1``.
Not multi-label — see alert_fusion / chaos_compound honesty.
"""
from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

FAULT_TO_ROOT: dict[str, int] = {
    "rain_fade": 1,
    "cpu_stress": 2,
    "bgp_flap": 3,
    "loss_progression": 4,
    "util_congestion": 5,
}


def _col_max(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or df.empty:
        return 0.0
    s = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return float(s.max()) if len(s) else 0.0


def score_fault(df: pd.DataFrame, fault: str) -> float:
    """Normalized score in ~[0, ∞); ≥1 means at/above SLA-ish full scale."""
    f = (fault or "").strip().lower()
    if f == "rain_fade":
        return _col_max(df, "latency_gre_ms") / 25.0
    if f == "cpu_stress":
        return _col_max(df, "cpu_usage_user") / 100.0
    if f == "bgp_flap":
        if "bgp_flap_count" not in df.columns or df.empty:
            return 0.0
        s = pd.to_numeric(df["bgp_flap_count"], errors="coerce").fillna(0.0)
        return float(max(0.0, s.max() - s.iloc[0])) / 10.0
    if f == "loss_progression":
        return _col_max(df, "loss_gre_pct") / 2.0
    if f == "util_congestion":
        return _col_max(df, "util_gre_mbps") / 35.0
    return 0.0


def dominant_root_label(
    df: pd.DataFrame,
    faults: Iterable[str],
    *,
    fallback: int = 1,
) -> tuple[int, dict[str, Any]]:
    """Return (root_label, debug) for compound series."""
    flist = [str(f).strip() for f in faults if str(f).strip()]
    scores = {f: score_fault(df, f) for f in flist}
    if not scores:
        return fallback, {"scores": {}, "picked_fault": None}
    picked = max(scores, key=lambda k: scores[k])
    # tie / all flat → first recipe fault
    if scores[picked] <= 0 and flist:
        picked = flist[0]
    root = FAULT_TO_ROOT.get(picked, fallback)
    return root, {"scores": scores, "picked_fault": picked, "root_label": root}
