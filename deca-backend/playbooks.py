"""Ranked playbook suggestions + executable action sequences (PS13-O4.3 partial).

Approve runs a budgeted sequence; failover (force_path) is never skipped.
Single ranked path per alert class — **not** a multi-candidate playbook
engine (FINDINGS O4.3 downgrade).
"""
from __future__ import annotations

from typing import Any, Optional

# Soft-clear budget must stay well under the 120s red-gate lead window.
SOFT_CLEAR_BUDGET_SEC = 8.0
FORCE_PATH_BUDGET_SEC = 15.0


def ranked_actions(
    *,
    path: str = "eth0",
    severity: str = "",
    alert_class: str = "",
    root_cause: str = "",
    path_asymmetry_detected: bool = False,
    rogue_ce: Optional[str] = None,
    victim_ce: Optional[str] = None,
) -> list[str]:
    """Return ordered playbook steps (highest priority first)."""
    sev = (severity or "").strip().upper()
    cls = (alert_class or "").strip().lower()
    rc = (root_cause or "").strip().lower()
    backup = path if path in ("gre", "eth0") else "eth0"
    bgpish = cls == "bgp_route_flap" or "route_flap" in rc or sev in {"3A", "3B"}
    ce_conflict = (
        "ce_sla_conflict" in rc
        or bool(rogue_ce)
        or (cls == "policy_drift" and (rogue_ce or victim_ce))
    )

    if ce_conflict:
        rogue = rogue_ce or "bronze-CE"
        victim = victim_ce or "gold-CE"
        steps = [
            f"1. Identify rogue CE ({rogue}) vs victim ({victim}); confirm Prom ce_util_mbps / path util",
            f"2. Approve: protect victim SLA — force_path→{backup} on PE1; throttle/stop rogue burst inject",
            "3. Hold human override until Gold TT&C recovers (exit_k); document operator on audit",
        ]
    elif bgpish:
        steps = [
            f"1. Approve sequence: one-shot BGP soft-clear (stabilize) then force_path→{backup}",
            "2. Check FRR BGP/LDP on PE1↔CORE; dampen flap source if still injecting",
            "3. Hold human override until clear_force + exit_k; confirm VPNv4 prefixes return",
        ]
    elif cls == "tunnel_degradation" or "physical" in rc or sev in {"1A", "1B", "1C"}:
        steps = [
            f"1. Approve: steer ESP underlay to {backup} on PE1 (force_path)",
            "2. Confirm rain-fade/netem or GRE brownout (Prom GRE vs eth0 latency); clear inject when safe",
            "3. Hold human override until GRE SLA recovers and exit_k fail-back",
        ]
    elif "crypto" in rc or "cpu" in rc or sev in {"2A", "2B"}:
        steps = [
            f"1. Approve: steer ESP underlay to {backup} on PE1 (force_path)",
            "2. Inspect PE1 CPU/stress (Prom cpu_usage_*); stop stress-ng / crypto load if active",
            "3. Hold human override until CPU cools and underlay latency stabilizes",
        ]
    else:
        steps = [
            f"1. Approve: steer ESP underlay to {backup} on PE1 (force_path)",
            f"2. Verify Decide math (Q1 ETA / Q2 severity={sev or 'n/a'} class={cls or 'n/a'}) against Prom GRE/eth0",
            "3. Keep human override until clear_force / exit_k recovery",
        ]

    if path_asymmetry_detected:
        steps.insert(
            1,
            "2. Path asymmetry flagged (GRE vs eth0): prefer backup until preferred underlay differential closes",
        )
        out: list[str] = []
        for i, s in enumerate(steps, start=1):
            body = s.split(". ", 1)[-1] if ". " in s[:4] else s
            out.append(f"{i}. {body}")
        return out

    return steps


def action_sequence(
    *,
    path: str = "eth0",
    severity: str = "",
    alert_class: str = "",
    root_cause: str = "",
) -> list[dict[str, Any]]:
    """Executable ops for Approve — budgeted; force_path always terminal for risk tiers."""
    sev = (severity or "").strip().upper()
    cls = (alert_class or "").strip().lower()
    rc = (root_cause or "").strip().lower()
    backup = path if path in ("gre", "eth0") else "eth0"
    bgpish = cls == "bgp_route_flap" or "route_flap" in rc or sev in {"3A", "3B"}
    seq: list[dict[str, Any]] = []
    if bgpish:
        # REMEDIATION direction: one-shot soft-clear to stabilize RIB.
        # Do NOT reuse inject_bgp_flap.sh multi-cycle loop (that induces flaps for GT).
        seq.append(
            {
                "op": "bgp_soft_clear",
                "budget_sec": SOFT_CLEAR_BUDGET_SEC,
                "reason": "remediation_stabilize_one_shot",
            }
        )
    seq.append(
        {
            "op": "force_path",
            "path": backup,
            "budget_sec": FORCE_PATH_BUDGET_SEC,
            "reason": "preemptive_failover",
        }
    )
    return seq


def asymmetry_metrics(
    latency_gre_ms: Optional[float],
    latency_eth0_ms: Optional[float],
    *,
    abs_threshold_ms: float = 5.0,
    rel_threshold: float = 0.5,
) -> dict:
    """Named path-asymmetry signal from dual 1Hz probes (PS13-O2.2)."""
    out: dict = {
        "path_asymmetry_ms": None,
        "path_asymmetry_abs_ms": None,
        "path_asymmetry_detected": False,
        "path_asymmetry_threshold_ms": abs_threshold_ms,
    }
    if latency_gre_ms is None or latency_eth0_ms is None:
        return out
    gre = float(latency_gre_ms)
    eth = float(latency_eth0_ms)
    diff = gre - eth
    abs_diff = abs(diff)
    out["path_asymmetry_ms"] = round(diff, 3)
    out["path_asymmetry_abs_ms"] = round(abs_diff, 3)
    # Absolute floor OR relative to the healthier path
    baseline = max(min(gre, eth), 0.1)
    out["path_asymmetry_detected"] = bool(
        abs_diff >= abs_threshold_ms or (abs_diff / baseline) >= rel_threshold
    )
    return out
