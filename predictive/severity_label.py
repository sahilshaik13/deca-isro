"""Severity segmentation for Q2 pinpoint faults.

Root labels 0–5 stay for Decide mapping; severity strings refine urgency:

  0   normal
  1A  rain early (10–18 ms GRE)
  1B  rain critical (19–24 ms)
  1C  rain breach (≥25 ms)
  2A  CPU moderate (Pi default 40–70% user; GNS3 may use fabric-native bands)
  2B  CPU severe (Pi ≥70% user; GNS3 fabric-native)
  3A  BGP mild flap rate
  3B  BGP severe flap rate
  4A  loss moderate (0.5–2% GRE)
  4B  loss breach (≥2% Payload SLA)
  5A  util elevated — CAPTURE_CONTRACT: scheduled ceil ∈ [0.5·end_mbit, end_mbit);
      Mbps fallback (no schedule): Pi 20–35 Mbps; GNS3 fabric-native
  5B  util near-ceil — CAPTURE_CONTRACT: scheduled ceil ≥ end_mbit (plateau/target);
      Mbps fallback (no schedule): Pi ≥35 Mbps; GNS3 fabric-native
      Absolute 35 Mbps is unreachable under honest payload-ceil residency (~34.5);
      schedule-sourced 5B is the contract-correct definition.
  6A  CE SLA conflict mild (Pi rogue util 10–18 Mbps; GNS3 fabric-native)
  6B  CE SLA conflict severe (Pi ≥18 Mbps; GNS3 fabric-native)

Windows take the *max* severity seen in the window (worst-case wins).
GNS3-native cuts: `severity_bands.fit_gns3_bands` — LABEL-TIME only, not inference remaps.
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
    """Instantaneous flaps/sec at 1 Hz (positive diff of cumulative flap count)."""
    v = series.astype(float).ffill().fillna(0.0)
    return v.diff().fillna(0.0).clip(lower=0.0)


# BGP flaps are bursty: many 1 Hz samples are 0 even during an active flap
# campaign. Instantaneous rate under-labels the phase as severity "0". A short
# rolling mean matches how operators (and Q2 windows) see the texture.
BGP_RATE_ROLL_SEC = 10


def _bgp_rate_smooth(series: pd.Series, roll_sec: int = BGP_RATE_ROLL_SEC) -> pd.Series:
    return _bgp_rate(series).rolling(int(roll_sec), min_periods=1).mean()


def label_rows(
    df: pd.DataFrame,
    root_label: int,
    *,
    bands: dict | None = None,
) -> pd.Series:
    """Per-row severity string given the campaign root label.

    Optional ``bands`` overrides CPU/util/CE cutpoints (GNS3-native fit).
    Latency/loss/BGP stay SLA-tied unless explicitly overridden in ``bands``.
    """
    from .severity_bands import PI_BANDS

    b = {**PI_BANDS, **(bands or {})}
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
        _bgp_rate_smooth(df["bgp_flap_count"])
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
        out[lat < float(b["lat_1a"])] = "0"
        out[(lat >= float(b["lat_1a"])) & (lat < float(b["lat_1b"]))] = "1A"
        out[(lat >= float(b["lat_1b"])) & (lat < float(b["lat_1c"]))] = "1B"
        out[lat >= float(b["lat_1c"])] = "1C"
    elif root_label == 2:
        out[:] = "0"
        out[(cpu >= float(b["cpu_2a"])) & (cpu < float(b["cpu_2b"]))] = "2A"
        out[cpu >= float(b["cpu_2b"])] = "2B"
    elif root_label == 3:
        out[:] = "0"
        out[(bgp_r >= float(b["bgp_3a"])) & (bgp_r < float(b["bgp_3b"]))] = "3A"
        out[bgp_r >= float(b["bgp_3b"])] = "3B"
    elif root_label == 4:
        out[:] = "0"
        out[(loss >= float(b["loss_4a"])) & (loss < float(b["loss_4b"]))] = "4A"
        out[loss >= float(b["loss_4b"])] = "4B"
    elif root_label == 5:
        from .util_schedule import (
            DEFAULT_5A_FRAC_OF_END,
            DEFAULT_5B_FRAC_OF_END,
            label_util_severity_from_schedule,
            series_has_util_schedule,
        )

        # Prefer schedule ceil vs end_mbit (CAPTURE_CONTRACT). Mbps bands are
        # legacy fallback only — do not retune util_5b from chaos confusion.
        if series_has_util_schedule(df):
            out = label_util_severity_from_schedule(
                df,
                frac_5a=float(b.get("util_5a_frac_of_end", DEFAULT_5A_FRAC_OF_END)),
                frac_5b=float(b.get("util_5b_frac_of_end", DEFAULT_5B_FRAC_OF_END)),
            )
        else:
            out[:] = "0"
            out[(util >= float(b["util_5a"])) & (util < float(b["util_5b"]))] = "5A"
            out[util >= float(b["util_5b"])] = "5B"
    elif root_label == 6:
        out[:] = "0"
        out[(util >= float(b["ce_6a"])) & (util < float(b["ce_6b"]))] = "6A"
        out[util >= float(b["ce_6b"])] = "6B"
    return out


def window_severity(row_severities: list[str]) -> str:
    """Worst severity in window by SEVERITY_ORDER index within same root family.

    Across mixed (shouldn't happen in pinpoint), pick global max order index.
    """
    if not row_severities:
        return "0"
    return max(row_severities, key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0)


def stamp_series(
    df: pd.DataFrame,
    root_label: int,
    *,
    bands: dict | None = None,
) -> pd.DataFrame:
    d = df.copy()
    d["severity"] = label_rows(d, root_label, bands=bands)
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
