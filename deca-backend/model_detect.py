"""Attach live Q2 detection evidence to dashboard Simple-fault Decide cards.

Orchestrator venv may lack xgboost/joblib — we subprocess into
`.venv-predictive` (same pattern as Q3 → deca-copilot).
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
SAMPLES = int(os.environ.get("DECA_DETECT_SAMPLES", "10"))
INTERVAL = float(os.environ.get("DECA_DETECT_INTERVAL", "0.4"))
TIMEOUT = float(os.environ.get("DECA_DETECT_TIMEOUT", "25"))


def detect_live(
    *,
    fault_id: str = "",
    fabric: str | None = None,
    samples: int | None = None,
    interval: float | None = None,
) -> dict[str, Any]:
    """Run one-shot Q2 detect; always returns a dict (ok True/False)."""
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
                "Q2 detect skipped — install .venv-predictive to show model evidence on Decide."
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
            "explanation": "Q2 oneshot timed out — Decide seed still valid from demo catalog.",
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
            "explanation": "Q2 oneshot returned no JSON.",
        }
    try:
        # oneshot prints a single JSON object
        data = json.loads(raw)
    except json.JSONDecodeError:
        # tolerate leading log noise
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
                "explanation": "Q2 oneshot JSON parse failed.",
            }
    data.setdefault("fault_id", fault_id or None)
    return data


def merge_into_seed(seed: dict[str, Any], detection: dict[str, Any]) -> dict[str, Any]:
    """Enrich a fault_demo / seed-preemption body with model_detection evidence."""
    out = dict(seed)
    out["model_detection"] = detection
    if detection.get("ok"):
        # Prefer live model class when it agrees or when seed severity empty
        if detection.get("severity"):
            if not out.get("severity") or detection.get("matches_demo_fault"):
                out["severity"] = detection["severity"]
        if detection.get("q2_name") and not out.get("root_cause"):
            out["root_cause"] = detection["q2_name"]
        if detection.get("root_label") is not None and out.get("root_cause_label") is None:
            out["root_cause_label"] = detection["root_label"]
        if detection.get("q2_confidence") is not None:
            # blend lightly toward model confidence for Decide display
            try:
                seed_c = float(out.get("confidence") or 0.85)
                model_c = float(detection["q2_confidence"])
                out["confidence"] = round(0.4 * seed_c + 0.6 * model_c, 4)
            except (TypeError, ValueError):
                pass
        snaps = detection.get("prom_snapshot") or {}
        sigs = dict(out.get("contributing_signals") or {})
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
                sigs[k] = float(snaps[k])
        sigs["q2_confidence"] = float(detection.get("q2_confidence") or 0)
        out["contributing_signals"] = sigs

        expl = detection.get("explanation") or ""
        summary = out.get("summary") or ""
        if expl and expl not in summary:
            out["summary"] = (summary + " " + expl).strip() if summary else expl
    return out
