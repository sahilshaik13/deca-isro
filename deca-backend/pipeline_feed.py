"""Write human-readable lines into pipeline_*.log for the NOC TerminalDrawer tabs.

Tabs (already tailed by terminal_manager monitors):
  1. Inject     — fault_demo tee
  2. Telemetry  — Prom snapshot of loss/jitter/util/BGP
  3. Inference  — reformatted infer_q1_q2_live log lines
  4. Copilot    — RAG/ask retrieval notes
  5. Decide     — arbitration / firing_tti_heads from active alerts
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import config

_DATA = Path(config.REPO_ROOT) / "data" / "deca"
INJECT_LOG = _DATA / "pipeline_inject.log"
TELEMETRY_LOG = _DATA / "pipeline_telemetry.log"
INFERENCE_LOG = _DATA / "pipeline_inference.log"
COPILOT_LOG = _DATA / "pipeline_copilot.log"
DECIDE_LOG = _DATA / "pipeline_decide.log"

INFER_SRC = Path(
    os.environ.get("DECA_INFER_LOG", "/tmp/infer_q1_q2_live_demo.log")
)

_started = False
_stop = threading.Event()
_t0 = time.time()


def _ensure_files() -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    for p in (INJECT_LOG, TELEMETRY_LOG, INFERENCE_LOG, COPILOT_LOG, DECIDE_LOG):
        if not p.is_file():
            p.touch()
            _append(p, f"waiting for stream… ({p.name})")


def _append(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line.rstrip() + "\n")
        fh.flush()


def _elapsed() -> str:
    return f"t+{int(time.time() - _t0)}s"


def log_inject(line: str) -> None:
    _append(INJECT_LOG, f"[{_elapsed()}] {line}")


def log_copilot(line: str) -> None:
    _append(COPILOT_LOG, f"[{_elapsed()}] {line}")


def log_decide(line: str) -> None:
    _append(DECIDE_LOG, f"[{_elapsed()}] {line}")


def log_inference(line: str) -> None:
    _append(INFERENCE_LOG, f"[{_elapsed()}] {line}")


def start() -> None:
    global _started, _t0
    if _started:
        return
    _started = True
    _t0 = time.time()
    _ensure_files()
    log_inject("pipeline feed ready — waiting for fault inject")
    log_copilot("pipeline feed ready — waiting for RAG / ask")
    log_decide("pipeline feed ready — waiting for Decide seed")
    log_inference("pipeline feed ready — waiting for infer_q1_q2_live")
    threading.Thread(target=_telemetry_loop, name="pipe-telem", daemon=True).start()
    threading.Thread(target=_infer_tail_loop, name="pipe-infer", daemon=True).start()
    threading.Thread(target=_decide_loop, name="pipe-decide", daemon=True).start()


def stop() -> None:
    _stop.set()


def _telemetry_loop() -> None:
    while not _stop.is_set():
        try:
            from prometheus_feed import fetch_live_network

            live = fetch_live_network()
            raw = live.get("raw") or {}
            stations = live.get("stations") or []
            online = sum(1 for s in stations if s.get("status") == "online")
            line = (
                f"[{_elapsed()}] loss_gre_pct={float(raw.get('packet_loss_pct') or 0):.2f} "
                f"jitter_ms={float(raw.get('jitter_ms') or 0):.2f} "
                f"lat_gre_ms={float(raw.get('latency_gre_ms') or 0):.1f} "
                f"bgp_upd={float(raw.get('bgp_update_rate') or 0):.2f} "
                f"stations_online={online}/{len(stations)}"
            )
            _append(TELEMETRY_LOG, line)
        except Exception as exc:  # noqa: BLE001
            _append(TELEMETRY_LOG, f"[{_elapsed()}] telemetry wait: {exc}")
        for _ in range(20):
            if _stop.is_set():
                return
            time.sleep(0.1)


def _infer_tail_loop() -> None:
    """Reformat infer live log into short jury-facing lines."""
    INFER_SRC.parent.mkdir(parents=True, exist_ok=True)
    if not INFER_SRC.is_file():
        INFER_SRC.touch()
    with INFER_SRC.open("r", encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        while not _stop.is_set():
            line = fh.readline()
            if not line:
                time.sleep(0.3)
                continue
            pretty = _format_infer_line(line.strip())
            if pretty:
                log_inference(pretty)


def _format_infer_line(raw: str) -> str | None:
    if not raw or raw.startswith("#"):
        return None
    low = raw.lower()
    # Prefer already-short lines
    if "window scored" in low or "severity=" in low or "conf=" in low:
        return raw[:240]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        if any(k in low for k in ("severity", "eta", "q2", "q1", "gate", "class")):
            return raw[:240]
        return None
    if not isinstance(obj, dict):
        return None
    sev = obj.get("severity") or obj.get("class") or obj.get("primary")
    conf = obj.get("confidence") or obj.get("conf") or obj.get("q2_confidence")
    eta = obj.get("eta_sec") or obj.get("eta") or obj.get("eta_minutes")
    parts = ["window scored:"]
    if sev is not None:
        parts.append(f"severity={sev}")
    if conf is not None:
        try:
            parts.append(f"conf={float(conf):.2f}")
        except (TypeError, ValueError):
            parts.append(f"conf={conf}")
    if eta is not None:
        parts.append(f"eta={eta}")
    return " ".join(parts)


def _decide_loop() -> None:
    seen: set[Any] = set()
    while not _stop.is_set():
        try:
            import repos

            rid = None
            try:
                from orchestrator import _active_run

                rid = _active_run()
            except Exception:  # noqa: BLE001
                rid = None
            rows = repos.list_alerts(run_id=rid, status="active", limit=5) if rid else []
            if not rows:
                rows = repos.list_alerts(status="active", limit=5)
            for a in rows:
                aid = a.get("id")
                if aid in seen:
                    continue
                seen.add(aid)
                if len(seen) > 200:
                    seen = set(list(seen)[-100:])
                payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
                arb = payload.get("arbitration") if isinstance(payload.get("arbitration"), dict) else {}
                heads = arb.get("firing_tti_heads") or payload.get("firing_tti_heads") or []
                compound = arb.get("compound_suspected") or payload.get("compound_suspected")
                primary = a.get("class") or payload.get("class") or "?"
                playbook = payload.get("playbook") or payload.get("recommended_actions")
                if isinstance(playbook, list):
                    playbook = playbook[0] if playbook else None
                line = (
                    f"alert#{aid} primary={primary} "
                    f"conf={a.get('confidence')} eta={a.get('eta')}"
                )
                if heads:
                    line += f" firing_tti_heads=[{', '.join(str(h) for h in heads)}]"
                if compound:
                    line += " compound_suspected"
                if playbook:
                    line += f" playbook={str(playbook)[:80]}"
                log_decide(line)
        except Exception as exc:  # noqa: BLE001
            _append(DECIDE_LOG, f"[{_elapsed()}] decide wait: {exc}")
        for _ in range(30):
            if _stop.is_set():
                return
            time.sleep(0.1)


def ensure_sessions_meta() -> list[dict[str, str]]:
    """Ids that terminal_manager already spawns for pipeline tabs."""
    return [
        {"id": "m-pipe-inject", "label": "1. Inject", "tab": "inject"},
        {"id": "m-pipe-telem", "label": "2. Telemetry", "tab": "telemetry"},
        {"id": "m-pipe-infer", "label": "3. Inference", "tab": "inference"},
        {"id": "m-pipe-copilot", "label": "4. Copilot", "tab": "copilot"},
        {"id": "m-pipe-decide", "label": "5. Decide", "tab": "decide"},
        {"id": "m-pipe-watch", "label": "6. Live Watch", "tab": "watch"},
    ]
