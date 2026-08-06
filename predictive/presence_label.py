"""Multi-hot family presence labels (Phase-2 layer beside single-label Q2).

Answers: *which fault families are active on this window?*
Q2 remains: *which severity is dominant for the playbook?*

Skeleton GT for COMPOUND rows = recipe fault intent (not per-window physics).
Pinpoint L* rows: presence_Lk=1 iff root_label==k (and label!=0).
Does not overwrite canonical q2_windows.csv — write a sidecar.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .compound_label import FAULT_TO_ROOT

PRESENCE_FAMILIES: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
PRESENCE_COLS: tuple[str, ...] = tuple(f"presence_L{k}" for k in PRESENCE_FAMILIES)

# Extend map for L6 when present in recipes (not in FAULT_TO_ROOT today).
_FAULT_ROOT: dict[str, int] = {
    **FAULT_TO_ROOT,
    "ce_sla_conflict": 6,
    "ce_sla": 6,
    "rogue_ce": 6,
}


def presence_col(root: int) -> str:
    return f"presence_L{int(root)}"


def empty_presence_row() -> dict[str, int]:
    return {c: 0 for c in PRESENCE_COLS}


def roots_from_faults(faults: list[str]) -> set[int]:
    out: set[int] = set()
    for f in faults:
        r = _FAULT_ROOT.get(str(f).strip().lower())
        if r is not None:
            out.add(int(r))
    return out


def load_compound_faults(protocol_dir: Path) -> dict[str, list[str]]:
    """Map source_capture → recipe faults for COMPOUND/iter_*."""
    out: dict[str, list[str]] = {}
    for lab in sorted((protocol_dir / "COMPOUND").glob("iter_*/label.json")):
        key = f"COMPOUND/{lab.parent.name}"
        try:
            meta = json.loads(lab.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        faults = list((meta.get("recipe") or {}).get("faults") or [])
        if not faults and meta.get("faults"):
            faults = list(meta["faults"])
        out[key] = [str(f) for f in faults]
    return out


def attach_presence_labels(
    windows: pd.DataFrame,
    protocol_dir: Path | str,
) -> pd.DataFrame:
    """Return copy of windows with presence_L1..L6 columns."""
    proto = Path(protocol_dir)
    df = windows.copy()
    for c in PRESENCE_COLS:
        df[c] = 0

    compound_faults = load_compound_faults(proto)
    if "source_capture" not in df.columns:
        raise ValueError("attach_presence_labels needs source_capture")

    root = pd.to_numeric(df.get("root_label"), errors="coerce").fillna(0).astype(int)
    is_comp = pd.to_numeric(df.get("is_compound"), errors="coerce").fillna(0).astype(int)
    src = df["source_capture"].astype(str)

    # Pinpoint: one-hot from root_label
    pinpoint = is_comp.eq(0)
    for r in PRESENCE_FAMILIES:
        df.loc[pinpoint & root.eq(r), presence_col(r)] = 1

    # Compound: recipe multi-hot
    for key, faults in compound_faults.items():
        mask = src.eq(key)
        if not mask.any():
            continue
        for r in roots_from_faults(faults):
            if r in PRESENCE_FAMILIES:
                df.loc[mask, presence_col(r)] = 1

    return df


def quieter_root_for_compound(protocol_dir: Path, iter_name: str) -> dict[str, Any]:
    """Quieter family = min score_fault among recipe faults (series-level)."""
    from .compound_label import score_fault

    lab_path = protocol_dir / "COMPOUND" / iter_name / "label.json"
    series_path = protocol_dir / "COMPOUND" / iter_name / "series.csv"
    meta = json.loads(lab_path.read_text())
    faults = list((meta.get("recipe") or {}).get("faults") or [])
    dom = int((meta.get("dominant_label") or {}).get("root_label") or meta.get("label") or 0)
    scores: dict[str, float] = {}
    if series_path.exists():
        series = pd.read_csv(series_path)
        scores = {f: float(score_fault(series, f)) for f in faults}
    if scores:
        quiet_fault = min(scores, key=lambda k: scores[k])
    else:
        quiet_fault = faults[-1] if faults else None
    quiet_root = int(_FAULT_ROOT.get(str(quiet_fault or ""), 0))
    return {
        "iter": iter_name,
        "faults": faults,
        "scores": scores,
        "dominant_root": dom,
        "quieter_fault": quiet_fault,
        "quieter_root": quiet_root,
        "source_capture": f"COMPOUND/{iter_name}",
    }
