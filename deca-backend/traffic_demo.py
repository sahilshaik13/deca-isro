"""NOC traffic demo — Start/Stop ToS iperf on active fabric (Pi or GNS3)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import config
import fabric as fabric_mod

STATUS_PATH = Path(
    os.environ.get(
        "DECA_TRAFFIC_DEMO_STATUS",
        str(config.REPO_ROOT / "data" / "deca" / "traffic_demo_status.json"),
    )
)

PROFILES = ("ttc", "payload", "admin", "mixed")

_lock = threading.Lock()
_proc: subprocess.Popen | None = None


def _default() -> dict[str, Any]:
    return {
        "running": False,
        "fabric": fabric_mod.get_active(),
        "profile": None,
        "duration_s": 0,
        "started_at": None,
        "started_by": None,
        "message": "idle",
        "log_tail": [],
        "profiles": list(PROFILES),
    }


def _read() -> dict[str, Any]:
    if not STATUS_PATH.is_file():
        return _default()
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        base = _default()
        base.update(data)
        return base
    except (OSError, json.JSONDecodeError, TypeError):
        return _default()


def _write(data: dict[str, Any]) -> dict[str, Any]:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def status() -> dict[str, Any]:
    with _lock:
        st = _read()
        # Reconcile dead background process
        global _proc
        if st.get("running") and _proc is not None and _proc.poll() is not None:
            st["running"] = False
            st["message"] = f"finished (exit {_proc.returncode})"
            _proc = None
            _write(st)
        # Keep started fabric; expose active separately (do not lie after switch)
        st["active_fabric"] = fabric_mod.get_active()
        st.setdefault("fabric", st.get("fabric") or st["active_fabric"])
        return st


def _script_for(fab: str) -> Path:
    if fab == "gns3":
        return config.REPO_ROOT / "lab" / "gns3" / "traffic_control.sh"
    return config.REPO_ROOT / "lab" / "deca_iperf_qos_traffic.sh"


def start(
    profile: str = "mixed",
    duration_s: int = 0,
    started_by: str = "deca-ui",
) -> dict[str, Any]:
    profile = (profile or "mixed").strip().lower()
    if profile not in PROFILES:
        return {"ok": False, "error": f"unknown profile={profile!r}"}
    fab = fabric_mod.get_active()
    script = _script_for(fab)
    if not script.is_file():
        return {"ok": False, "error": f"missing script {script}"}

    with _lock:
        cur = _read()
        if cur.get("running"):
            return {
                "ok": False,
                "error": "traffic already running — stop first",
                "status": cur,
            }

        dur = int(duration_s) if duration_s and int(duration_s) > 0 else 0
        env = os.environ.copy()
        env["DECA_TRAFFIC_PROFILE"] = profile
        env["DECA_TRAFFIC_DURATION"] = str(dur if dur > 0 else 86400)
        env["DECA_FABRIC"] = fab

        if fab == "gns3":
            cmd = ["bash", str(script), "start", profile, str(dur)]
        else:
            # Pi script: start [duration_s]; profile via env for selective clients
            cmd = ["bash", str(script), "start", str(dur if dur > 0 else 3600)]

        try:
            global _proc
            _proc = subprocess.Popen(
                cmd,
                cwd=str(config.REPO_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as exc:
            return {"ok": False, "error": str(exc)}

        # Brief wait to catch immediate failures
        time.sleep(0.8)
        log_tail: list[str] = []
        if _proc.poll() is not None and _proc.returncode not in (0, None):
            out = (_proc.stdout.read() if _proc.stdout else "") or ""
            log_tail = out.splitlines()[-20:]
            _proc = None
            return {
                "ok": False,
                "error": "traffic script exited early",
                "log_tail": log_tail,
            }

        # For oneshot GNS3, script may exit 0 after launching daemons
        if _proc.poll() is not None:
            out = (_proc.stdout.read() if _proc.stdout else "") or ""
            log_tail = out.splitlines()[-30:]
            _proc = None

        st = {
            "running": True,
            "fabric": fab,
            "profile": profile,
            "duration_s": dur,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "started_by": started_by,
            "message": f"{fab} traffic {profile} started",
            "log_tail": log_tail,
            "profiles": list(PROFILES),
        }
        _write(st)
        return {"ok": True, "status": st}


def stop(reason: str = "operator_stop", fabric: str | None = None) -> dict[str, Any]:
    with _lock:
        cur = _read()
        fab = (fabric or cur.get("fabric") or fabric_mod.get_active()).strip().lower()
        script = _script_for(fab)
        global _proc
        if _proc is not None and _proc.poll() is None:
            try:
                _proc.terminate()
            except OSError:
                pass
            _proc = None

        log_tail: list[str] = []
        if script.is_file():
            try:
                proc = subprocess.run(
                    ["bash", str(script), "stop"],
                    cwd=str(config.REPO_ROOT),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env={**os.environ, "DECA_FABRIC": fab},
                )
                log_tail = (proc.stdout or "").splitlines()[-20:]
                if proc.stderr:
                    log_tail += (proc.stderr or "").splitlines()[-10:]
            except (OSError, subprocess.TimeoutExpired) as exc:
                log_tail = [str(exc)]

        st = {
            "running": False,
            "fabric": fab,
            "active_fabric": fabric_mod.get_active(),
            "profile": None,
            "duration_s": 0,
            "started_at": None,
            "started_by": None,
            "message": f"stopped ({reason})",
            "log_tail": log_tail,
            "profiles": list(PROFILES),
        }
        _write(st)
        return {"ok": True, "status": st}
