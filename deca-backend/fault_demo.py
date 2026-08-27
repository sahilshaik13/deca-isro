"""Simple one-click fault demos for the NOC dashboard (mentor: click → see → predict).

Each fault: live inject on the active fabric; Decide card appears only when
live Q1/Q2 scores warrant it (model-only — no catalog severity/ETA). Clear
stops inject leftovers from this catalog
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
# After Approve/Reject: stop inject, then wait for Prom to settle before "healthy".
RECOVER_SETTLE_S = float(os.environ.get("DECA_RECOVER_SETTLE_S", "35"))
RECOVER_LAT_MS = float(os.environ.get("DECA_RECOVER_LAT_MS", "12"))


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
_recover_token = 0  # bump to cancel pending auto-recover
_state: dict[str, Any] = {
    "running": False,
    "fault_id": None,
    "fabric": None,
    "message": "idle",
    "started_at": None,
    "seeded_alert": None,
    "log_tail": [],
    "phase": "idle",  # idle | injecting | seeded | steered | recovering | collapsing | healthy
}


# Mentor-facing catalog — same shapes as CLI inject commands used in demos.
FAULTS: dict[str, dict[str, Any]] = {
    "rain_fade": {
        "label": "Rain fade",
        "blurb": "Slows the primary satellite path (like weather fade)",
        # Ramp 5→55 ms over ~192s, then hold 120s (mentor demo shape).
        "inject": [
            "bash",
            "scripts/inject_rain_fade.sh",
            "--host",
            HOST,
            "--steps",
            "24",
            "--step-sec",
            "8",
            "--start-ms",
            "5",
            "--end-ms",
            "55",
            "--jitter-ms",
            "5",
            "--hold-sec",
            "120",
        ],
        "clear": ["bash", "scripts/inject_rain_fade.sh", "--clear", "--host", HOST],
        "seed_delay_s": 12,  # first model poll quickly; Prom history fills LSTM window
        "jury_hold_s": 120,
        "inject_duration_s": 312,  # 24*8 + 120
        "seed_context": {"path": "eth0"},
    },
    "cpu_stress": {
        "label": "CPU / crypto stress",
        "blurb": "Overloads the router so encrypted traffic struggles",
        "inject": [
            "bash",
            "scripts/inject_cpu_stress.sh",
            "--host",
            HOST,
            "--seconds",
            "180",
        ],
        "clear": ["bash", "scripts/inject_cpu_stress.sh", "--clear", "--host", HOST],
        "seed_delay_s": 12,
        "jury_hold_s": 120,
        "inject_duration_s": 180,
        "seed_context": {"path": "eth0"},
    },
    "bgp_flap": {
        "label": "BGP flap",
        "blurb": "Shakes the routing table — paths keep flipping",
        "inject": [
            "bash",
            "scripts/inject_bgp_flap.sh",
            "--host",
            HOST,
            "--cycles",
            "18",
            "--period-sec",
            "6",
            "--hold-sec",
            "120",
        ],
        "clear": ["bash", "scripts/inject_bgp_flap.sh", "--clear", "--host", HOST],
        "seed_delay_s": 10,
        "jury_hold_s": 120,
        "inject_duration_s": 228,  # 18*6 + 120
        "seed_context": {"path": "eth0"},
    },
    "ce_sla_conflict": {
        "label": "CE SLA conflict",
        "blurb": "Lower-priority site crowds out a critical mission site",
        "inject": [
            "bash",
            "scripts/inject_ce_sla_conflict.sh",
            "--host",
            HOST,
            "--force-clear",
            "--steps",
            "6",
            "--step-sec",
            "20",
            "--start-mbit",
            "3",
            "--end-mbit",
            "20",
            "--hold-sec",
            "120",
        ],
        "clear": [
            "bash",
            "scripts/inject_ce_sla_conflict.sh",
            "--clear",
            "--host",
            HOST,
        ],
        "seed_delay_s": 18,
        "jury_hold_s": 120,
        "inject_duration_s": 240,  # 6*20 + 120
        "seed_context": {
            "path": "eth0",
            "rogue_ce": "ce-mauritius",
            "victim_ce": "ce-a",
            "rogue_sla": "Bronze 90%",
            "victim_sla": "Gold 99.9%",
            "affected_scope": [
                "rogue: ce-mauritius (Bronze 90%)",
                "victim: ce-a (Gold 99.9%)",
                "PE1 station1",
            ],
        },
    },
    "loss_progression": {
        "label": "Loss ramp",
        "blurb": "Packet loss climbs on the primary path",
        "inject": [
            "bash",
            "scripts/inject_loss_progression.sh",
            "--host",
            HOST,
            "--steps",
            "24",
            "--step-sec",
            "8",
            "--start-pct",
            "0",
            "--end-pct",
            "3.5",
            "--hold-sec",
            "120",
        ],
        "clear": [
            "bash",
            "scripts/inject_loss_progression.sh",
            "--clear",
            "--host",
            HOST,
        ],
        "seed_delay_s": 15,
        "jury_hold_s": 120,
        "inject_duration_s": 312,  # 24*8 + 120
        "seed_context": {"path": "eth0"},
    },
}


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": fid,
            "label": meta["label"],
            "blurb": meta["blurb"],
            "duration_hint_s": int(
                meta.get("inject_duration_s")
                or (60 + int(meta.get("seed_delay_s") or 0) + int(meta.get("jury_hold_s") or 0))
            ),
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


def _resolve_alert_ids(alert_ids: list[Any], reason: str) -> None:
    for aid in alert_ids:
        if aid is None:
            continue
        try:
            req = urllib.request.Request(
                f"{API.rstrip('/')}/api/v1/alerts/{int(aid)}/resolve",
                data=json.dumps({"reason": reason}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception:  # noqa: BLE001
            pass


def _prom_looks_settled() -> bool:
    """True when GRE latency has cooled enough to call the path naturally healthy."""
    lat = _prom_latency_gre()
    if lat is None:
        return False
    try:
        return float(lat) <= RECOVER_LAT_MS
    except (TypeError, ValueError):
        return False


def _schedule_natural_healthy(
    *,
    token: int,
    steered: bool,
    reason: str,
    seeded_alert_id: Optional[int],
    settle_s: float,
) -> None:
    """Wait for telemetry (or timeout) before flipping phase → healthy."""

    def _run() -> None:
        t0 = time.time()
        min_wait = min(8.0, max(3.0, settle_s * 0.25))
        deadline = t0 + max(5.0, settle_s)
        while time.time() < deadline:
            with _lock:
                if token != _recover_token:
                    return
                if _state.get("phase") not in ("recovering", "steered", "collapsing"):
                    return
            if (time.time() - t0) >= min_wait and _prom_looks_settled():
                break
            time.sleep(2.0)

        with _lock:
            if token != _recover_token:
                return
            if _state.get("phase") not in ("recovering", "steered", "collapsing"):
                return
            label = _state.get("label") or "fault"
            _state["phase"] = "healthy"
            _state["running"] = False
            _state["fault_id"] = None
            _state["fabric"] = None
            _state["seeded_alert"] = None
            _state["model_detection"] = None
            if steered:
                _state["message"] = (
                    f"healthy — path settled after Approve (backup still held)"
                )
            else:
                _state["message"] = f"healthy — {label} settled naturally ({reason})"
            _write_status()

        # Resolve Decide spam only after settle (Approve already marked the card).
        try:
            _resolve_preemption_alerts(
                f"settled:{reason}",
                also=int(seeded_alert_id) if seeded_alert_id else None,
            )
        except Exception:  # noqa: BLE001
            _resolve_alert_ids([seeded_alert_id], f"settled:{reason}")

        if not steered:
            _reset_autonomy(f"fault_settled:{reason}")

        try:
            import pipeline_feed

            pipeline_feed.log_inject(f"natural healthy after {reason}")
            pipeline_feed.log_decide(f"path settled — idle ({reason})")
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(
        target=_run, daemon=True, name=f"fault-natural-healthy-{reason}"
    ).start()


def _resolve_preemption_alerts(reason: str, *, also: Optional[int] = None) -> None:
    """Resolve Decide cards from this demo so the rail stops spamming."""
    ids: list[Any] = []
    if also is not None:
        ids.append(also)
    try:
        import repos

        for a in repos.list_alerts(status="active", limit=50):
            payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
            if payload.get("preemption") or payload.get("noc_demo_fault"):
                ids.append(a.get("id"))
    except Exception:  # noqa: BLE001
        pass
    # unique preserve order
    seen: set[Any] = set()
    uniq = []
    for i in ids:
        if i in seen or i is None:
            continue
        seen.add(i)
        uniq.append(i)
    _resolve_alert_ids(uniq, reason)


def _reset_autonomy(reason: str) -> None:
    try:
        req = urllib.request.Request(
            f"{API.rstrip('/')}/api/v1/controller/action",
            data=json.dumps({"op": "reset_autonomy", "reason": reason}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception:  # noqa: BLE001
        pass


def _schedule_auto_recover(fault_id: str, *, grace_s: float = 12.0) -> None:
    """After inject/hold ends with no Approve, collapse → clear → healthy."""
    global _recover_token
    with _lock:
        _recover_token += 1
        token = _recover_token
        _state["phase"] = "collapsing"
        _state["message"] = (
            f"{FAULTS.get(fault_id, {}).get('label', fault_id)} — "
            f"no Approve yet; auto-heal in ~{int(grace_s)}s (or Approve now)"
        )
        _write_status()

    def _run() -> None:
        time.sleep(max(2.0, grace_s))
        with _lock:
            if token != _recover_token:
                return
            if _state.get("fault_id") not in (None, fault_id):
                return
            # Already settling / done — do not clear again.
            if _state.get("phase") in (
                "steered",
                "healthy",
                "idle",
                "recovering",
            ):
                return
        clear(reason="auto_collapse")

    threading.Thread(
        target=_run, daemon=True, name=f"fault-auto-recover-{fault_id}"
    ).start()


def _jury_grace_s(fault_id: str) -> float:
    """Seconds after inject exits before auto-clear (Decide still open briefly)."""
    meta = FAULTS.get(fault_id) or {}
    argv = " ".join(str(x) for x in (meta.get("inject") or []))
    # Live plateau already covered by --hold-sec or a long cpu burn.
    if "--hold-sec" in argv or fault_id == "cpu_stress":
        return 20.0
    return float(meta.get("jury_hold_s") or 120.0)


def _deadline_s(fault_id: str) -> float:
    meta = FAULTS.get(fault_id) or {}
    inject_s = float(meta.get("inject_duration_s") or 0)
    if inject_s <= 0:
        inject_s = float(meta.get("seed_delay_s") or 30) + 120.0
    # Safety net past full inject/hold + settle
    return inject_s + 60.0


def _schedule_hard_deadline(fault_id: str, deadline_s: float) -> None:
    """Safety net: never leave inject/alerts hanging past the demo window."""
    global _recover_token
    with _lock:
        token = _recover_token

    def _run() -> None:
        time.sleep(max(30.0, deadline_s))
        with _lock:
            if token != _recover_token:
                return
            if _state.get("fault_id") != fault_id:
                return
            if _state.get("phase") in ("steered", "healthy", "idle", "recovering"):
                return
        clear(reason="deadline_collapse")

    threading.Thread(
        target=_run, daemon=True, name=f"fault-deadline-{fault_id}"
    ).start()


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
    try:
        import pipeline_feed

        pipeline_feed.log_inject(f"inject {fault_id} on gns3 by {started_by}")
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.copy()
    env.setdefault("DECA_REQUIRE_LIVE", "1")
    # Align demo shapes with Pi / docs/shared_fault_book.json
    shape = {
        "rain_fade": {
            "STEPS": "24",
            "STEP_SEC": "8",
            "START_MS": "5",
            "END_MS": "55",
            "JITTER_MS": "5",
            "HOLD_SEC": "120",
        },
        "cpu_stress": {"DUR": "180"},
        "bgp_flap": {"CYCLES": "18", "PERIOD": "6", "HOLD_SEC": "120"},
        "loss_progression": {
            "STEPS": "24",
            "STEP_SEC": "8",
            "END_LOSS": "3.5",
            "START_PCT": "0",
            "HOLD_SEC": "120",
        },
        "util_congestion": {
            "STEPS": "6",
            "STEP_SEC": "20",
            "START_MBIT": "5",
            "END_MBIT": "30",
            "HOLD_SEC": "120",
        },
        "ce_sla_conflict": {
            "STEPS": "6",
            "STEP_SEC": "20",
            "START_MBIT": "3",
            "END_MBIT": "20",
            "HOLD_SEC": "120",
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
                "phase": "injecting",
                "message": (
                    f"Injecting {meta['label']} on GNS3… "
                    "Decide only if Q1/Q2 scores fire; Approve or wait for auto-collapse"
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
        target=_watcher_thread_func,
        args=(fault_id, float(meta["seed_delay_s"]), dict(meta.get("seed_context") or {})),
        daemon=True,
        name=f"fault-seed-gns3-{fault_id}",
    )
    _watcher = t
    t.start()
    _schedule_hard_deadline(fault_id, _deadline_s(fault_id))

    def _reap() -> None:
        assert proc is not None
        out, _ = proc.communicate()
        should_recover = False
        with _lock:
            if out:
                lines = [ln for ln in out.splitlines() if ln.strip()][-15:]
                _state["log_tail"] = (_state.get("log_tail") or [])[-5:] + lines
            if _state.get("fault_id") == fault_id:
                _state["running"] = False
                if _state.get("phase") not in ("steered", "healthy", "recovering"):
                    _state["message"] = (
                        f"{meta['label']} plateau done — Approve now, or auto-heal shortly"
                    )
                    _write_status()
                    should_recover = True
                else:
                    _write_status()
        if should_recover:
            _schedule_auto_recover(fault_id, grace_s=_jury_grace_s(fault_id))

    threading.Thread(target=_reap, daemon=True, name=f"fault-reap-gns3-{fault_id}").start()
    return {"ok": True, "fault_id": fault_id, "fabric": "gns3", "status": status()}


def _seed_context(fault_id: str) -> dict[str, Any]:
    meta = FAULTS.get(fault_id) or {}
    ctx = dict(meta.get("seed_context") or meta.get("seed") or {})
    ctx.setdefault("path", "eth0")
    return ctx


def _try_model_seed(fault_id: str) -> dict[str, Any] | None:
    """Run Q1/Q2 oneshot; POST Decide only if score gate fires. None = no raise."""
    import model_detect

    ctx = _seed_context(fault_id)
    with _lock:
        _state["message"] = (
            f"{FAULTS[fault_id]['label']} live — waiting on Q1/Q2 scores…"
        )
        _write_status()

    detection = model_detect.detect_live(fault_id=fault_id)
    try:
        import pipeline_feed

        if detection.get("ok"):
            pipeline_feed.log_inference(
                f"Q1/Q2 oneshot fault={fault_id} sev={detection.get('severity')} "
                f"p={detection.get('q2_confidence')} eta_m={detection.get('eta_minutes')} "
                f"eta_s={detection.get('eta_seconds')} match={detection.get('matches_demo_fault')}"
            )
        else:
            pipeline_feed.log_inference(
                f"Q1/Q2 oneshot fail fault={fault_id} err={detection.get('error')}"
            )
    except Exception:  # noqa: BLE001
        pass
    body = model_detect.build_seed_from_detection(
        detection,
        fault_id=fault_id,
        path=str(ctx.get("path") or "eth0"),
        context=ctx,
    )

    lat = _prom_latency_gre()
    with _lock:
        _state["model_detection"] = {
            "ok": bool(detection.get("ok")),
            "severity": detection.get("severity"),
            "q2_confidence": detection.get("q2_confidence"),
            "eta_minutes": (body or {}).get("eta_minutes") or detection.get("eta_minutes"),
            "eta_source": (body or {}).get("eta_source") or detection.get("eta_source"),
            "raise": body is not None,
            "matches_demo_fault": detection.get("matches_demo_fault"),
            "explanation": (detection.get("explanation") or "")[:240],
        }
        eta_bit = ""
        if detection.get("ok") and detection.get("eta_minutes") is not None:
            eta_bit = f" eta={detection.get('eta_minutes')}m"
        elif detection.get("ok") and detection.get("eta_seconds") is not None:
            eta_bit = f" eta_s={detection.get('eta_seconds')}"
        gate = "RAISE" if body is not None else "hold"
        _state.setdefault("log_tail", []).append(
            "q1_q2_detect "
            + (
                f"{gate} sev={detection.get('severity')} p={detection.get('q2_confidence')}"
                f"{eta_bit} match={detection.get('matches_demo_fault')}"
                if detection.get("ok")
                else f"fail={detection.get('error')}"
            )
        )
        if lat is not None and body is not None:
            sigs = dict(body.get("contributing_signals") or {})
            sigs.setdefault("latency_gre_ms", float(lat))
            body["contributing_signals"] = sigs
        _write_status()

    if body is None:
        return None

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API.rstrip('/')}/api/v1/simulation/seed-preemption",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


def _watcher_still_active(fault_id: str) -> bool:
    with _lock:
        if _state.get("fault_id") != fault_id:
            return False
        if _state.get("phase") in ("steered", "healthy", "collapsing", "idle", "recovering"):
            return False
        return True


def _watcher_thread_func(fault_id: str, delay: float, _seed: dict[str, Any] | None = None) -> None:
    """Poll Prom→Q1/Q2 until scores warrant a Decide card, or inject ends."""
    time.sleep(max(1.0, delay))
    if not _watcher_still_active(fault_id):
        return

    meta = FAULTS[fault_id]
    deadline = time.time() + float(
        meta.get("inject_duration_s")
        or (float(meta.get("seed_delay_s") or 30) + float(meta.get("jury_hold_s") or 120))
    )
    # Fast recheck — each oneshot is ~1–3s with Prom history.
    poll_s = float(os.environ.get("DECA_MODEL_SEED_POLL_S", "3"))
    attempt = 0

    while _watcher_still_active(fault_id) and time.time() < deadline:
        attempt += 1
        try:
            res = _try_model_seed(fault_id)
        except Exception as exc:  # noqa: BLE001
            with _lock:
                _state["message"] = (
                    f"{meta['label']} — model detect error (retry): {exc}"
                )
                _state.setdefault("log_tail", []).append(f"model_seed_error:{exc}")
                _write_status()
            res = None

        if res is not None:
            with _lock:
                _state["seeded_alert"] = res.get("alert_id")
                _state["message"] = (
                    f"{meta['label']} — Decide from model scores "
                    f"(alert {res.get('alert_id')}, "
                    f"{res.get('alert_class')}, sev={res.get('severity')}). "
                    "Approve when ready."
                )
                _state.setdefault("log_tail", []).append(
                    f"seeded alert_id={res.get('alert_id')} class={res.get('alert_class')} "
                    f"sev={res.get('severity')} eta={res.get('eta_minutes')} "
                    f"src=model attempt={attempt}"
                )
                _state["phase"] = "seeded"
                _write_status()
            try:
                import pipeline_feed

                pipeline_feed.log_inject(
                    f"model-seeded Decide alert#{res.get('alert_id')} "
                    f"class={res.get('alert_class')} sev={res.get('severity')}"
                )
                pipeline_feed.log_decide(
                    f"seed alert#{res.get('alert_id')} primary={res.get('alert_class')} "
                    f"sev={res.get('severity')} from Q1/Q2 — Approve to steer, or wait for auto-collapse"
                )
                with _lock:
                    md = dict(_state.get("model_detection") or {})
                pipeline_feed.log_copilot(
                    "retrieved: model "
                    f"sev={md.get('severity') or res.get('severity')} "
                    f"p={md.get('q2_confidence') or res.get('confidence')} "
                    f"eta={md.get('eta_minutes') or res.get('eta_minutes')} "
                    f"class={res.get('alert_class')} · Q3 grounding on model scores"
                )
            except Exception:  # noqa: BLE001
                pass
            return

        with _lock:
            md = _state.get("model_detection") or {}
            _state["message"] = (
                f"{meta['label']} injecting — model hold "
                f"(sev={md.get('severity')}, p={md.get('q2_confidence')}); "
                f"recheck in {int(poll_s)}s"
            )
            _write_status()
        # Sleep in slices so steer/clear can abort promptly.
        end = time.time() + poll_s
        while time.time() < end:
            if not _watcher_still_active(fault_id):
                return
            time.sleep(min(2.0, end - time.time()))

    if _watcher_still_active(fault_id):
        with _lock:
            _state["message"] = (
                f"{meta['label']} — inject ending; model never raised "
                "(no Decide card — score gate)"
            )
            _state.setdefault("log_tail", []).append(
                f"model_only_no_raise fault={fault_id} attempts={attempt}"
            )
            _write_status()
        try:
            import pipeline_feed

            pipeline_feed.log_inject(
                f"no Decide card for {fault_id} — Q1/Q2 scores never crossed gate"
            )
        except Exception:  # noqa: BLE001
            pass


def attach_cli(
    fault_id: str,
    *,
    started_by: str = "cli",
    duration_s: float | None = None,
    seed_delay_s: float | None = None,
    cmd_summary: str = "",
) -> dict[str, Any]:
    """Register a laptop CLI inject without spawning the script (script already running).

    Starts the same Q1/Q2 Decide watcher + pipeline Inject feed used by dashboard start,
    so ``deca_watch.sh`` and NOC terminal tabs light up from mentor CLI commands.
    """
    global _proc, _watcher, _recover_token
    if fault_id not in FAULTS:
        return {"ok": False, "error": f"unknown fault_id={fault_id}", "catalog": catalog()}
    meta = FAULTS[fault_id]
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {
                "ok": False,
                "error": f"fault already running via dashboard: {_state.get('fault_id')}",
                "status": status(),
            }
        # Idempotent: laptop re-attach / same fault already live.
        if (
            _state.get("running")
            and _state.get("fault_id") == fault_id
            and _state.get("phase") in ("injecting", "seeded")
        ):
            return {"ok": True, "already": True, "source": _state.get("source"), "status": status()}
        if (
            _state.get("running")
            and _state.get("source") == "cli"
            and _state.get("fault_id")
            and _state.get("fault_id") != fault_id
            and _state.get("phase") in ("injecting", "seeded")
        ):
            return {
                "ok": False,
                "error": f"cli fault already attached: {_state.get('fault_id')}",
                "status": status(),
            }
        _recover_token += 1

    _resolve_preemption_alerts("superseded_by_new_fault")
    delay = float(
        seed_delay_s
        if seed_delay_s is not None
        else (meta.get("seed_delay_s") or 30)
    )
    dur = float(duration_s) if duration_s is not None and duration_s > 0 else float(
        meta.get("inject_duration_s") or (delay + float(meta.get("jury_hold_s") or 120))
    )
    summary = (cmd_summary or "").strip() or f"cli {fault_id}"
    log_lines = [f"cli-attach {fault_id} by {started_by}: {summary}"]
    try:
        import pipeline_feed

        pipeline_feed.log_inject(
            f"CLI inject {fault_id} ({meta['label']}) — {summary}"
        )
        pipeline_feed.log_decide(
            f"watching CLI {fault_id} for Q1/Q2 raise (first poll ~{int(delay)}s)"
        )
    except Exception:  # noqa: BLE001
        pass

    with _lock:
        _proc = None  # physics owned by laptop SSH, not orchestrator Popen
        _state.update(
            {
                "running": True,
                "fault_id": fault_id,
                "fabric": fabric_mod.get_active(),
                "label": meta["label"],
                "phase": "injecting",
                "source": "cli",
                "message": (
                    f"CLI injecting {meta['label']}… "
                    "Decide appears when Q1/Q2 scores fire; Approve on hold"
                ),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "started_by": started_by,
                "seeded_alert": None,
                "log_tail": log_lines[-20:],
                "pid": None,
                "cli_duration_s": dur,
                "cmd_summary": summary,
            }
        )
        _write_status()

    t = threading.Thread(
        target=_watcher_thread_func,
        args=(fault_id, delay, dict(meta.get("seed_context") or {})),
        daemon=True,
        name=f"fault-cli-seed-{fault_id}",
    )
    _watcher = t
    t.start()
    _schedule_hard_deadline(fault_id, dur + 60.0)
    return {"ok": True, "fault_id": fault_id, "source": "cli", "status": status()}


def log_cli(line: str, *, fault_id: str | None = None) -> dict[str, Any]:
    """Append one inject line from CLI → status log_tail + pipeline Inject tab."""
    text = (line or "").rstrip()
    if not text:
        return {"ok": True, "skipped": True}
    with _lock:
        if fault_id and _state.get("fault_id") and fault_id != _state.get("fault_id"):
            return {"ok": False, "error": "fault_id mismatch"}
        tail = list(_state.get("log_tail") or [])
        tail.append(text)
        _state["log_tail"] = tail[-40:]
        _write_status()
    try:
        import pipeline_feed

        pipeline_feed.log_inject(text)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True}


def end_cli(
    fault_id: str = "",
    *,
    reason: str = "cli_hold_done",
) -> dict[str, Any]:
    """CLI inject finished (hold done / Ctrl+C / --clear)."""
    with _lock:
        fid = fault_id or _state.get("fault_id")
        if not fid:
            return {"ok": True, "status": status()}
        if _state.get("fault_id") and fault_id and _state.get("fault_id") != fault_id:
            return {"ok": False, "error": "fault_id mismatch", "status": status()}
        source = _state.get("source")
        phase = _state.get("phase")
        label = _state.get("label") or fid

    if reason in ("cli_clear", "cli_interrupted", "operator_clear"):
        # Physics already cleared by script; settle UI like operator clear.
        return clear(reason="operator_clear" if reason != "cli_interrupted" else "auto_collapse")

    # Hold / ramp finished — keep Decide open briefly (same as dashboard reap).
    should_recover = False
    with _lock:
        if _state.get("fault_id") == fid and source == "cli":
            _state["running"] = False
            if phase not in ("steered", "healthy", "recovering"):
                _state["message"] = (
                    f"{label} plateau done — Approve now, or auto-heal shortly"
                )
                should_recover = True
            _write_status()
    try:
        import pipeline_feed

        pipeline_feed.log_inject(f"CLI inject/hold finished: {fid} ({reason})")
    except Exception:  # noqa: BLE001
        pass
    if should_recover and fid:
        _schedule_auto_recover(str(fid), grace_s=_jury_grace_s(str(fid)))
    return {"ok": True, "fault_id": fid, "status": status()}


def start(fault_id: str, *, started_by: str = "deca-ui") -> dict[str, Any]:
    global _proc, _watcher, _recover_token
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
        _recover_token += 1

    # Drop leftover Decide spam from a previous demo before seeding a new one.
    _resolve_preemption_alerts("superseded_by_new_fault")
    _clear_all_demo(fabric="pi")
    log_lines: list[str] = [f"start {fault_id} on pi by {started_by}"]
    try:
        import pipeline_feed

        pipeline_feed.log_inject(
            f"inject {fault_id} ({meta['label']}) cmd={' '.join(meta['inject'][:6])}…"
        )
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.copy()
    # Inject scripts self-notify when run from a laptop terminal; disable when
    # orchestrator already owns the fault lifecycle.
    env["DECA_CLI_BRIDGE"] = "0"
    proc = subprocess.Popen(
        meta["inject"],
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
                "fabric": "pi",
                "label": meta["label"],
                "phase": "injecting",
                "source": "dashboard",
                "message": (
                    f"Injecting {meta['label']} on Pi… "
                    "Decide appears only if Q1/Q2 scores fire; "
                    "Approve within the hold, or wait for auto-heal"
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
        target=_watcher_thread_func,
        args=(fault_id, float(meta["seed_delay_s"]), dict(meta.get("seed_context") or {})),
        daemon=True,
        name=f"fault-seed-{fault_id}",
    )
    _watcher = t
    t.start()

    # Hard deadline past full inject+hold so jury isn't cut off early.
    _schedule_hard_deadline(fault_id, _deadline_s(fault_id))

    def _reap() -> None:
        assert proc is not None
        out, _ = proc.communicate()
        should_recover = False
        with _lock:
            if out:
                lines = [ln for ln in out.splitlines() if ln.strip()][-15:]
                _state["log_tail"] = (_state.get("log_tail") or [])[-5:] + lines
                try:
                    import pipeline_feed

                    for ln in lines[-8:]:
                        pipeline_feed.log_inject(ln)
                except Exception:  # noqa: BLE001
                    pass
            if _state.get("fault_id") == fault_id:
                _state["running"] = False
                if _state.get("phase") not in ("steered", "healthy", "recovering"):
                    _state["message"] = (
                        f"{meta['label']} plateau done — Approve now, or auto-heal shortly"
                    )
                    _write_status()
                    try:
                        import pipeline_feed

                        pipeline_feed.log_inject(
                            f"inject/hold finished: {fault_id} — jury window closing"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    should_recover = True
                else:
                    _write_status()
        if should_recover:
            _schedule_auto_recover(fault_id, grace_s=_jury_grace_s(fault_id))

    threading.Thread(target=_reap, daemon=True, name=f"fault-reap-{fault_id}").start()
    return {"ok": True, "fault_id": fault_id, "status": status()}


def clear(*, reason: str = "operator_clear", fabric: str | None = None) -> dict[str, Any]:
    """Stop inject physics, then settle to healthy naturally (Approve/Reject/auto).

    Approve: steer already done by orchestrator; we stop inject and wait for Prom
    to cool before phase=healthy (backup override kept).
    Reject / auto-collapse: stop inject, wait for settle, then reset autonomy.
    """
    global _proc, _recover_token
    seeded_alert_id: Optional[int] = None
    steered = reason in ("steered", "approve", "operator_steer")
    rejected = reason in ("rejected", "reject")
    # Instant snap only for fabric switches / hard operator wipe.
    instant = reason.startswith("fabric_switch") or reason in (
        "operator_clear_now",
        "superseded_by_new_fault",
    )
    natural = (not instant) and (
        steered
        or rejected
        or reason
        in (
            "auto_collapse",
            "deadline_collapse",
            "operator_clear",
            "steered",
        )
    )

    with _lock:
        _recover_token += 1  # cancel pending auto-recover / prior settle
        token = _recover_token
        fid = _state.get("fault_id")
        label = _state.get("label") or fid or "fault"
        seeded_alert_id = _state.get("seeded_alert")
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
        if natural:
            _state["phase"] = "recovering"
            if steered:
                _state["message"] = (
                    f"Approved — inject stopped; waiting for {label} to settle naturally…"
                )
            elif rejected:
                _state["message"] = (
                    f"Rejected — inject stopped; waiting for {label} to settle naturally…"
                )
            else:
                _state["message"] = (
                    f"{label} ending — waiting for path to settle naturally…"
                )
            # Keep fault_id/label visible during settle so UI shows recovering.
        else:
            _state["phase"] = "steered" if steered else "healthy"
            _state["message"] = (
                f"steered — inject stopped ({reason})"
                if steered
                else f"cleared ({reason})"
            )
            _state["fault_id"] = None
            _state["fabric"] = None
            _state["seeded_alert"] = None
            _state["model_detection"] = None
        _write_status()

    if not natural:
        try:
            _resolve_preemption_alerts(
                reason, also=int(seeded_alert_id) if seeded_alert_id else None
            )
        except Exception:  # noqa: BLE001
            _resolve_alert_ids([seeded_alert_id], reason)
        if not steered:
            _reset_autonomy(f"fault_clear:{reason}")

    try:
        import pipeline_feed

        if steered:
            pipeline_feed.log_inject(f"steered — inject stopped, settling ({reason})")
            pipeline_feed.log_decide(
                f"Approve done — waiting for natural healthy ({reason})"
            )
        elif rejected:
            pipeline_feed.log_inject(f"rejected — inject stopped, settling ({reason})")
            pipeline_feed.log_decide(
                f"Reject done — waiting for natural healthy ({reason})"
            )
        else:
            pipeline_feed.log_inject(f"recovering after {reason}")
    except Exception:  # noqa: BLE001
        pass

    # Never run Pi clear scripts while campaign owns injectors (would fight BGP).
    if started_fabric == "pi" and _campaign_owns_pi_inject():
        with _lock:
            _state["phase"] = "healthy"
            _state["fault_id"] = None
            _state["message"] = (
                "demo cleared; skipped netem clear — protocol campaign owns injectors"
            )
            _write_status()
        return {
            "ok": True,
            "cleared": fid,
            "skipped_inject_clear": True,
            "message": _state["message"],
            "status": status(),
        }

    # Stop impairment so Prom can return toward baseline (natural heal on graphs).
    _clear_all_demo(fabric=str(started_fabric) if started_fabric else None)

    if natural:
        _schedule_natural_healthy(
            token=token,
            steered=steered,
            reason=reason,
            seeded_alert_id=seeded_alert_id if isinstance(seeded_alert_id, int) else None,
            settle_s=RECOVER_SETTLE_S,
        )
    else:
        with _lock:
            _state["phase"] = "healthy" if not steered else "steered"
            if not steered:
                _state["message"] = f"healthy — cleared ({reason})"
            _write_status()

    return {"ok": True, "cleared": fid, "recovering": natural, "status": status()}
