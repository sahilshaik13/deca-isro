"""Per-fabric Q2 severity model routing (Pi d2 / GNS3 d3).

Pi-primary demo stays on frozen ``d2_e100_l6_mcw3``. GNS3 twin path uses
``d3_e120_l4_mcw2`` trained on the cite-era 3838-row matrix (pre-BGP-roll) —
same form-sweep recipe that historically transferred at ~0.721. No remaps,
no chaos_final tuning.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PI_Q2_DEFAULT = ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_unified/q2_severity.joblib"
GNS3_Q2_DEFAULT = ROOT / "data/deca/predictive/protocol_models/xgb_q2_sev_gns3_d3/q2_severity.joblib"


def resolve_fabric(raw: str | None = None) -> str:
    fab = (raw or os.environ.get("DECA_FABRIC", "pi") or "pi").strip().lower()
    return "gns3" if fab == "gns3" else "pi"


def resolve_q2_model(
    *,
    fabric: str | None = None,
    q2_model: str | Path | None = None,
    q2_model_gns3: str | Path | None = None,
) -> Path:
    """Pick Q2 joblib for the active fabric.

    Explicit ``q2_model`` wins on Pi. On GNS3, ``q2_model_gns3`` (or the
    default d3 path) wins when present; otherwise fall back to ``q2_model``.
    """
    fab = resolve_fabric(fabric)
    primary = Path(q2_model) if q2_model else PI_Q2_DEFAULT
    if fab != "gns3":
        return primary
    twin = Path(q2_model_gns3) if q2_model_gns3 else GNS3_Q2_DEFAULT
    if twin.is_file():
        return twin
    return primary
