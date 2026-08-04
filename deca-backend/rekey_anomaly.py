"""IPsec rekey anomaly scoring from existing exporter signals (PS13-O2.3).

Threshold rules only — no ML. Uses ipsec_sa_age_s / child SA count / rekey
event counters already (or newly) emitted by lab/exporters/deca-ipsec-rekey.sh.
"""
from __future__ import annotations

from typing import Any, Optional


# Lab-scale defaults: strongSwan rekeys are infrequent; bursts look anomalous.
REKEY_RATE_1H_THRESHOLD = 3.0
SA_AGE_RESET_MIN_S = 120.0  # age jumped down while tunnels still up
CHILD_SA_FLAP_MIN = 2


def score(
    *,
    sa_age_s: Optional[float],
    child_sa_count: Optional[float],
    rekey_events_1h: Optional[float] = None,
    prev_sa_age_s: Optional[float] = None,
) -> dict[str, Any]:
    """Return anomaly flag + reasons from gauge samples."""
    reasons: list[str] = []
    rate = float(rekey_events_1h or 0.0)
    age = float(sa_age_s) if sa_age_s is not None else None
    nsa = float(child_sa_count) if child_sa_count is not None else None

    if rate >= REKEY_RATE_1H_THRESHOLD:
        reasons.append(f"rekey_rate_1h={rate:.1f}>={REKEY_RATE_1H_THRESHOLD}")

    if (
        prev_sa_age_s is not None
        and age is not None
        and prev_sa_age_s >= SA_AGE_RESET_MIN_S
        and age < prev_sa_age_s * 0.25
        and age < SA_AGE_RESET_MIN_S
    ):
        reasons.append(f"sa_age_reset {prev_sa_age_s:.0f}s→{age:.0f}s")

    if nsa is not None and nsa <= 0 and age is not None and age > 0:
        reasons.append("child_sa_missing_while_age_nonzero")

    anomalous = bool(reasons)
    return {
        "ipsec_rekey_anomaly": 1 if anomalous else 0,
        "ipsec_rekey_rate_1h": rate,
        "reasons": reasons,
        "sa_age_s": age,
        "child_sa_count": nsa,
    }


def decide_seed_payload(score_out: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Fields to merge into a Decide seed when anomaly is raised."""
    if not score_out.get("ipsec_rekey_anomaly"):
        return None
    return {
        "root_cause": "rekey_anomaly",
        "alert_class": "tunnel_degradation",
        "severity": "1B",
        "title": "IPsec rekey anomaly",
        "summary": (
            "Charon SA rekey / age pattern looks anomalous vs baseline. "
            "Approve to steer underlay while investigating IKE/CHILD_SA health. "
            f"Reasons: {', '.join(score_out.get('reasons') or [])}."
        ),
    }
