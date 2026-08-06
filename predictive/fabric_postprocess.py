"""QUARANTINED — do not use in demo / competition / cite paths.

History: twin util/CPU/CE "fixes" were hardcoded remaps of the same numeric
bands used by `severity_label` (util≥20→5A/5B, etc.). That is the label
function wearing a prediction costume — circular with GT. Walked back
2026-08-05. See fix_receipts/WALKBACK_CIRCULAR_REMAP.md.

Legitimate twin levers (unchanged menu): per-fabric d3 · idle/SLA-% features ·
util transfer head — not this module.
"""
from __future__ import annotations

from typing import Any

# Kept as no-ops so any stale import does not silently re-enable remaps.


def refine_twin_severity(severity: str, **_kwargs: Any) -> str:
    return severity


def disambiguate_util_vs_ce(severity: str, **_kwargs: Any) -> str:
    return severity


def apply_to_proba_row(severity: str, sample: dict[str, Any], **_kwargs: Any) -> str:
    return severity
