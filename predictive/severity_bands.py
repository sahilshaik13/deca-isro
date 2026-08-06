"""Per-fabric severity band tables for Q2 *labeling* (not inference remaps).

Pi bands stay SLA-/physics-aligned (latency 25 ms, loss 2%, dedicated CPU).
GNS3 bands are fit from that fabric's own idle/stress distributions so 2A/2B
mean "moderate vs severe *on shared virtual hardware*", not Pi's absolute %.

FORBIDDEN (see WALKBACK_CIRCULAR_REMAP.md): remapping *predictions* at inference
to these bands. This module only changes how GT severity strings are stamped
when building windows on a given fabric.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Pi / default — external SLAs + dedicated-hardware CPU/util (severity_label.py history)
PI_BANDS: dict[str, Any] = {
    "fabric": "pi",
    "source": "sla_and_dedicated_hardware",
    "cpu_2a": 40.0,
    "cpu_2b": 70.0,
    # Mbps fallback when util_ceil_schedule is absent (pre-contract / legacy).
    "util_5a": 20.0,
    "util_5b": 35.0,
    # CAPTURE_CONTRACT Q2 util severity — fractions of this inject's end_mbit
    # (from util_ceil_schedule.jsonl), not measured Mbps and not score-tuned.
    "util_5a_frac_of_end": 0.50,
    "util_5b_frac_of_end": 1.00,
    "ce_6a": 10.0,
    "ce_6b": 18.0,
    # SLA-tied — same on both fabrics
    "lat_1a": 10.0,
    "lat_1b": 19.0,
    "lat_1c": 25.0,
    "loss_4a": 0.5,
    "loss_4b": 2.0,
    "bgp_3a": 0.2,
    "bgp_3b": 1.0,
}


def load_bands(path: Path | None = None, *, fabric: str = "pi") -> dict[str, Any]:
    if fabric == "pi" and path is None:
        return dict(PI_BANDS)
    if path is None:
        return dict(PI_BANDS)
    data = json.loads(Path(path).read_text())
    out = dict(PI_BANDS)
    out.update(data)
    out["fabric"] = fabric
    return out


def fit_gns3_bands(
    protocol_dir: Path,
    *,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Derive GNS3-native CPU/util/CE cutpoints from L0 + stress captures.

    Method: among samples clearly above idle, use ~p25 as mild floor (A) and
    ~p60–p70 as severe floor (B). SLA-tied latency/loss/BGP stay Pi/absolute.
    """
    root = Path(protocol_dir)

    def _load(pattern: str) -> pd.DataFrame:
        frames = [pd.read_csv(p) for p in sorted(root.glob(pattern))]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    l0 = _load("L0_*/iter_*/series.csv")
    l2 = _load("L2_*/iter_*/series.csv")
    l5 = _load("L5_*/iter_*/series.csv")
    l6 = _load("L6_*/iter_*/series.csv")
    if l2.empty or l5.empty:
        raise SystemExit(f"need L2+L5 series under {root} to fit GNS3 bands")

    def _col(df: pd.DataFrame, c: str) -> pd.Series:
        return pd.to_numeric(df[c], errors="coerce").dropna() if c in df.columns else pd.Series(dtype=float)

    cpu_idle = float(_col(l0, "cpu_usage_user").quantile(0.95)) if not l0.empty else 8.0
    util_idle = float(_col(l0, "util_gre_mbps").quantile(0.95)) if not l0.empty else 2.5

    cpu_on = _col(l2, "cpu_usage_user")
    cpu_on = cpu_on[cpu_on > cpu_idle + 5]
    util5_on = _col(l5, "util_gre_mbps")
    util5_on = util5_on[util5_on > util_idle + 2]
    util6_on = _col(l6, "util_gre_mbps") if not l6.empty else util5_on
    util6_on = util6_on[util6_on > util_idle + 1]

    # Use low/mid quantiles of *on* samples so mild stress variants stay labeled
    # (GNS3 CPU is often discrete gauge steps e.g. 55/72/85/92 — p25 pooled was
    # too high and wiped worker=1 iters into severity "0").
    def _cuts(on: pd.Series, idle: float, lo_q: float, hi_q: float, floor_margin: float):
        if len(on) < 20:
            return idle + floor_margin, idle + floor_margin * 3
        a = max(idle + floor_margin, float(on.quantile(lo_q)))
        b = float(on.quantile(hi_q))
        if b <= a:
            b = a + max(1.0, 0.15 * a)
        return round(a, 2), round(b, 2)

    cpu_2a, cpu_2b = _cuts(cpu_on, cpu_idle, 0.10, 0.50, 15.0)
    util_5a, util_5b = _cuts(util5_on, util_idle, 0.15, 0.55, 3.0)
    ce_6a, ce_6b = _cuts(util6_on, util_idle, 0.15, 0.55, 2.0)

    bands = dict(PI_BANDS)
    bands.update(
        {
            "fabric": "gns3",
            "source": "fit_from_protocol_idle_stress",
            "protocol_dir": str(root),
            "cpu_idle_p95": round(cpu_idle, 3),
            "util_idle_p95": round(util_idle, 3),
            "cpu_2a": cpu_2a,
            "cpu_2b": cpu_2b,
            "util_5a": util_5a,
            "util_5b": util_5b,
            "ce_6a": ce_6a,
            "ce_6b": ce_6b,
            "n_cpu_on": int(len(cpu_on)),
            "n_util5_on": int(len(util5_on)),
            "n_util6_on": int(len(util6_on)),
            "note": (
                "LABEL-TIME ONLY for GNS3 window GT. Not an inference remap. "
                "Shared-host virtualization: cpu_usage_user / CE contention ≠ Pi dedicated hardware."
            ),
        }
    )
    # Guard: A < B
    for a, b in (("cpu_2a", "cpu_2b"), ("util_5a", "util_5b"), ("ce_6a", "ce_6b")):
        if bands[a] >= bands[b]:
            bands[b] = float(bands[a]) + 1.0

    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(bands, indent=2) + "\n")
    return bands


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--protocol-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    bands = fit_gns3_bands(Path(args.protocol_dir), out_path=Path(args.out))
    print(json.dumps(bands, indent=2))


if __name__ == "__main__":
    main()
