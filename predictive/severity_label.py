"""Severity segmentation for Q2 pinpoint faults.

Root labels 0–5 stay for Decide mapping; severity strings refine urgency:

  0   normal
  1A  rain early (10–18 ms GRE)
  1B  rain critical (19–24 ms)
  1C  rain breach (≥25 ms)
  2A  CPU moderate (40–70% user)
  2B  CPU severe (≥70% user)
  3A  BGP mild flap rate
  3B  BGP severe flap rate
  4A  loss moderate (0.5–2% GRE)
  4B  loss breach (≥2% Payload SLA)
  5A  util elevated (20–35 Mbps GRE through HTB)
  5B  util near-ceil (≥35 Mbps → root 40 Mbit)
  6A  CE SLA conflict mild (rogue util 10–18 Mbps)
  6B  CE SLA conflict severe (rogue util ≥18 Mbps)

Windows take the *max* severity seen in the window (worst-case wins).
New 4*/5*/6* codes are appended so existing 0–3B id encoding stays stable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Ordered severity within each root class (higher index = worse)
SEVERITY_ORDER = [
    "0",
    "1A",
    "1B",
    "1C",
    "2A",
    "2B",
    "3A",
    "3B",
    "4A",
    "4B",
    "5A",
    "5B",
    "6A",
    "6B",
]

SEVERITY_TO_ROOT = {
    "0": 0,
    "1A": 1,
    "1B": 1,
    "1C": 1,
    "2A": 2,
    "2B": 2,
    "3A": 3,
    "3B": 3,
    "4A": 4,
    "4B": 4,
    "5A": 5,
    "5B": 5,
    "6A": 6,
    "6B": 6,
}

SEVERITY_NAMES = {
    "0": "normal",
    "1A": "physical_early",
    "1B": "physical_critical",
    "1C": "physical_breach",
    "2A": "cpu_moderate",
    "2B": "cpu_severe",
    "3A": "bgp_mild",
    "3B": "bgp_severe",
    "4A": "loss_moderate",
    "4B": "loss_breach",
    "5A": "util_elevated",
    "5B": "util_near_ceil",
    "6A": "ce_sla_mild",
    "6B": "ce_sla_severe",
}

# Red-gate severities (HITL) — plan §3 + PS13 loss/util breach
RED_SEVERITIES = frozenset({"1B", "1C", "2B", "3B", "4B", "5B", "6B"})

# Encode for XGBoost integer classes
SEVERITY_TO_ID = {s: i for i, s in enumerate(SEVERITY_ORDER)}
ID_TO_SEVERITY = {i: s for s, i in SEVERITY_TO_ID.items()}


def _bgp_rate(series: pd.Series) -> pd.Series:
    v = series.astype(float).ffill().fillna(0.0)
    return v.diff().fillna(0.0).clip(lower=0.0)


def label_rows(df: pd.DataFrame, root_label: int) -> pd.Series:
    """Per-row severity string given the campaign root label."""
    n = len(df)
    out = pd.Series(["0"] * n, index=df.index, dtype=object)
    if root_label == 0:
        return out

    lat = df["latency_gre_ms"].astype(float) if "latency_gre_ms" in df.columns else pd.Series(0.0, index=df.index)
    cpu = (
        df["cpu_usage_user"].astype(float)
        if "cpu_usage_user" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    bgp_r = (
        _bgp_rate(df["bgp_flap_count"])
        if "bgp_flap_count" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    loss = (
        df["loss_gre_pct"].astype(float)
        if "loss_gre_pct" in df.columns
        else pd.Series(0.0, index=df.index)
    )
    util = (
        df["util_gre_mbps"].astype(float)
        if "util_gre_mbps" in df.columns
        else pd.Series(0.0, index=df.index)
    )

    if root_label == 1:
        out[:] = "1A"
        out[lat < 10] = "0"  # still quiet within rain campaign baseline
        out[(lat >= 10) & (lat < 19)] = "1A"
        out[(lat >= 19) & (lat < 25)] = "1B"
        out[lat >= 25] = "1C"
    elif root_label == 2:
        out[:] = "0"
        out[(cpu >= 40) & (cpu < 70)] = "2A"
        out[cpu >= 70] = "2B"
    elif root_label == 3:
        # rate in flaps/sec over 1 Hz samples; mild vs severe
        out[:] = "0"
        out[(bgp_r >= 0.2) & (bgp_r < 1.0)] = "3A"
        out[bgp_r >= 1.0] = "3B"
    elif root_label == 4:
        out[:] = "0"
        out[(loss >= 0.5) & (loss < 2.0)] = "4A"
        out[loss >= 2.0] = "4B"
    elif root_label == 5:
        out[:] = "0"
        out[(util >= 20.0) & (util < 35.0)] = "5A"
        out[util >= 35.0] = "5B"
    elif root_label == 6:
        # CE SLA conflict: bronze rogue surge visible as util_gre_mbps / ce gauges
        out[:] = "0"
        out[(util >= 10.0) & (util < 18.0)] = "6A"
        out[util >= 18.0] = "6B"
    return out


def window_severity(row_severities: list[str]) -> str:
    """Worst severity in window by SEVERITY_ORDER index within same root family.

    Across mixed (shouldn't happen in pinpoint), pick global max order index.
    """
    if not row_severities:
        return "0"
    return max(row_severities, key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0)


def stamp_series(df: pd.DataFrame, root_label: int) -> pd.DataFrame:
    d = df.copy()
    d["severity"] = label_rows(d, root_label)
    d["severity_name"] = d["severity"].map(SEVERITY_NAMES)
    d["root_label"] = root_label
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True)
    ap.add_argument("--root-label", type=int, required=True, choices=[0, 1, 2, 3, 4, 5, 6])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.capture)
    out = stamp_series(df, args.root_label)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    counts = out["severity"].value_counts().to_dict()
    print(json.dumps({"wrote": str(path), "counts": counts}, indent=2))


if __name__ == "__main__":
    main()
