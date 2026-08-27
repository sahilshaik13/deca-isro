"""Live Q1+Q2 → Decide seed for Simple faults (fully model-dependent).

Orchestrator venv may lack xgboost/joblib — we subprocess into
`.venv-predictive` (same pattern as Q3 → deca-copilot).

Decide cards are raised only from Prom → oneshot scores. Catalog inject
scripts still create the fault; they do not supply severity / ETA / confidence.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import config

REPO = config.REPO_ROOT
PRED_PY = Path(
    os.environ.get(
        "DECA_PREDICTIVE_PYTHON",
        str(REPO / ".venv-predictive" / "bin" / "python"),
    )
)
# ≥30 samples so oneshot can fill the Q1 LSTM window (TTI from Prom).
# With Prom history (default), wall clock is ~1–2s per detect, not 30×sleep.
SAMPLES = int(os.environ.get("DECA_DETECT_SAMPLES", "30"))
INTERVAL = float(os.environ.get("DECA_DETECT_INTERVAL", "0.2"))
TIMEOUT = float(os.environ.get("DECA_DETECT_TIMEOUT", "45"))
# Match infer_q1_q2_live urgency windows (seconds).
RED_SEC = float(os.environ.get("DECA_RED_SEC", "120"))
# Raise earlier on Q1 TTI (≤15 min) so Decide appears mid-ramp, not only near SLA.
YELLOW_SEC = float(os.environ.get("DECA_YELLOW_SEC", "900"))
# Require non-normal Q2, or Q1 ETA in yellow/red (score gate).
MODEL_ONLY = os.environ.get("DECA_MODEL_ONLY", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# Same mapping as predictive.infer_q1_q2_live.Q2_TO_ALERT_CLASS (+ CE root 6).
Q2_TO_ALERT_CLASS = {
    0: "congestion_breach",
    1: "tunnel_degradation",
    2: "congestion_breach",
    3: "bgp_route_flap",
    4: "tunnel_degradation",
    5: "policy_drift",
    6: "policy_drift",
}

RED_SEVERITIES = frozenset({"1B", "1C", "2B", "3B", "4B", "5B", "6B"})


def detect_live(
    *,
    fault_id: str = "",
    fabric: str | None = None,
    samples: int | None = None,
    interval: float | None = None,
) -> dict[str, Any]:
    """Run one-shot Q1+Q2 detect; always returns a dict (ok True/False)."""
    try:
        import fabric as fabric_mod

        fab = fabric or fabric_mod.get_active()
    except Exception:  # noqa: BLE001
        fab = fabric or "pi"

    if not PRED_PY.is_file():
        return {
            "ok": False,
            "error": "predictive_venv_missing",
            "hint": str(PRED_PY),
            "fault_id": fault_id,
            "explanation": (
                "Q1/Q2 detect skipped — install .venv-predictive for model Decide."
            ),
        }

    cmd = [
        str(PRED_PY),
        "-m",
        "predictive.oneshot_detect",
        "--fault-id",
        fault_id or "",
        "--fabric",
        fab,
        "--samples",
        str(samples if samples is not None else SAMPLES),
        "--interval",
        str(interval if interval is not None else INTERVAL),
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["DECA_FABRIC"] = fab
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO),
            capture_output=True,
            timeout=TIMEOUT,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "detect_timeout",
            "fault_id": fault_id,
            "explanation": "Q1/Q2 oneshot timed out — no Decide card (model-only).",
        }
    except OSError as exc:
        return {
            "ok": False,
            "error": f"detect_spawn:{exc}",
            "fault_id": fault_id,
            "explanation": "Could not spawn predictive oneshot.",
        }

    raw = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    if not raw:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:400]
        return {
            "ok": False,
            "error": f"detect_empty_rc_{proc.returncode}",
            "stderr": err,
            "fault_id": fault_id,
            "explanation": "Q1/Q2 oneshot returned no JSON.",
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                data = None
        else:
            data = None
        if not isinstance(data, dict):
            return {
                "ok": False,
                "error": "detect_bad_json",
                "fault_id": fault_id,
                "raw_tail": raw[-300:],
                "explanation": "Q1/Q2 oneshot JSON parse failed.",
            }
    data.setdefault("fault_id", fault_id or None)
    return data


def should_raise(detection: dict[str, Any]) -> bool:
    """Score gate: raise Decide only when models warrant it."""
    if not detection.get("ok"):
        return False
    sev = str(detection.get("severity") or "0").strip() or "0"
    eta_s: float | None = None
    if detection.get("eta_seconds") is not None:
        try:
            eta_s = float(detection["eta_seconds"])
        except (TypeError, ValueError):
            eta_s = None
    elif detection.get("eta_minutes") is not None:
        try:
            eta_s = float(detection["eta_minutes"]) * 60.0
        except (TypeError, ValueError):
            eta_s = None

    # Non-normal Q2 class — primary score.
    if sev != "0":
        return True
    # Q1 urgency even if Q2 still healthy (early TTI).
    if eta_s is not None and eta_s <= YELLOW_SEC:
        return True
    return False


def build_seed_from_detection(
    detection: dict[str, Any],
    *,
    fault_id: str = "",
    path: str = "eth0",
    host: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a seed-preemption body purely from model scores.

    Returns None when the score gate does not fire (no catalog fallback).
    ``context`` may carry inject-only attribution (rogue/victim CE) — never scores.
    """
    if MODEL_ONLY and not should_raise(detection):
        return None
    if not detection.get("ok"):
        return None

    ctx = dict(context or {})
    # Strip any leftover catalog score keys if a caller passed an old seed dict.
    for k in (
        "severity",
        "eta_minutes",
        "confidence",
        "alert_class",
        "root_cause",
        "root_cause_label",
        "concerns",
        "title",
        "summary",
        "eta_loss_minutes",
    ):
        ctx.pop(k, None)

    sev = str(detection.get("severity") or "0")
    try:
        root_label = int(detection.get("root_label") if detection.get("root_label") is not None else 0)
    except (TypeError, ValueError):
        root_label = 0
    rc_name = str(detection.get("q2_name") or "unknown")
    if sev == "0":
        rc_name = "normal"
    alert_class = Q2_TO_ALERT_CLASS.get(root_label, "congestion_breach")
    # CE inject context → policy_drift even if root mapping differs.
    if ctx.get("rogue_ce") or ctx.get("victim_ce"):
        alert_class = "policy_drift"

    conf = 0.55
    if detection.get("q2_confidence") is not None:
        try:
            conf = float(detection["q2_confidence"])
        except (TypeError, ValueError):
            conf = 0.55

    eta_minutes: float | None = None
    eta_source = "none"
    if detection.get("eta_minutes") is not None:
        try:
            eta_minutes = round(float(detection["eta_minutes"]), 3)
            eta_source = detection.get("eta_source") or "q1_lstm_prom"
        except (TypeError, ValueError):
            eta_minutes = None
    elif detection.get("eta_seconds") is not None:
        try:
            eta_minutes = round(max(0.05, float(detection["eta_seconds"]) / 60.0), 3)
            eta_source = detection.get("eta_source") or "q1_lstm_prom"
        except (TypeError, ValueError):
            eta_minutes = None

    # No catalog ETA. Q2-only raises get an advisory clock (not a scripted seed).
    if eta_minutes is None:
        if sev == "0":
            return None
        eta_minutes = round(YELLOW_SEC / 60.0, 3)
        eta_source = "q2_only_advisory_clock"

    eta_s = float(detection.get("eta_seconds") or (eta_minutes * 60.0))
    # Blend confidence with Q1 urgency (same idea as infer_q1_q2_live).
    if detection.get("eta_seconds") is not None:
        conf = max(
            0.55,
            min(
                0.97,
                0.5 * conf
                + 0.5 * (0.55 + (RED_SEC - min(eta_s, RED_SEC)) / RED_SEC * 0.35),
            ),
        )

    path = str(ctx.get("path") or path or "eth0")
    title = f"Q1+Q2: {rc_name} — SLA risk in ~{int(eta_s)}s"
    if sev in RED_SEVERITIES:
        title = f"Q1+Q2: {rc_name} ({sev}) — breach window ~{int(eta_s)}s"

    expl = str(detection.get("explanation") or "").strip()
    summary = (
        f"Model scores: Q2 {rc_name} severity={sev} (p={conf:.2f}); "
        f"Q1 TTI ≈ {eta_s:.0f}s ({eta_source}). "
        f"Approve to steer to {path}."
    )
    if expl:
        summary = f"{summary} {expl}"

    snaps = detection.get("prom_snapshot") or {}
    sigs: dict[str, float] = {}
    for k in (
        "latency_gre_ms",
        "latency_eth0_ms",
        "jitter_gre_ms",
        "loss_gre_pct",
        "util_gre_mbps",
        "cpu_usage_user",
        "bgp_flap_count",
        "path_asymmetry",
    ):
        if k in snaps and snaps[k] is not None:
            try:
                sigs[k] = float(snaps[k])
            except (TypeError, ValueError):
                pass
    sigs["q2_confidence"] = float(detection.get("q2_confidence") or conf)
    if detection.get("eta_seconds") is not None:
        try:
            sigs["q1_eta_seconds"] = float(detection["eta_seconds"])
        except (TypeError, ValueError):
            pass

    body: dict[str, Any] = {
        "title": title,
        "path": path,
        "confidence": round(conf, 4),
        "eta_minutes": eta_minutes,
        "eta_source": eta_source,
        "alert_class": alert_class,
        "root_cause": rc_name,
        "root_cause_label": root_label,
        "severity": sev,
        "summary": summary,
        "contributing_signals": sigs,
        "model_detection": detection,
        "enrich_q3": True,
        "preemption": True,
        "noc_demo_fault": fault_id or None,
        "generation_path": detection.get("generation_path") or "q1_q2_oneshot_frozen",
    }
    if host:
        body["host"] = host
    # Inject attribution only (not scores).
    for k in (
        "rogue_ce",
        "victim_ce",
        "rogue_sla",
        "victim_sla",
        "affected_scope",
    ):
        if ctx.get(k) is not None:
            body[k] = ctx[k]
    return body


def merge_into_seed(seed: dict[str, Any], detection: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper — model scores win; catalog scores discarded."""
    fault_id = str(
        detection.get("fault_id")
        or seed.get("noc_demo_fault")
        or ""
    )
    built = build_seed_from_detection(
        detection,
        fault_id=fault_id,
        path=str(seed.get("path") or "eth0"),
        host=seed.get("host"),
        context=seed,
    )
    if built is not None:
        return built
    # Gate did not fire — return detection evidence only (caller must not POST).
    out = {
        "model_detection": detection,
        "raise": False,
        "path": seed.get("path") or "eth0",
    }
    return out
