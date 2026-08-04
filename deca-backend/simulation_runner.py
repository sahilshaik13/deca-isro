"""Background runner for scripts/run_simulation.sh (orchestrator lab demo)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import config

REPO_ROOT = config.REPO_ROOT
STATUS_PATH = Path(
    os.environ.get("DECA_SIM_STATUS", str(REPO_ROOT / "data" / "deca" / "simulation_status.json"))
).resolve()
STOP_FLAG = Path(
    os.environ.get("DECA_SIM_STOP_FLAG", str(REPO_ROOT / "data" / "deca" / "simulation.stop"))
).resolve()
LOG_PATH = Path(
    os.environ.get("DECA_SIM_LOG", str(REPO_ROOT / "data" / "deca" / "simulation.log"))
).resolve()
SCRIPT_PI = (REPO_ROOT / "scripts" / "run_simulation.sh").resolve()
SCRIPT_GNS3 = (REPO_ROOT / "lab" / "gns3" / "run_orchestrator_sim.sh").resolve()
SCRIPT = SCRIPT_PI  # overridden at start() by active fabric


_proc: Optional[subprocess.Popen] = None
_meta: dict[str, Any] = {}


def _ensure_dirs() -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_status_file() -> dict[str, Any]:
    if not STATUS_PATH.is_file():
        return {
            "running": False,
            "finished": False,
            "phase": None,
            "phase_name": None,
            "message": "idle",
            "waiting_for_approve": False,
            "log_tail": [],
        }
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"running": False, "message": "status unreadable", "log_tail": []}


def _alive() -> bool:
    global _proc
    if _proc is None:
        return False
    code = _proc.poll()
    if code is None:
        return True
    _proc = None
    return False


def status() -> dict[str, Any]:
    data = _read_status_file()
    alive = _alive()
    data["running"] = bool(alive or data.get("running"))
    if not alive and data.get("running") and not data.get("finished"):
        # Process died without finish_status
        data["running"] = False
        data["finished"] = True
        data.setdefault("ok", False)
        data["message"] = data.get("message") or "simulation process exited"
    data["pid"] = _meta.get("pid")
    data["started_by"] = _meta.get("started_by")
    data["dry"] = _meta.get("dry")
    data["fabric"] = data.get("fabric") or _meta.get("fabric")
    data["script"] = _meta.get("script") or str(SCRIPT_PI)
    data["status_path"] = str(STATUS_PATH)
    return data


def start(*, dry: bool = False, started_by: str = "deca-ui") -> dict[str, Any]:
    global _proc, _meta
    if _alive():
        return {"ok": False, "error": "simulation already running", "status": status()}

    fabric = "pi"
    run_id = "sim-live"
    try:
        import fabric as fabric_mod

        fabric = (fabric_mod.get_active() or "pi").strip().lower()
        run_id = fabric_mod.default_run_id(fabric)
    except Exception:
        fabric = "pi"
        run_id = "sim-live"
    script = SCRIPT_GNS3 if fabric == "gns3" else SCRIPT_PI
    if not script.is_file():
        return {"ok": False, "error": f"missing script: {script}"}

    # Fresh Decide rail + history for this fabric run (previous timeline leftovers)
    cleared: dict[str, Any] = {}
    try:
        import repos

        cleared = repos.clear_run_session(run_id)
        repos.set_active_run(
            run_id, mode="live", notes=f"timeline start ({fabric})"
        )
    except Exception as exc:  # noqa: BLE001
        cleared = {"error": str(exc)}

    # Reset path/conflict overlay so map/Decide don't show last run's steer
    try:
        import controller_client

        controller_client.post_action(
            op="reset_autonomy",
            reason="timeline_start",
            approved_by=started_by or "deca-ui",
        )
    except Exception:  # noqa: BLE001
        pass

    _ensure_dirs()
    STOP_FLAG.unlink(missing_ok=True)
    # Truncate previous sim log so UI log_tail isn't stale
    try:
        LOG_PATH.write_text("", encoding="utf-8")
    except OSError:
        pass
    STATUS_PATH.write_text(
        json.dumps(
            {
                "running": True,
                "finished": False,
                "phase": 0,
                "phase_name": "Starting",
                "message": f"Launching {script.name} (fabric={fabric})…",
                "ui_expectation": "Cleared prior Decide/history for this fabric run.",
                "waiting_for_approve": False,
                "log_tail": [],
                "ok": True,
                "fabric": fabric,
                "run_id": run_id,
                "cleared": cleared,
                "elapsed_s": 0,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["DECA_SIM_STATUS"] = str(STATUS_PATH)
    env["DECA_SIM_STOP_FLAG"] = str(STOP_FLAG)
    env["DECA_SIM_LOG"] = str(LOG_PATH)
    env["DECA_SIM_FABRIC"] = fabric
    # Script seeds alerts back into this API — always use IPv4 loopback.
    env["DECA_SIM_ORCH_URL"] = os.environ.get(
        "DECA_SIM_ORCH_URL", f"http://127.0.0.1:{config.PORT}"
    )
    env["DECA_SIM_CTRL_URL"] = config.SDWAN_CONTROLLER_URL
    env["DECA_SIM_DRY"] = "1" if dry else "0"

    log_fh = open(LOG_PATH, "ab", buffering=0)  # noqa: SIM115 — kept for process lifetime
    _proc = subprocess.Popen(
        ["bash", str(script)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    _meta = {
        "pid": _proc.pid,
        "started_by": started_by,
        "dry": dry,
        "fabric": fabric,
        "run_id": run_id,
        "started_at": time.time(),
        "log_fh": log_fh,
        "script": str(script),
    }
    return {
        "ok": True,
        "pid": _proc.pid,
        "dry": dry,
        "fabric": fabric,
        "run_id": run_id,
        "active_run_id": run_id,
        "cleared": cleared,
        "script": str(script),
        "status": status(),
    }


def stop(*, reason: str = "operator_stop") -> dict[str, Any]:
    global _proc
    _ensure_dirs()
    STOP_FLAG.write_text(reason + "\n", encoding="utf-8")
    if _proc is not None and _proc.poll() is None:
        try:
            os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                _proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        try:
            _proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(_proc.pid), signal.SIGKILL)
            except Exception:  # noqa: BLE001
                _proc.kill()
        _proc = None
    data = _read_status_file()
    data["running"] = False
    data["finished"] = True
    data["message"] = f"stopped: {reason}"
    data["waiting_for_approve"] = False
    STATUS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "status": status()}
