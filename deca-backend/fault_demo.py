"""Simple one-click fault demos for the NOC dashboard (mentor: click → see → predict).

Each fault: short live inject on the active fabric + Decide seed so the math/HITL
card appears while telemetry moves. Clear stops inject leftovers from this catalog
only (scoped to the fabric that started the fault).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

import config
import fabric as fabric_mod

REPO_ROOT = config.REPO_ROOT
STATUS_PATH = Path(
    os.environ.get(
        "DECA_FAULT_DEMO_STATUS",
        str(REPO_ROOT / "data" / "deca" / "fault_demo_status.json"),
    )
).resolve()
API = os.environ.get("DECA_API_URL", "http://127.0.0.1:8000")


def _prom_url() -> str:
    """Prom for the active fabric (Pi :9090 / GNS3 :9091)."""
    try:
        return fabric_mod.prom_url_for()
    except Exception:  # noqa: BLE001
        return os.environ.get("DECA_PROM_URL", "http://127.0.0.1:9090")


HOST = os.environ.get("DECA_INJECT_HOST", "station1")

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_watcher: Optional[threading.Thread] = None
_state: dict[str, Any] = {
    "running": False,
    "fault_id": None,
    "fabric": None,
    "message": "idle",
    "started_at": None,
    "seeded_alert": None,
    "log_tail": [],
}


# Mentor-facing catalog — keep short (~60–90s) so jury can click several.
FAULTS: dict[str, dict[str, Any]] = {
    "rain_fade": {
        "label": "Rain fade",
        "blurb": "GRE latency ramp → tunnel degradation predict",
        "inject": [
            "bash",
            "scripts/inject_rain_fade.sh",
            "--host",
            HOST,
            "--steps",
            "8",
            "--step-sec",
            "8",
            "--start-ms",
            "5",
            "--end-ms",
            "45",
        ],
        "clear": ["bash", "scripts/inject_rain_fade.sh", "--clear", "--host", HOST],
        "seed_delay_s": 20,
        "seed": {
            "title": "Rain fade — GRE latency rising (predict before TT&C breach)",
            "alert_class": "tunnel_degradation",
            "root_cause": "physical_path_degradation",
            "severity": "1B",
            "path": "eth0",
            "eta_minutes": 2.0,
            "confidence": 0.9,
            "concerns": [
                "TT&C SLA — latency climbing toward ≤25 ms ceiling on gre-te",
                "Gold CE (NRSC) availability 99.9% at risk if rain fade continues",
                "Physical / optical path degradation on preferred underlay",
                "Approve → eth0 backup before TT&C fail-closed",
            ],
        },
    },
    "cpu_stress": {
        "label": "CPU / crypto stress",
        "blurb": "PE CPU burn → crypto exhaustion predict",
        "inject": [
            "bash",
            "scripts/inject_cpu_stress.sh",
            "--host",
            HOST,
            "--seconds",
            "75",
        ],
        "clear": ["bash", "scripts/inject_cpu_stress.sh", "--clear", "--host", HOST],
        "seed_delay_s": 15,
        "seed": {
            "title": "CPU exhaustion — PE crypto load (predict underlay stress)",
            "alert_class": "congestion_breach",
            "root_cause": "cpu_crypto_exhaustion",
            "severity": "2B",
            "path": "eth0",
            "eta_minutes": 2.5,
            "confidence": 0.88,
            "concerns": [
                "PE crypto exhaustion — IPsec + HTB LLQ may stall",
                "TT&C (1:10) and Payload (1:15) share the stressed PE",
                "Congestion breach predicted before util / latency AAR trip",
                "Approve → eth0 backup to shed crypto load on preferred path",
            ],
        },
    },
    "bgp_flap": {
        "label": "BGP flap",
        "blurb": "Short soft-clear storm → route instability predict",
        "inject": [
            "bash",
            "scripts/inject_bgp_flap.sh",
            "--host",
            HOST,
            "--cycles",
            "24",
            "--period-sec",
            "3",
        ],
        "clear": ["bash", "scripts/inject_bgp_flap.sh", "--clear", "--host", HOST],
        "seed_delay_s": 12,
        "seed": {
            "title": "BGP instability — flap rate rising",
            "alert_class": "bgp_route_flap",
            "root_cause": "route_flap",
            "severity": "3B",
            "path": "eth0",
            "eta_minutes": 2.0,
            "confidence": 0.9,
            "concerns": [
                "Control-plane flap — vrf-mission routes oscillating",
                "CE reachability and path preference may flip mid-flow",
                "TT&C / Payload forwarding unstable until BGP settles",
                "Approve → eth0 backup to stabilize while flaps clear",
            ],
        },
    },
    "ce_sla_conflict": {
        "label": "CE SLA conflict",
        "blurb": "Bronze CE surge vs Gold TT&C — rogue/victim",
        "inject": [
            "bash",
            "scripts/inject_ce_sla_conflict.sh",
            "--host",
            HOST,
            "--force-clear",
            "--steps",
            "4",
            "--step-sec",
            "15",
            "--start-mbit",
            "3",
            "--end-mbit",
            "20",
        ],
        "clear": [
            "bash",
            "scripts/inject_ce_sla_conflict.sh",
            "--clear",
            "--host",
            HOST,
        ],
        "seed_delay_s": 25,
        "seed": {
            "title": "CE SLA policy conflict — Bronze surge endangering Gold",
            "alert_class": "policy_drift",
            "root_cause": "ce_sla_conflict",
            "severity": "5B",
            "path": "eth0",
            "eta_minutes": 2.5,
            "confidence": 0.92,
            "rogue_ce": "ce-mauritius",
            "victim_ce": "ce-a",
            "rogue_sla": "Bronze 90%",
            "victim_sla": "Gold 99.9%",
            "affected_scope": [
                "rogue: ce-mauritius (Bronze 90%)",
                "victim: ce-a (Gold 99.9%)",
                "PE1 station1",
            ],
            "concerns": [
                "Rogue CE-Mauritius (Bronze 90%) surging ~2–3 → ~20 Mbps",
                "Victim CE-NRSC / ce-a (Gold 99.9%) — TT&C CoS at risk of starvation",
                "CE↔CE SLA policy conflict on shared PE HTB — Bronze must not preempt Gold",
                "Approve protects critical class (throttle rogue / steer backup)",
            ],
        },
    },
    "loss_progression": {
        "label": "Loss ramp",
        "blurb": "GRE netem loss → loss TTI / Payload SLA risk",
        "inject": [
            "bash",
            "scripts/inject_loss_progression.sh",
            "--host",
            HOST,
            "--steps",
            "5",
            "--step-sec",
            "12",
        ],
        "clear": [
            "bash",
            "scripts/inject_loss_progression.sh",
            "--clear",
            "--host",
            HOST,
        ],
        "seed_delay_s": 18,
        "seed": {
            "title": "Loss progression — GRE loss climbing toward Payload SLA",
            "alert_class": "tunnel_degradation",
            "root_cause": "loss_progression",
            "severity": "4B",
            "path": "eth0",
            "eta_minutes": 2.0,
            "confidence": 0.89,
            "eta_loss_minutes": 1.5,
            "concerns": [
                "Payload SLA — loss climbing toward ≤2% (TT&C ≤0.1% even tighter)",
                "GRE loss head ETA ≈ 1.5 min — predictive breach window open",
                "Mission underlay packet loss threatens Gold + Silver CE flows",
                "Approve → eth0 backup before loss SLA trip",
            ],
        },
    },
}


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": fid,
            "label": meta["label"],
            "blurb": meta["blurb"],
            "duration_hint_s": 60 + int(meta.get("seed_delay_s") or 0),
        }
        for fid, meta in FAULTS.items()
    ]


def _write_status() -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(_state, indent=2) + "\n", encoding="utf-8")


def status() -> dict[str, Any]:
    with _lock:
        alive = _proc is not None and _proc.poll() is None
        if _state.get("running") and not alive and _proc is not None:
            _state["running"] = False
            _state["message"] = _state.get("message") or "inject finished"
        out = dict(_state)
        out["catalog"] = catalog()
        out["prom"] = _prom_url()
        out["active_fabric"] = fabric_mod.get_active()
        return out


def _campaign_owns_pi_inject() -> bool:
    """True while protocol campaign BGP (or similar) owns station1 injectors."""
    try:
        r = subprocess.run(
            ["pgrep", "-af", "inject_bgp_flap|run_protocol_campaign"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except Exception:  # noqa: BLE001
        return False
    lines = [
        ln
        for ln in (r.stdout or "").splitlines()
        if ln.strip() and "pgrep" not in ln
    ]
    return any("inject_bgp" in ln or "run_protocol_campaign" in ln for ln in lines)


def _run_cmd(argv: list[str], *, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _clear_all_demo(*, fabric: str | None = None) -> None:
    target = fabric or fabric_mod.get_active()
    if target == "gns3":
        # Adapters clear via lab/gns3/inject when ready; no-op until then.
        clear_sh = REPO_ROOT / "lab" / "gns3" / "inject" / "clear_all.sh"
        if clear_sh.is_file():
            try:
                _run_cmd(["bash", str(clear_sh)], timeout=60)
            except Exception:  # noqa: BLE001
                pass
        return
    for meta in FAULTS.values():
        try:
            _run_cmd(meta["clear"], timeout=60)
        except Exception:  # noqa: BLE001
            pass


def _prom_latency_gre() -> Optional[float]:
    fab = fabric_mod.get_active()
    if fab == "gns3":
        q = (
            'sdwan_path_latency_ms{job="deca_gns3_fabric",host="gns3-pe1",'
            'path="gre",src="edge",fabric="gns3"}'
        )
    else:
        q = (
            'sdwan_path_latency_ms{job="deca_kafka_telemetry_bridge",'
            'host="station1",path="gre",src="edge"}'
        )
    url = f"{_prom_url().rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': q})}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = json.loads(resp.read().decode())
        rows = body.get("data", {}).get("result") or []
        if not rows:
            # Fallback: hit exporter directly when Prom has not scraped yet
            if fab == "gns3":
                try:
                    with urllib.request.urlopen("http://127.0.0.1:9275/metrics", timeout=2) as resp:
                        for line in resp.read().decode().splitlines():
                            if "sdwan_path_latency_ms" in line and 'path="gre"' in line and not line.startswith("#"):
                                return float(line.rsplit(" ", 1)[-1])
                except Exception:  # noqa: BLE001
                    return None
            return None
        return float(rows[0]["value"][1])
    except Exception:  # noqa: BLE001
        return None


def _start_gns3(fault_id: str, *, started_by: str) -> dict[str, Any]:
    """Dispatch to GNS3 inject adapters (NetEM + iperf3 — Pi twin; no TRex)."""
    global _proc, _watcher
    adapter = REPO_ROOT / "lab" / "gns3" / "inject" / f"{fault_id}.sh"
    if not fabric_mod.gns3_ready():
        return {
            "ok": False,
            "error": (
                "GNS3 fabric not marked ready — touch "
                "`/media/brain/Shaik's/gns3/projects/DECA_READY` after topology is up."
            ),
            "active_fabric": "gns3",
            "catalog": catalog(),
        }
    if not adapter.is_file():
        return {
            "ok": False,
            "error": f"GNS3 adapter missing for {fault_id}",
            "catalog": catalog(),
        }
    meta = FAULTS[fault_id]
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {
                "ok": False,
                "error": f"fault already running: {_state.get('fault_id')}",
                "status": status(),
            }
    _clear_all_demo(fabric="gns3")
    log_lines = [f"start {fault_id} on gns3 by {started_by}"]
    env = os.environ.copy()
    env.setdefault("DECA_REQUIRE_LIVE", "1")
    # Align demo shapes with Pi / docs/shared_fault_book.json
    shape = {
        "rain_fade": {
            "STEPS": "8",
            "STEP_SEC": "8",
            "START_MS": "5",
            "END_MS": "45",
            "JITTER_MS": "4",
        },
        "cpu_stress": {"DUR": "75"},
        "bgp_flap": {"CYCLES": "24", "PERIOD": "3"},
        "loss_progression": {
            "STEPS": "5",
            "STEP_SEC": "12",
            "END_LOSS": "3.5",
            "START_PCT": "0",
        },
        "util_congestion": {
            "STEPS": "6",
            "STEP_SEC": "20",
            "START_MBIT": "5",
            "END_MBIT": "30",
        },
        "ce_sla_conflict": {
            "STEPS": "4",
            "STEP_SEC": "15",
            "START_MBIT": "3",
            "END_MBIT": "20",
        },
    }.get(fault_id, {})
    env.update(shape)
    proc = subprocess.Popen(
        ["bash", str(adapter)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    with _lock:
        _proc = proc
        _state.update(
            {
                "running": True,
                "fault_id": fault_id,
                "fabric": "gns3",
                "label": meta["label"],
                "message": (
                    f"Injecting {meta['label']} on GNS3 (iperf3 + NetEM — Pi twin)…"
                ),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "started_by": started_by,
                "seeded_alert": None,
                "log_tail": log_lines[-20:],
                "pid": proc.pid,
            }
        )
        _write_status()

    t = threading.Thread(
        target=_watcher,
        args=(fault_id, float(meta["seed_delay_s"]), dict(meta["seed"])),
        daemon=True,
        name=f"fault-seed-gns3-{fault_id}",
    )
    _watcher = t
    t.start()

    def _reap() -> None:
        assert proc is not None
        out, _ = proc.communicate()
        with _lock:
            if out:
                lines = [ln for ln in out.splitlines() if ln.strip()][-15:]
                _state["log_tail"] = (_state.get("log_tail") or [])[-5:] + lines
            if _state.get("fault_id") == fault_id:
                _state["running"] = False
                if "finished" not in (_state.get("message") or ""):
                    _state["message"] = (
                        _state.get("message") or f"{meta['label']} GNS3 inject finished"
                    )
                _write_status()

    threading.Thread(target=_reap, daemon=True, name=f"fault-reap-gns3-{fault_id}").start()
    return {"ok": True, "fault_id": fault_id, "fabric": "gns3", "status": status()}


def _seed(seed: dict[str, Any], fault_id: str) -> dict[str, Any]:
    lat = _prom_latency_gre()
    body = dict(seed)
    summary = (
        f"NOC demo fault `{fault_id}` is live on the fabric. "
        "Watch telemetry move; Approve steers backup before SLA breach."
    )
    if lat is not None:
        summary += f" Live GRE latency ≈ {lat:.2f} ms."
        body.setdefault("contributing_signals", {})
        body["contributing_signals"]["latency_gre_ms"] = lat
    body["summary"] = summary
    body["enrich_q3"] = True

    # Live Q2 oneshot — shows Decide *how* the model saw this inject.
    try:
        import model_detect

        with _lock:
            _state["message"] = (
                f"{FAULTS[fault_id]['label']} live — running Q2 detect on Prom…"
            )
            _write_status()
        detection = model_detect.detect_live(fault_id=fault_id)
        body = model_detect.merge_into_seed(body, detection)
        with _lock:
            _state["model_detection"] = {
                "ok": bool(detection.get("ok")),
                "severity": detection.get("severity"),
                "q2_confidence": detection.get("q2_confidence"),
                "matches_demo_fault": detection.get("matches_demo_fault"),
                "explanation": (detection.get("explanation") or "")[:240],
            }
            _state.setdefault("log_tail", []).append(
                "q2_detect "
                + (
                    f"sev={detection.get('severity')} p={detection.get('q2_confidence')} "
                    f"match={detection.get('matches_demo_fault')}"
                    if detection.get("ok")
                    else f"fail={detection.get('error')}"
                )
            )
            _write_status()
    except Exception as exc:  # noqa: BLE001
        body.setdefault("model_detection", {"ok": False, "error": str(exc)})
        with _lock:
            _state.setdefault("log_tail", []).append(f"q2_detect_error:{exc}")
            _write_status()

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API.rstrip('/')}/api/v1/simulation/seed-preemption",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _watcher(fault_id: str, delay: float, seed: dict[str, Any]) -> None:
    time.sleep(max(1.0, delay))
    with _lock:
        if _state.get("fault_id") != fault_id:
            return
    try:
        res = _seed(seed, fault_id)
        with _lock:
            _state["seeded_alert"] = res.get("alert_id")
            _state["message"] = (
                f"{FAULTS[fault_id]['label']} live — Decide card seeded "
                f"(alert {res.get('alert_id')}). Approve when ready."
            )
            _state.setdefault("log_tail", []).append(
                f"seeded alert_id={res.get('alert_id')} class={res.get('alert_class')}"
            )
            _write_status()
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["message"] = f"inject running; seed failed: {exc}"
            _write_status()


def start(fault_id: str, *, started_by: str = "deca-ui") -> dict[str, Any]:
    global _proc, _watcher
    if fault_id not in FAULTS:
        return {"ok": False, "error": f"unknown fault_id={fault_id}", "catalog": catalog()}
    active = fabric_mod.get_active()
    if active == "gns3":
        return _start_gns3(fault_id, started_by=started_by)
    if _campaign_owns_pi_inject():
        return {
            "ok": False,
            "error": (
                "Pi protocol campaign owns station1 injectors (BGP/L3+). "
                "Leave Simple faults idle until the stamp finishes, or switch "
                "fabric to GNS3 when that topology is ready."
            ),
            "active_fabric": "pi",
            "catalog": catalog(),
        }
    meta = FAULTS[fault_id]
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {
                "ok": False,
                "error": f"fault already running: {_state.get('fault_id')}",
                "status": status(),
            }

    _clear_all_demo(fabric="pi")
    log_lines: list[str] = [f"start {fault_id} on pi by {started_by}"]
    proc = subprocess.Popen(
        meta["inject"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    with _lock:
        _proc = proc
        _state.update(
            {
                "running": True,
                "fault_id": fault_id,
                "fabric": "pi",
                "label": meta["label"],
                "message": f"Injecting {meta['label']} on Pi… telemetry should move within ~10–20s",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "started_by": started_by,
                "seeded_alert": None,
                "log_tail": log_lines[-20:],
                "pid": proc.pid,
            }
        )
        _write_status()

    t = threading.Thread(
        target=_watcher,
        args=(fault_id, float(meta["seed_delay_s"]), dict(meta["seed"])),
        daemon=True,
        name=f"fault-seed-{fault_id}",
    )
    _watcher = t
    t.start()

    def _reap() -> None:
        assert proc is not None
        out, _ = proc.communicate()
        with _lock:
            if out:
                lines = [ln for ln in out.splitlines() if ln.strip()][-15:]
                _state["log_tail"] = (_state.get("log_tail") or [])[-5:] + lines
            if _state.get("fault_id") == fault_id:
                _state["running"] = False
                if "finished" not in (_state.get("message") or ""):
                    _state["message"] = (
                        _state.get("message") or f"{meta['label']} inject finished"
                    )
                _write_status()

    threading.Thread(target=_reap, daemon=True, name=f"fault-reap-{fault_id}").start()
    return {"ok": True, "fault_id": fault_id, "status": status()}


def clear(*, reason: str = "operator_clear", fabric: str | None = None) -> dict[str, Any]:
    global _proc
    with _lock:
        fid = _state.get("fault_id")
        started_fabric = (
            fabric
            or _state.get("fabric")
            or fabric_mod.get_active()
        )
        if _proc is not None and _proc.poll() is None:
            try:
                _proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        _proc = None
        _state["running"] = False
        _state["message"] = f"cleared ({reason})"
        _state["fault_id"] = None
        _state["fabric"] = None
        _write_status()
    # Never run Pi clear scripts while campaign owns injectors (would fight BGP).
    if started_fabric == "pi" and _campaign_owns_pi_inject():
        return {
            "ok": True,
            "cleared": fid,
            "skipped_inject_clear": True,
            "message": "demo cleared; skipped netem clear — protocol campaign owns injectors",
            "status": status(),
        }
    _clear_all_demo(fabric=str(started_fabric) if started_fabric else None)
    return {"ok": True, "cleared": fid, "status": status()}
