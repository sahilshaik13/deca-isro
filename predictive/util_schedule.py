"""Util Q1 labeling — schedule-gated (CAPTURE_CONTRACT anti-confound).

eth0 TX can sit ~20–24 Mbps while HTB 1:15 ceil is still low (other classes on
the iface). Util TTI must NOT treat that as “approaching payload ceiling.”

Breach = first time scheduled ``htb_payload_ceil_mbps >= end_mbit``.
Usable util windows only when ``htb_payload_ceil_mbps >= usable_frac * end_mbit``.

Q2 util severity (5A/5B) under CAPTURE_CONTRACT is also schedule-sourced:
  5B = scheduled ceil has reached this inject's ``end_mbit`` (plateau / target)
  5A = scheduled ceil elevated (≥ ``5a_frac * end_mbit``) but not yet at end
Measured Mbps bands remain a no-schedule fallback only — post-contract payload
residency tops out ~34.5 Mbps, so an absolute ``util_5b=35`` cut never fires.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_USABLE_FRAC = 0.70
# Elevated-ramp floor as a fraction of this inject's end_mbit (not fabric root).
DEFAULT_5A_FRAC_OF_END = 0.50
# Near-ceil = at the inject target (plateau / final step).
DEFAULT_5B_FRAC_OF_END = 1.00
# Steady-state PE payload class ceil (lab/deca_htb_qos.sh ≈ 0.85 × 40 Mbit).
# Live-readable via `tc class show` / deca-htb-payload-ceil.sh — not inject-only.
NOMINAL_PAYLOAD_CEIL_MBPS = 34.0
# After last schedule log (plateau start), hold scheduled ceil this many seconds
# before reverting feature fill to nominal (inject restores class on EXIT).
SCHEDULE_FEATURE_HOLD_SEC = 120


def load_ceil_schedule(path: Path) -> pd.DataFrame:
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"empty util ceil schedule: {path}")
    df = pd.DataFrame(rows).sort_values("ts_unix").reset_index(drop=True)
    if "htb_payload_ceil_mbps" not in df.columns or "ts_unix" not in df.columns:
        raise ValueError(f"schedule missing required cols: {path}")
    return df


def attach_ceil_schedule(
    series: pd.DataFrame,
    schedule: pd.DataFrame,
    *,
    col: str = "htb_payload_ceil_mbps",
) -> pd.DataFrame:
    """Forward-fill scheduled payload ceil onto 1 Hz series rows."""
    out = series.sort_values("ts_unix").reset_index(drop=True).copy()
    # Drop prior ceil fills so re-attach (label then feature) does not create _x/_y.
    drop_cols = [c for c in (col, "util_end_mbit") if c in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    sch = schedule.sort_values("ts_unix")[["ts_unix", "htb_payload_ceil_mbps"]].copy()
    sch = sch.rename(columns={"htb_payload_ceil_mbps": col})
    merged = pd.merge_asof(
        out,
        sch,
        on="ts_unix",
        direction="backward",
    )
    # Before first schedule point: ceil unknown / pre-inject
    merged[col] = merged[col].fillna(0.0)
    if "end_mbit" in schedule.columns:
        end = float(schedule["end_mbit"].iloc[-1])
        merged["util_end_mbit"] = end
    return merged


def schedule_breach_ts(schedule: pd.DataFrame, end_mbit: float | None = None) -> int | None:
    """First unix ts where scheduled ceil reaches end_mbit (plateau / final step)."""
    end = float(end_mbit if end_mbit is not None else schedule["end_mbit"].iloc[-1])
    hit = schedule[schedule["htb_payload_ceil_mbps"].astype(float) >= end - 1e-6]
    if hit.empty:
        return None
    return int(hit["ts_unix"].iloc[0])


def series_has_util_schedule(df: pd.DataFrame) -> bool:
    return (
        "htb_payload_ceil_mbps" in df.columns
        and "util_end_mbit" in df.columns
        and df["htb_payload_ceil_mbps"].notna().any()
        and float(pd.to_numeric(df["util_end_mbit"], errors="coerce").fillna(0).max()) > 0
    )


def attach_ceil_for_features(
    series: pd.DataFrame,
    schedule: pd.DataFrame | None = None,
    *,
    nominal_mbps: float = NOMINAL_PAYLOAD_CEIL_MBPS,
    hold_sec: int = SCHEDULE_FEATURE_HOLD_SEC,
) -> pd.DataFrame:
    """Put live-parity ``htb_payload_ceil_mbps`` on a series for Q2 features.

    - With a schedule: use scheduled ceil only inside [first_ts, last_ts+hold];
      outside → nominal steady-state ceil (what ``tc class show`` returns idle).
    - Without a schedule: fill nominal everywhere.

    Labeling still uses ``attach_ceil_schedule`` (0 outside inject). Features must
    not see artificial 0 — that is not a live HTB reading.
    """
    out = series.sort_values("ts_unix").reset_index(drop=True).copy()
    nom = float(nominal_mbps)
    if schedule is None or schedule.empty:
        out["htb_payload_ceil_mbps"] = nom
        return out
    enriched = attach_ceil_schedule(out, schedule)
    t_lo = int(schedule["ts_unix"].min())
    t_hi = int(schedule["ts_unix"].max()) + int(hold_sec)
    ts = enriched["ts_unix"].astype(int)
    outside = (ts < t_lo) | (ts > t_hi)
    enriched.loc[outside, "htb_payload_ceil_mbps"] = nom
    enriched["htb_payload_ceil_mbps"] = (
        pd.to_numeric(enriched["htb_payload_ceil_mbps"], errors="coerce")
        .fillna(nom)
        .astype(float)
    )
    return enriched


def label_util_severity_from_schedule(
    df: pd.DataFrame,
    *,
    frac_5a: float = DEFAULT_5A_FRAC_OF_END,
    frac_5b: float = DEFAULT_5B_FRAC_OF_END,
) -> pd.Series:
    """Stamp 5A/5B from scheduled HTB payload ceil vs this inject's end_mbit.

    Split point is the injection schedule (known ceiling), not measured Mbps and
    not a score-driven cut. Requires columns from ``attach_ceil_schedule``.
    """
    n = len(df)
    out = pd.Series(["0"] * n, index=df.index, dtype=object)
    if not series_has_util_schedule(df):
        raise ValueError("label_util_severity_from_schedule needs htb_payload_ceil_mbps + util_end_mbit")
    ceil = pd.to_numeric(df["htb_payload_ceil_mbps"], errors="coerce").fillna(0.0).astype(float)
    end = pd.to_numeric(df["util_end_mbit"], errors="coerce").fillna(0.0).astype(float)
    # Guard against zero end (pre-attach rows): treat as unlabeled.
    valid = end > 0
    gate_5a = float(frac_5a) * end
    gate_5b = float(frac_5b) * end
    out.loc[valid & (ceil >= gate_5a) & (ceil < gate_5b - 1e-9)] = "5A"
    out.loc[valid & (ceil >= gate_5b - 1e-9)] = "5B"
    return out


def apply_util_label_gate(
    windows: pd.DataFrame,
    series_with_ceil: pd.DataFrame,
    *,
    end_mbit: float,
    usable_frac: float = DEFAULT_USABLE_FRAC,
    breach_ts: int | None = None,
) -> pd.DataFrame:
    """Recompute eta + label_usable using schedule breach and ceil gate.

    Expects windows from ``q1_windows.build_windows`` on util target; overwrites
    ``eta_seconds`` / ``label_usable`` for contract-correct util TTI.
    """
    if windows.empty:
        return windows
    out = windows.copy()
    if breach_ts is None:
        # derive from series column if present
        ceil = series_with_ceil["htb_payload_ceil_mbps"].astype(float)
        ts = series_with_ceil["ts_unix"].astype(int)
        hits = ts[ceil >= end_mbit - 1e-6]
        breach_ts = int(hits.iloc[0]) if len(hits) else None

    gate = float(usable_frac) * float(end_mbit)
    # map end_ts -> ceil at window end
    ceil_by_ts = series_with_ceil.set_index("ts_unix")["htb_payload_ceil_mbps"].astype(float)

    etas = []
    usable = []
    for _, row in out.iterrows():
        end_ts = int(row["end_ts"])
        c = float(ceil_by_ts.asof(end_ts)) if end_ts in ceil_by_ts.index or True else 0.0
        # asof via reindex
        try:
            c = float(ceil_by_ts.reindex(ceil_by_ts.index.union([end_ts])).sort_index().ffill().loc[end_ts])
        except Exception:
            c = 0.0
        if breach_ts is None or c < gate:
            etas.append(float(row.get("eta_seconds", 0.0)))
            usable.append(False)
            continue
        eta = float(max(0, breach_ts - end_ts))
        etas.append(eta)
        usable.append(end_ts <= breach_ts)
    out["eta_seconds"] = etas
    out["label_usable"] = usable
    out["util_label_mode"] = "schedule_gated"
    out["util_end_mbit"] = float(end_mbit)
    out["util_usable_ceil_gate"] = gate
    return out


def build_util_windows_contract(
    series: pd.DataFrame,
    schedule_path: Path,
    *,
    win: int = 30,
    stride: int = 5,
    usable_frac: float = DEFAULT_USABLE_FRAC,
) -> tuple[pd.DataFrame, dict]:
    """Build util Q1 windows with CAPTURE_CONTRACT schedule gating."""
    from .q1_windows import build_windows

    schedule = load_ceil_schedule(schedule_path)
    end_mbit = float(schedule["end_mbit"].iloc[-1])
    enriched = attach_ceil_schedule(series, schedule)
    # Unreachable eth0 SLA: raw util can sit ~20 Mbps while class ceil is still
    # 5–18 Mbit; an eth0 threshold would cull (or falsely label) early windows.
    # Keep all pre-end windows; rewrite ETA / usable via schedule gate below.
    windows, meta = build_windows(
        enriched,
        win=win,
        stride=stride,
        sla=1e9,
        target_col="util_gre_mbps",
    )
    breach_ts = schedule_breach_ts(schedule, end_mbit)
    windows = apply_util_label_gate(
        windows,
        enriched,
        end_mbit=end_mbit,
        usable_frac=usable_frac,
        breach_ts=breach_ts,
    )
    usable = windows[windows["label_usable"] == True] if not windows.empty else windows  # noqa: E712
    meta.update(
        {
            "util_label_mode": "schedule_gated",
            "util_end_mbit": end_mbit,
            "util_usable_frac": usable_frac,
            "util_breach_ts": breach_ts,
            "n_train_windows_gated": int(len(usable)),
            "schedule": str(schedule_path),
        }
    )
    return windows, meta
