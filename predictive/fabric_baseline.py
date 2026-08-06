"""Fabric idle-baseline + util-%-of-ceiling normalization for Q2 features.

Pi vs GNS3 idle economies differ sharply (e.g. GRE latency ~0.3ms vs ~8ms).
Training on raw absolutes teaches Pi idle as "normal"; the quieter twin then
looks anomalous before any fault. Subtract (or z-score) each fabric's own L0
idle so features are *delta-from-idle* / *z-vs-idle*.

Util Mbps can also be expressed as a fraction of the fabric HTB ceiling
(applied PE WAN rate — currently 40 Mbit on both Pi and GNS3 twin) so
"near-ceil" lines up across fabrics without rewriting severity labels.

Severity labels stay on absolute series — this module is feature-only.
"""
from __future__ import annotations

import json
from glob import glob
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .q2_windows import CUMULATIVE_COLS, FEATURE_COLS

# Level channels only — rates/deltas of cumulatives are already relative.
IDLE_LEVEL_COLS = [c for c in FEATURE_COLS if c not in CUMULATIVE_COLS]

# Floor for z-score when L0 is flat (GNS3 gauge-theater std≈0).
_STD_FLOOR = 1e-3

# Applied HTB root rates (lab/*/apply_sla_htb.sh) — not aspirational SLA.md WAN maps.
FABRIC_UTIL_CEIL_MBPS: dict[str, float] = {
    "pi": 40.0,
    "gns3": 40.0,
}

UTIL_FEATURE_COLS = ("util_gre_mbps",)


def fabric_util_ceiling_mbps(fabric: str | None = None, override: float | None = None) -> float:
    if override is not None and float(override) > 0:
        return float(override)
    fab = (fabric or "pi").strip().lower()
    return float(FABRIC_UTIL_CEIL_MBPS.get(fab, FABRIC_UTIL_CEIL_MBPS["pi"]))


def util_ceiling_meta(fabric: str, ceil_mbps: float) -> dict[str, Any]:
    return {
        "mode": "pct_ceil",
        "fabric": fabric,
        "ceil_mbps": float(ceil_mbps),
        "cols": list(UTIL_FEATURE_COLS),
        "note": "feature-only; severity labels remain absolute Mbps",
    }


def apply_util_ceiling_df(
    df: pd.DataFrame,
    ceil_mbps: float,
    *,
    cols: tuple[str, ...] | list[str] = UTIL_FEATURE_COLS,
) -> pd.DataFrame:
    """Divide util Mbps cols by fabric ceiling → fraction of ceil (copy)."""
    if ceil_mbps <= 0:
        raise ValueError(f"util ceiling must be >0, got {ceil_mbps}")
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            continue
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float) / float(ceil_mbps)
    return out


def apply_util_ceiling_sample(
    sample: dict[str, float],
    ceil_mbps: float,
    *,
    cols: tuple[str, ...] | list[str] = UTIL_FEATURE_COLS,
) -> dict[str, float]:
    if ceil_mbps <= 0:
        return dict(sample)
    out = dict(sample)
    for c in cols:
        if c not in out:
            continue
        try:
            out[c] = float(out[c] or 0.0) / float(ceil_mbps)
        except (TypeError, ValueError):
            out[c] = 0.0
    return out


def find_l0_series(protocol_dir: Path) -> list[Path]:
    root = Path(protocol_dir).resolve()
    paths = sorted(Path(p) for p in glob(str(root / "L0_normal" / "iter_*" / "series.csv")))
    paths += sorted(Path(p) for p in glob(str(root / "L0_normal" / "**/series.csv")))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p in seen or any(part.startswith("_") for part in p.parts):
            continue
        seen.add(p)
        out.append(p)
    return out


def fit_idle_baseline(
    frames: list[pd.DataFrame],
    *,
    cols: list[str] | None = None,
) -> dict[str, Any]:
    """Fit per-column idle mean/std from L0 frames."""
    use = cols or IDLE_LEVEL_COLS
    if not frames:
        raise ValueError("no L0 frames to fit idle baseline")
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    ns: dict[str, int] = {}
    for c in use:
        vals: list[np.ndarray] = []
        for df in frames:
            if c not in df.columns:
                continue
            v = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            if len(v):
                vals.append(v)
        if not vals:
            continue
        cat = np.concatenate(vals)
        means[c] = float(np.mean(cat))
        stds[c] = float(max(float(np.std(cat)), _STD_FLOOR))
        ns[c] = int(len(cat))
    return {
        "mode": "delta",  # default; caller may override
        "cols": sorted(means.keys()),
        "mean": means,
        "std": stds,
        "n": ns,
        "std_floor": _STD_FLOOR,
    }


def fit_idle_baseline_from_protocol(protocol_dir: Path) -> dict[str, Any]:
    from .preprocess import align_1hz, ema_smooth

    paths = find_l0_series(protocol_dir)
    if not paths:
        raise FileNotFoundError(f"no L0_normal series under {protocol_dir}")
    frames = [ema_smooth(align_1hz(pd.read_csv(p))) for p in paths]
    bl = fit_idle_baseline(frames)
    bl["protocol_dir"] = str(Path(protocol_dir).resolve())
    bl["l0_sources"] = [str(p) for p in paths]
    return bl


def apply_idle_baseline(
    df: pd.DataFrame,
    baseline: dict[str, Any],
    *,
    mode: str | None = None,
) -> pd.DataFrame:
    """Return copy with level cols transformed; cumulatives untouched."""
    mode = (mode or baseline.get("mode") or "delta").lower()
    if mode in ("none", "off", ""):
        return df.copy()
    out = df.copy()
    means = baseline.get("mean") or {}
    stds = baseline.get("std") or {}
    for c in baseline.get("cols") or IDLE_LEVEL_COLS:
        if c not in out.columns or c not in means:
            continue
        x = pd.to_numeric(out[c], errors="coerce").astype(float)
        mu = float(means[c])
        if mode == "delta":
            out[c] = x - mu
        elif mode in ("z", "zscore", "z_idle"):
            sig = float(stds.get(c, _STD_FLOOR) or _STD_FLOOR)
            out[c] = (x - mu) / sig
        else:
            raise ValueError(f"unknown idle baseline mode: {mode}")
    return out


def apply_idle_to_sample(
    sample: dict[str, float],
    baseline: dict[str, Any],
    *,
    mode: str | None = None,
) -> dict[str, float]:
    """Transform one live sample dict (level cols only)."""
    mode = (mode or baseline.get("mode") or "delta").lower()
    if mode in ("none", "off", ""):
        return dict(sample)
    out = dict(sample)
    means = baseline.get("mean") or {}
    stds = baseline.get("std") or {}
    for c in baseline.get("cols") or IDLE_LEVEL_COLS:
        if c not in means or c not in out:
            continue
        try:
            x = float(out[c] or 0.0)
        except (TypeError, ValueError):
            x = 0.0
        mu = float(means[c])
        if mode == "delta":
            out[c] = x - mu
        elif mode in ("z", "zscore", "z_idle"):
            sig = float(stds.get(c, _STD_FLOOR) or _STD_FLOOR)
            out[c] = (x - mu) / sig
    return out


def save_idle_baseline(path: Path, baseline: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2) + "\n")


def load_idle_baseline(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())
