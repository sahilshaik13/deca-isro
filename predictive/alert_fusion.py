"""Multi-head arbitration for Q1 TTI + Q2 severity (compound-aware).

Deliberate policy (not a learned fusion model):

1. **Gate red** = OR across TTI heads that are hot + within red_sec
   (any head can light the rail).
2. **Primary issue / root_cause** = Q2 severity argmax (owns the *why*).
3. **Urgency ETA shown** = min of firing TTI ETAs (soonest clock wins).
4. **Clock language** = hard-SLA heads (latency/loss/jitter) say **breach**;
   util head says **approaching ceiling** (HTB soft gate — O2.1 / same
   discipline as O2.2). Display surfaces must use this, not docs alone.
5. **Severity tie-break** = higher index in SEVERITY_ORDER within the same
   root family is worse; we do *not* override Q2 with a second classifier.
6. **Compound honesty** = expose ``firing_tti_heads`` + ``arbitration`` so the
   card is multi-hypothesis when several heads fire; playbook still keys off
   primary Q2 class (see ``chaos_compound`` runbook).

This is explicit priority, not silent ambiguity. Phase-2 could replace (2)
with a multi-label / graph fusion model — not claimed here.
"""
from __future__ import annotations

from typing import Any

from .severity_label import SEVERITY_ORDER

# Hard external SLAs (TT&C / payload) vs soft configured HTB ceiling (util).
HARD_SLA_HEADS = frozenset({"latency", "loss", "jitter"})
SOFT_CEILING_HEADS = frozenset({"util"})


def urgency_clock_copy(firing: list[dict[str, Any]]) -> dict[str, str]:
    """Operator-facing ETA wording from the *leading* (soonest) firing head.

    Util-led clock → approaching ceiling (soft HTB gate).
    Lat/loss/jitter-led → SLA breach (hard external SLA).
    Empty firing → hard_sla default (latency path historically owned the clock).
    """
    lead = str(firing[0]["head"]) if firing else "latency"
    if lead in SOFT_CEILING_HEADS:
        return {
            "urgency_clock_kind": "soft_ceiling",
            "urgency_lead_head": lead,
            "phrase_short": "approaching ceiling",
            "phrase_eta": "approaching HTB ceiling in",
            "phrase_title_suffix": "HTB ceiling in",
        }
    return {
        "urgency_clock_kind": "hard_sla",
        "urgency_lead_head": lead,
        "phrase_short": "SLA breach",
        "phrase_eta": "SLA breach in",
        "phrase_title_suffix": "SLA breach in",
    }


def firing_tti_heads(
    *,
    red_sec: float,
    eta_lat: float | None,
    lat_hot: bool,
    eta_loss: float | None,
    loss_hot: bool,
    eta_jitter: float | None,
    jitter_hot: bool,
    eta_util: float | None,
    util_hot: bool,
) -> list[dict[str, Any]]:
    """Heads that independently satisfy the red TTI condition (ignoring severity)."""
    out: list[dict[str, Any]] = []
    for name, eta, hot in (
        ("latency", eta_lat, lat_hot),
        ("loss", eta_loss, loss_hot),
        ("jitter", eta_jitter, jitter_hot),
        ("util", eta_util, util_hot),
    ):
        if eta is not None and hot and eta <= red_sec:
            out.append({"head": name, "eta_seconds": float(eta)})
    out.sort(key=lambda h: h["eta_seconds"])
    return out


def urgency_eta_seconds(firing: list[dict[str, Any]], fallback: float | None) -> float | None:
    """Soonest firing TTI; else latency ETA (or None)."""
    if firing:
        return float(firing[0]["eta_seconds"])
    return fallback


def severity_rank(severity: str | None) -> int:
    if not severity:
        return -1
    try:
        return SEVERITY_ORDER.index(severity)
    except ValueError:
        return -1


def fuse_alert_fields(
    *,
    red_sec: float,
    eta_lat: float | None,
    lat_hot: bool,
    eta_loss: float | None,
    loss_hot: bool,
    eta_jitter: float | None,
    jitter_hot: bool,
    eta_util: float | None,
    util_hot: bool,
    q2_name: str | None,
    severity: str | None,
    q2_confidence: float | None,
) -> dict[str, Any]:
    """Structured arbitration block for seed / Decide payload."""
    firing = firing_tti_heads(
        red_sec=red_sec,
        eta_lat=eta_lat,
        lat_hot=lat_hot,
        eta_loss=eta_loss,
        loss_hot=loss_hot,
        eta_jitter=eta_jitter,
        jitter_hot=jitter_hot,
        eta_util=eta_util,
        util_hot=util_hot,
    )
    urgency = urgency_eta_seconds(firing, eta_lat)
    compound = len(firing) > 1
    clock = urgency_clock_copy(firing)
    return {
        "arbitration": {
            "policy": (
                "gate_or_tti; primary_issue=q2_severity_argmax; "
                "urgency_eta=min_firing_tti; compound_exposes_all_heads; "
                "util_clock=approaching_ceiling_not_sla_breach"
            ),
            "primary_issue": q2_name or "unknown",
            "primary_severity": severity or "",
            "primary_confidence": float(q2_confidence or 0.0),
            "severity_rank": severity_rank(severity),
            "urgency_eta_seconds": urgency,
            "firing_tti_heads": firing,
            "compound_suspected": compound,
            **clock,
            "note": (
                "Under compound inject, Q2 may pick one dominant class; "
                "firing_tti_heads lists concurrent TTI evidence. "
                "Util TTI is a soft HTB ceiling clock — not hard SLA breach language. "
                "Not a multi-label / graph fusion model."
            ),
        }
    }
