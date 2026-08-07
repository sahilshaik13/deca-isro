"""DECA Orchestrator FastAPI routes (fleet / alerts / ask / runs / actions)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import ask_service
import config
import controller_client
import ingest
import playbooks
import repos
import simulation_runner
import topology
from db import init_db

router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


class RunCreate(BaseModel):
    run_id: str
    mode: str = "live"
    notes: str = ""


class AskBody(BaseModel):
    question: str
    run_id: Optional[str] = None


class ActionBody(BaseModel):
    path: Optional[str] = Field(default=None, description="gre|eth0 for force_path")
    reason: str = "orchestrator_approve"
    operator_note: str = ""
    # Multi-operator NOC: which human Approved/Rejected (audit trail)
    approved_by: str = "deca-ui"


class SimulationStartBody(BaseModel):
    dry: bool = False
    started_by: str = "deca-ui"


class SimulationStopBody(BaseModel):
    reason: str = "operator_stop"


class ControllerActionBody(BaseModel):
    op: str = Field(description="force_path|clear_force|reset_autonomy|bgp_soft_clear")
    path: Optional[str] = Field(default=None, description="gre|eth0 for force_path")
    reason: str = "orchestrator"
    approved_by: str = "deca-ui"


class FaultStartBody(BaseModel):
    fault_id: str
    started_by: str = "deca-ui"


class FaultClearBody(BaseModel):
    reason: str = "operator_clear"


class FabricSetBody(BaseModel):
    active: str = Field(description="pi | gns3")
    set_by: str = "deca-ui"


class TrafficStartBody(BaseModel):
    profile: str = Field(
        default="mixed",
        description="ttc | payload | admin | mixed",
    )
    duration_s: int = Field(
        default=0,
        description="0 = run until stop; else seconds",
    )
    started_by: str = "deca-ui"


class TrafficStopBody(BaseModel):
    reason: str = "operator_stop"


class CaptureOpenBody(BaseModel):
    link_id: str
    from_id: str = ""
    to_id: str = ""
    fabric: Optional[str] = None


class CaptureStopBody(BaseModel):
    link_id: Optional[str] = None


class SeedPreemptionBody(BaseModel):
    title: str = "Impending Congestion Detected"
    host: str = "station1"
    path: str = "eth0"
    confidence: float = 0.91
    eta_minutes: float = 4.0
    run_id: Optional[str] = None
    # Q2 root-cause → Decide rail class (must be UI-actionable)
    alert_class: str = "congestion_breach"
    root_cause: str = ""
    root_cause_label: Optional[int] = None
    summary: str = ""
    severity: str = ""
    # Optional ranked playbook override from gate; else built server-side
    recommended_actions: Optional[list[str]] = None
    # PS13-O2.2 named path asymmetry (GRE vs eth0 dual probe)
    path_asymmetry_ms: Optional[float] = None
    path_asymmetry_abs_ms: Optional[float] = None
    path_asymmetry_detected: bool = False
    contributing_signals: Optional[dict[str, float]] = None
    affected_scope: Optional[list[str]] = None
    eta_loss_minutes: Optional[float] = None
    eta_jitter_minutes: Optional[float] = None
    eta_util_minutes: Optional[float] = None
    # CE↔CE SLA conflict (ISRO mentor — rogue vs victim attribution)
    rogue_ce: Optional[str] = None
    victim_ce: Optional[str] = None
    rogue_sla: Optional[str] = None
    victim_sla: Optional[str] = None
    # Operator-facing concerns (SLA / CoS / layer) shown on Decide rail
    concerns: Optional[list[str]] = None
    # Q1 urgency clock wording: hard_sla (lat/loss/jitter) | soft_ceiling (util HTB)
    urgency_clock_kind: Optional[str] = None
    urgency_lead_head: Optional[str] = None
    arbitration: Optional[dict[str, Any]] = None
    # Live Q2 oneshot evidence (dashboard Simple faults / infer)
    model_detection: Optional[dict[str, Any]] = None
    # Simple-fault inject id (for clear / resolve)
    noc_demo_fault: Optional[str] = None
    # q1_lstm_prom | q2_only_advisory_clock | …
    eta_source: Optional[str] = None
    # Multi-operator NOC audit (optional)
    operator_id: Optional[str] = None
    # Q3: attach English NLP async by default (math gate does not wait)
    enrich_q3: bool = True
    q3_use_llm: bool = True


class Q3ExplainBody(BaseModel):
    title: str = ""
    summary: str = ""
    root_cause: str = ""
    severity: str = ""
    alert_class: str = ""
    host: str = "station1"
    path: str = "eth0"
    eta_minutes: Optional[float] = None
    use_llm: bool = True
    alert_id: Optional[int] = None


def _default_concerns(body: "SeedPreemptionBody", alert_class: str) -> list[str]:
    """Mentor-facing concerns for Decide — what is at risk if operator waits."""
    out: list[str] = []
    if body.concerns:
        return [str(c) for c in body.concerns if str(c).strip()]

    rc = (body.root_cause or "").lower()
    if body.rogue_ce or body.victim_ce or rc == "ce_sla_conflict":
        rogue = body.rogue_ce or "lower-SLA CE"
        victim = body.victim_ce or "higher-SLA CE"
        out.append(
            f"CE↔CE SLA conflict — rogue {rogue}"
            + (f" ({body.rogue_sla})" if body.rogue_sla else "")
            + f" endangering victim {victim}"
            + (f" ({body.victim_sla})" if body.victim_sla else "")
        )
        out.append("Gold / TT&C CoS (ToS 0x88 → HTB 1:10) must not be starved by Bronze surge")
        out.append("Approve steers backup underlay + protects critical class before 99.9% SLA miss")
        return out

    if alert_class == "tunnel_degradation" or rc in (
        "physical_path_degradation",
        "loss_progression",
        "rain_fade",
    ):
        out.append("TT&C SLA at risk — latency ≤25 ms · jitter ≤5 ms · loss ≤0.1%")
        if body.eta_loss_minutes is not None:
            out.append(f"Payload / loss head ETA ≈ {body.eta_loss_minutes} min to breach")
        else:
            out.append("Mission GRE underlay degrading — Gold CE availability threatened")
        out.append("Preferred path gre-te may fail closed for TT&C if crypto/path collapses")
    elif (
        (body.urgency_clock_kind or "") == "soft_ceiling"
        or (body.urgency_lead_head or "") == "util"
        or rc in ("util_congestion", "ce_sla_conflict")
        or (alert_class == "congestion_breach" and body.eta_util_minutes is not None
            and body.eta_loss_minutes is None and "cpu" not in rc and "crypto" not in rc
            and "flap" not in rc)
    ):
        # Util-led / L5–L6 texture: soft HTB ceiling — not hard TT&C SLA breach copy.
        out.append("Approaching configured HTB ceiling (soft util gate / O2.1) — not a hard TT&C SLA trip yet")
        if body.eta_util_minutes is not None:
            out.append(f"Util head ETA ≈ {body.eta_util_minutes} min to ceiling")
        out.append("Payload CoS (ToS 0x80 → HTB 1:15) shares PE with TT&C — steer before headroom collapses")
        if rc == "ce_sla_conflict" or body.rogue_ce:
            out.append("Q2 owns CE rogue vs organic congestion — util Q1 head only sees the ceiling clock")
    elif alert_class == "congestion_breach" or "cpu" in rc or "crypto" in rc:
        out.append("PE crypto / HTB headroom — IPsec + LLQ may stall under CPU stress")
        out.append("Payload CoS (ToS 0x80 → HTB 1:15) and TT&C share the stressed PE")
        out.append("Steer to eth0 backup before util / latency ceilings trip AAR")
    elif alert_class == "bgp_route_flap" or "flap" in rc or "route" in rc:
        out.append("Control-plane instability — VRF mission routes oscillating")
        out.append("CE reachability and TT&C/Payload path preference may flip unpredictably")
        out.append("Approve backup underlay to stabilize forwarding while BGP settles")
    elif alert_class == "policy_drift":
        out.append("Policy / CoS drift — observed marking or AAR intent no longer matches contract")
        out.append("Verify CE tier + PE HTB/VRF before TT&C or Gold SLA is missed")
    elif alert_class == "vrf_leakage":
        out.append("VRF leakage — mission vs admin separation at risk")
        out.append("Isolate underlay; protect TT&C fail-closed posture")
    else:
        out.append("Predictive breach on preferred underlay — Approve before SLA window closes")

    if body.severity:
        out.append(f"Q2 severity {body.severity} — HITL gate required (no silent auto-steer)")
    return out


def bootstrap() -> None:
    init_db()


def _active_run() -> Optional[str]:
    return repos.get_active_run_id()


@router.get("/runs")
def get_runs():
    active = _active_run()
    stored = repos.list_runs()
    available = ingest.list_available_run_ids()
    return {
        "active_run_id": active,
        "runs": stored,
        "available": available,
    }


@router.post("/runs")
def post_run(body: RunCreate):
    row = repos.set_active_run(body.run_id, mode=body.mode, notes=body.notes)
    refreshed = ingest.refresh_run(body.run_id, force=True)
    return {"ok": True, "run": row, "ingest": refreshed}


@router.post("/runs/{run_id}/refresh")
def refresh_run(run_id: str):
    return ingest.refresh_run(run_id)


@router.get("/fleet")
def get_fleet(run_id: Optional[str] = None):
    import fabric as fabric_mod
    import topology as topology_mod

    rid = run_id or _active_run()
    ticks: list[dict[str, Any]] = []
    if rid:
        ingest.refresh_run(rid)
        ticks = repos.latest_host_ticks(rid)
    active = fabric_mod.get_active()
    # Drop cross-fabric tick hosts so a Pi blind-run cannot blank GNS3 (or reverse)
    ticks = fabric_mod.filter_rows_for_fabric(ticks, active)
    by_host = {t["host"]: t for t in ticks}
    catalog = config.site_catalog_for(active)

    # Live Prom overlay for both fabrics so the fleet strip is never blank
    # when replay ticks are empty (sim-live / demo with no blind-run ingest).
    alert_by_host: dict[str, dict[str, Any]] = {}
    try:
        for a in repos.list_alerts(run_id=rid, status="active", limit=50) if rid else []:
            h = str(a.get("host") or "")
            if active == "gns3" and not h.startswith("gns3"):
                continue
            if active == "pi" and h.startswith("gns3"):
                continue
            payload = a.get("payload") if isinstance(a.get("payload"), dict) else {}
            alert_by_host[h] = {
                "class": a.get("class"),
                "confidence": payload.get("confidence"),
                "eta_minutes": (
                    payload.get("eta_minutes")
                    or payload.get("eta_loss_minutes")
                    or payload.get("eta_util_minutes")
                    or payload.get("eta_jitter_minutes")
                    or a.get("eta")
                ),
            }
    except Exception:
        alert_by_host = {}

    mission: dict[str, Any] | None = None
    try:
        from prometheus_feed import fetch_live_network

        live = fetch_live_network()
        mission = controller_client.fetch_mission_metrics()
        conflict = int((mission or {}).get("conflict") or 0)
        for st in live.get("stations") or []:
            host = st.get("host")
            if not host:
                continue
            existing = by_host.get(host) or {}
            m = dict(st.get("metrics") or existing.get("metrics") or {})
            online = st.get("status") == "online"
            reachable = bool(st.get("reachable", online))
            if not reachable:
                online = False
            lat = float(m.get("latency_gre_ms") or 0.0)
            loss = float(m.get("packet_loss_pct") or 0.0)
            budget_lat, budget_loss = 25.0, 0.1
            lat_ratio = min(1.0, lat / budget_lat) if budget_lat else 0.0
            loss_ratio = min(1.0, loss / budget_loss) if budget_loss else 0.0
            headroom = max(0.0, 1.0 - max(lat_ratio, loss_ratio))
            derived_conf = round(0.55 + 0.44 * headroom, 2)

            seeded = alert_by_host.get(host) or {}
            conf = existing.get("confidence")
            if conf is None:
                conf = seeded.get("confidence")
            if conf is None:
                conf = derived_conf if online else None

            eta = existing.get("eta_minutes")
            if eta is None:
                eta = seeded.get("eta_minutes")
            if eta is None and online:
                if lat >= budget_lat or loss >= budget_loss:
                    eta = round(max(0.8, float(seeded.get("eta_minutes") or 5.0) * 0.4), 1)
                elif lat >= budget_lat * 0.6 or loss >= budget_loss * 0.6 or conflict:
                    remain = max(0.05, 1.0 - max(lat_ratio, loss_ratio))
                    eta = round(max(1.5, remain * 5.0), 1)
                elif seeded.get("class") in (
                    "congestion_breach",
                    "tunnel_degradation",
                    "bgp_route_flap",
                    "policy_drift",
                ):
                    eta = float(seeded.get("eta_minutes") or 4.0)
                    conf = min(float(conf or 0.9), 0.88)

            confirmed = existing.get("confirmed")
            if not online:
                confirmed = "offline"
                conf = None
                eta = None
                m = {}
            elif not confirmed:
                confirmed = "healthy"

            by_host[host] = {
                **existing,
                "host": host,
                "confirmed": confirmed,
                "advisory": existing.get("advisory"),
                "confidence": float(conf) if conf is not None else None,
                "eta_minutes": float(eta) if eta is not None else None,
                "metrics": m,
                "reachable": online,
                "seeded_class": seeded.get("class"),
                "source": ("gns3_live" if active == "gns3" else "pi_live")
                if online
                else existing.get("source"),
            }
    except Exception:
        pass

    sites = []
    for site in catalog:
        host_states = []
        mclass = str(site.get("mission_class") or "payload")
        for h in site.get("hosts") or []:
            tick = dict(by_host.get(h) or {"host": h, "confirmed": None, "advisory": None})
            m = tick.get("metrics") or {}
            lat = float(m.get("latency_gre_ms") or 0.0)
            loss = float(m.get("packet_loss_pct") or 0.0)
            if tick.get("confirmed") == "offline" or tick.get("reachable") is False:
                tick["confirmed"] = "offline"
                tick["reachable"] = False
                tick["confidence"] = None
                tick["eta_minutes"] = None
                tick["metrics"] = {}
            elif m:
                seeded_eta = tick.get("eta_minutes")
                if mclass == "ttc":
                    budget_lat, budget_loss = 25.0, 0.1
                elif mclass == "be":
                    budget_lat, budget_loss = 999.0, 5.0
                else:
                    budget_lat, budget_loss = 80.0, 2.0
                lat_ratio = min(1.0, lat / budget_lat) if budget_lat else 0.0
                loss_ratio = min(1.0, loss / max(budget_loss, 1e-6))
                headroom = max(0.0, 1.0 - max(lat_ratio, loss_ratio))
                if tick.get("confidence") is None:
                    tick["confidence"] = round(0.55 + 0.44 * headroom, 2)

                if lat > budget_lat or loss > budget_loss:
                    tick["confirmed"] = "tunnel_degradation"
                    # Still actionable for HITL — do not flash ETA=0 the instant SLA trips.
                    tick["eta_minutes"] = round(
                        max(0.8, float(seeded_eta or 5.0) * 0.4),
                        1,
                    )
                elif mclass == "ttc" and (lat >= budget_lat * 0.6 or loss >= budget_loss * 0.6):
                    tick["confirmed"] = "tunnel_degradation"
                    remain = max(0.05, 1.0 - max(lat_ratio, loss_ratio))
                    tick["eta_minutes"] = round(max(1.5, remain * 5.0), 1)
                elif mclass == "ttc" and tick.get("seeded_class") in (
                    "congestion_breach",
                    "tunnel_degradation",
                    "bgp_route_flap",
                    "policy_drift",
                ):
                    tick["confirmed"] = tick.get("seeded_class") or "congestion_breach"
                    tick["eta_minutes"] = float(seeded_eta or 4.0)
                elif not tick.get("confirmed"):
                    tick["confirmed"] = "healthy"
                    if mclass != "ttc":
                        tick["eta_minutes"] = None
            host_states.append(tick)
        status = "unknown"
        if host_states:
            if any(s.get("confirmed") == "offline" or s.get("reachable") is False for s in host_states):
                status = "offline"
            elif any(
                (s.get("confirmed") or "-")
                not in ("-", "none", "healthy", "normal", "offline", "", None)
                for s in host_states
            ):
                status = "alert"
            elif any(s.get("confirmed") for s in host_states):
                status = "ok"
            elif any((s.get("metrics") or {}) for s in host_states):
                status = "ok"
                for s in host_states:
                    if not s.get("confirmed") and (s.get("metrics") or {}):
                        s["confirmed"] = "healthy"
        elif site.get("virtual"):
            status = "virtual"
        sites.append({**site, "hosts_state": host_states, "status": status})
    # Reuse mission from Prom overlay when available (avoid second :9280 scrape).
    if mission is None:
        mission = controller_client.fetch_mission_metrics()
    return {
        "run_id": rid,
        "fabric": active,
        "prometheus": fabric_mod.prom_url_for(active),
        "topology": topology_mod.layout(active),
        "sites": sites,
        "ticks": ticks,
        "mission": mission,
    }


def _slim_alert(row: dict[str, Any]) -> dict[str, Any]:
    """Drop duplicated payload_json blob (~majority of alert JSON size)."""
    out = dict(row)
    out.pop("payload_json", None)
    return out


@router.get("/alerts")
def get_alerts(
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    include_history: bool = False,
):
    import fabric as fabric_mod

    rid = run_id or _active_run()
    if rid:
        ingest.refresh_run(rid)
    fab = fabric_mod.get_active()

    def _for_fabric(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_slim_alert(a) for a in fabric_mod.filter_rows_for_fabric(rows, fab)]

    if status:
        filtered = repos.list_alerts(run_id=rid, status=status, limit=limit)
        return {"run_id": rid, "fabric": fab, "alerts": _for_fabric(filtered)}

    active = repos.list_alerts(run_id=rid, status="active", limit=limit)
    out: dict[str, Any] = {
        "run_id": rid,
        "fabric": fab,
        "active": _for_fabric([a for a in active if a.get("status") == "active"]),
    }
    # History is ~1MB and unused by the NOC poll path — opt-in only.
    if include_history:
        history = repos.list_alerts(run_id=rid, status=None, limit=limit)
        out["history"] = _for_fabric(history)
    else:
        out["history"] = []
    return out


@router.post("/controller/action")
def controller_action(body: ControllerActionBody):
    """Fabric-aware force_path / clear_force / reset / soft-clear (Pi :9280 or GNS3 mission)."""
    return controller_client.post_action(
        op=body.op,
        path=body.path,
        reason=body.reason,
        approved_by=body.approved_by,
    )


@router.post("/ask")
def post_ask(body: AskBody):
    rid = body.run_id or _active_run()
    result = ask_service.run_ask(body.question, run_id=rid)
    qid = repos.insert_query(
        run_id=rid,
        question=body.question,
        intent=result.get("intent"),
        answer=result.get("answer") or "",
        generation_path=result.get("generation_path") or "",
    )
    return {"ok": True, "query_id": qid, "run_id": rid, **result}


@router.get("/history")
def get_history(
    run_id: Optional[str] = None,
    limit: int = 50,
    include_alerts: bool = False,
    include_queries: bool = False,
):
    """Default: actions only (NOC uses recent actions). Fat alert blobs are opt-in."""
    import fabric as fabric_mod

    rid = run_id or _active_run()
    fab = fabric_mod.get_active()
    out: dict[str, Any] = {
        "run_id": rid,
        "fabric": fab,
        "actions": repos.list_actions(run_id=rid, limit=limit),
        "alerts": [],
        "queries": [],
    }
    if include_alerts:
        out["alerts"] = [
            _slim_alert(a)
            for a in fabric_mod.filter_rows_for_fabric(
                repos.list_alerts(run_id=rid, limit=limit), fab
            )
        ]
    if include_queries:
        out["queries"] = repos.list_queries(run_id=rid, limit=limit)
    return out


def _proposal_from_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Map alert → controller force_path proposal (backup underlay eth0 by default)."""
    payload = alert.get("payload") or {}
    actions = payload.get("recommended_actions") or []
    path = "eth0"
    for a in actions:
        s = str(a).lower()
        if "gre" in s and "prefer" in s:
            path = "gre"
        if "eth0" in s or "backup" in s or "failover" in s:
            path = "eth0"
    return {
        "op": "force_path",
        "path": path,
        "class": alert.get("class"),
        "host": alert.get("host"),
        "reason": f"approve alert#{alert.get('id')} {alert.get('class')}",
    }


@router.post("/actions/{alert_id}/approve")
def approve_action(alert_id: int, body: ActionBody | None = None):
    """Run budgeted action_sequence; force_path is never skipped for risk tiers."""
    import fabric as fabric_mod

    body = body or ActionBody()
    alert = repos.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    fab = fabric_mod.get_active()
    host = str(alert.get("host") or "")
    if host and not fabric_mod.host_belongs(host, fab):
        raise HTTPException(
            status_code=409,
            detail=(
                f"alert host {host!r} belongs to the other fabric — "
                f"switch Simulation source to match before Approve "
                f"(active={fab})"
            ),
        )
    proposal = _proposal_from_alert(alert)
    if body.path:
        proposal["path"] = body.path
    proposal["reason"] = body.reason or proposal["reason"]
    payload = alert.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    seq = payload.get("action_sequence")
    if not isinstance(seq, list) or not seq:
        seq = playbooks.action_sequence(
            path=proposal.get("path") or "eth0",
            severity=str(payload.get("severity") or ""),
            alert_class=str(alert.get("class") or ""),
            root_cause=str(payload.get("root_cause") or ""),
        )
    if body.path:
        for step in seq:
            if step.get("op") == "force_path":
                step["path"] = body.path

    t0 = time.monotonic()
    step_results: list[dict[str, Any]] = []
    force_path_done_at: float | None = None
    overall_ok = True
    for step in seq:
        op = str(step.get("op") or "")
        budget = float(step.get("budget_sec") or 15.0)
        step_t0 = time.monotonic()
        # Hard wall-clock budget: call with timeout ≤ budget, then always continue.
        timeout = max(1.0, min(budget, 30.0))
        try:
            ctrl = controller_client.post_action(
                op=op,
                path=step.get("path") if op == "force_path" else None,
                reason=str(step.get("reason") or proposal["reason"]),
                approved_by=body.approved_by,
                timeout_sec=timeout,
            )
        except Exception as exc:  # noqa: BLE001
            ctrl = {"ok": False, "error": str(exc), "op": op}
        elapsed = time.monotonic() - step_t0
        # If call finished under budget but budget remains, do not wait — proceed.
        # Budget is a cap, not a sleep.
        step_results.append(
            {
                "op": op,
                "budget_sec": budget,
                "elapsed_sec": round(elapsed, 3),
                "budget_exceeded": elapsed > budget,
                "result": ctrl,
            }
        )
        if op == "force_path":
            force_path_done_at = time.monotonic() - t0
            if not ctrl.get("ok"):
                overall_ok = False
        # soft-clear failure must NOT block force_path (always continue)

    wall = time.monotonic() - t0
    result = {
        "ok": overall_ok,
        "sequence": step_results,
        "wall_clock_sec": round(wall, 3),
        "seed_to_force_path_sec": (
            round(force_path_done_at, 3) if force_path_done_at is not None else None
        ),
    }
    proposal["action_sequence"] = seq
    action_id = repos.insert_action(
        run_id=alert.get("run_id") or _active_run(),
        alert_id=alert_id,
        action="approve",
        proposal=proposal,
        result=result,
        operator_note=body.operator_note,
    )
    repos.set_alert_status(alert_id, "approved" if overall_ok else "approve_failed")

    # HITL steer complete → stop the live inject so the fabric can heal on backup.
    fault_cleared = None
    try:
        import fault_demo

        st = fault_demo.status()
        demo_live = bool(
            st.get("running")
            or st.get("fault_id")
            or st.get("phase") in ("injecting", "seeded", "collapsing", "recovering")
        )
        if overall_ok and demo_live:
            fault_cleared = fault_demo.clear(reason="steered")
    except Exception as exc:  # noqa: BLE001
        fault_cleared = {"ok": False, "error": str(exc)}

    return {
        "ok": overall_ok,
        "action_id": action_id,
        "proposal": proposal,
        "controller": result,
        "fault_cleared": fault_cleared,
    }


@router.post("/actions/{alert_id}/reject")
def reject_action(alert_id: int, body: ActionBody | None = None):
    """Decline steer — stop inject and let the path settle back to healthy naturally."""
    body = body or ActionBody()
    alert = repos.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    result = {"ok": True, "rejected": True}
    action_id = repos.insert_action(
        run_id=alert.get("run_id") or _active_run(),
        alert_id=alert_id,
        action="reject",
        proposal={"alert_id": alert_id},
        result=result,
        operator_note=body.operator_note,
    )
    repos.set_alert_status(alert_id, "rejected")

    fault_cleared = None
    try:
        import fault_demo

        st = fault_demo.status()
        demo_live = bool(
            st.get("running")
            or st.get("fault_id")
            or st.get("phase") in ("injecting", "seeded", "collapsing", "recovering")
        )
        if demo_live:
            # No force_path — stop inject and settle on preferred path.
            fault_cleared = fault_demo.clear(reason="rejected")
    except Exception as exc:  # noqa: BLE001
        fault_cleared = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "action_id": action_id,
        "result": result,
        "fault_cleared": fault_cleared,
    }


class ResolveBody(BaseModel):
    reason: str = "fault_cleared"


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, body: ResolveBody | None = None):
    """Mark alert as resolved — called automatically when a fault demo is cleared.
    This makes the Decide rail go back to healthy and shows no active alerts."""
    body = body or ResolveBody()
    alert = repos.get_alert(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    repos.set_alert_status(alert_id, "resolved")
    return {"ok": True, "alert_id": alert_id, "status": "resolved", "reason": body.reason}


# ── Lab simulation (Start button → background run_simulation.sh) ─────────────


@router.get("/simulation/status")
def simulation_status():
    return simulation_runner.status()


@router.post("/simulation/start")
def simulation_start(body: SimulationStartBody | None = None):
    body = body or SimulationStartBody()
    result = simulation_runner.start(dry=body.dry, started_by=body.started_by)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "start failed")
    return result


@router.post("/simulation/stop")
def simulation_stop(body: SimulationStopBody | None = None):
    body = body or SimulationStopBody()
    result = simulation_runner.stop(reason=body.reason)
    # Belt-and-suspenders: clear leftover policy conflict / human gate even if
    # the sim process trap failed to run reset_sdwan_state.
    try:
        controller_client.post_action(
            op="reset_autonomy",
            reason=f"simulation_stop:{body.reason}",
            approved_by="deca-ui",
        )
    except Exception:  # noqa: BLE001
        pass
    return result


# ── Simple fault buttons (mentor: click → inject → Decide predict) ───────────


@router.get("/fabric")
def fabric_get():
    import fabric as fabric_mod

    return fabric_mod.status()


@router.post("/fabric")
def fabric_set(body: FabricSetBody):
    """Switch NOC fabric — stops other-fabric demos and binds fabric Decide run."""
    import fabric as fabric_mod

    prev = fabric_mod.get_active()
    result = fabric_mod.set_active(body.active, set_by=body.set_by)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "fabric set failed")
    cleanup = fabric_mod.switch_cleanup(prev, body.active)
    result["switch"] = cleanup
    result["active_run_id"] = cleanup.get("run_id")
    return result


@router.get("/faults")
def faults_catalog():
    import fault_demo

    return {"faults": fault_demo.catalog(), "status": fault_demo.status()}


@router.get("/faults/status")
def faults_status():
    import fault_demo

    return fault_demo.status()


@router.post("/faults/start")
def faults_start(body: FaultStartBody):
    import fault_demo

    result = fault_demo.start(body.fault_id, started_by=body.started_by)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error") or "fault start failed")
    return result


@router.post("/faults/clear")
def faults_clear(body: FaultClearBody | None = None):
    import fault_demo

    body = body or FaultClearBody()
    return fault_demo.clear(reason=body.reason)


class ModelDetectBody(BaseModel):
    fault_id: str = ""
    samples: Optional[int] = None
    interval: Optional[float] = None


@router.post("/model/detect")
def model_detect_now(body: ModelDetectBody | None = None):
    """One-shot frozen Q2 detect on live Prom — shows how the model saw a fault."""
    body = body or ModelDetectBody()
    import model_detect

    return model_detect.detect_live(
        fault_id=body.fault_id or "",
        samples=body.samples,
        interval=body.interval,
    )


@router.get("/model/detect")
def model_detect_get(fault_id: str = ""):
    import model_detect

    return model_detect.detect_live(fault_id=fault_id or "")


@router.get("/topology")
def topology_get(fabric: Optional[str] = None):
    import fabric as fabric_mod

    fab = fabric or fabric_mod.get_active()
    return topology.layout(fab)


@router.get("/traffic")
def traffic_status():
    import traffic_demo

    return traffic_demo.status()


@router.post("/traffic/start")
def traffic_start(body: TrafficStartBody):
    import traffic_demo

    result = traffic_demo.start(
        profile=body.profile,
        duration_s=body.duration_s,
        started_by=body.started_by,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409, detail=result.get("error") or "traffic start failed"
        )
    return result


@router.post("/traffic/stop")
def traffic_stop(body: TrafficStopBody | None = None):
    import traffic_demo

    body = body or TrafficStopBody()
    return traffic_demo.stop(reason=body.reason)


@router.get("/capture")
def capture_status():
    import capture_demo

    return capture_demo.status()


@router.post("/capture/open")
def capture_open(body: CaptureOpenBody):
    """Click topology link → start capture + launch Wireshark (Pi or GNS3)."""
    import capture_demo

    result = capture_demo.open_link(
        body.link_id,
        from_id=body.from_id,
        to_id=body.to_id,
        fabric=body.fabric,
    )
    if not result.get("ok"):
        raise HTTPException(
            status_code=409, detail=result.get("error") or "capture open failed"
        )
    return result


@router.post("/capture/stop")
def capture_stop(body: CaptureStopBody | None = None):
    import capture_demo

    body = body or CaptureStopBody()
    return capture_demo.stop_link(body.link_id)


@router.post("/simulation/seed-preemption")
def simulation_seed_preemption(body: SeedPreemptionBody | None = None):
    """Phase 4: insert HITL preemption alert so Approve → POST /action before SLA breach.

    Q1/Q2 math path returns immediately. Optional Q3 enrichment merges `q3_nlp`
    onto the alert payload in a background thread (Decide rail polls it in).
    """
    body = body or SeedPreemptionBody()
    import fabric as fabric_mod

    fab = fabric_mod.get_active()
    # Always seed into the fabric-scoped Decide run (never land GNS3 seed in Pi run)
    rid = body.run_id or fabric_mod.default_run_id(fab)
    repos.set_active_run(rid, mode="live", notes=f"simulation seed ({fab})")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    path = body.path if body.path in ("gre", "eth0") else "eth0"
    host = body.host
    if fab == "gns3" and (not host or str(host).startswith("station")):
        host = "gns3-pe1"
    elif fab == "pi" and (not host or str(host).startswith("gns3")):
        host = "station1"
    allowed = {
        "congestion_breach",
        "tunnel_degradation",
        "bgp_route_flap",
        "vrf_leakage",
        "policy_drift",
    }
    alert_class = body.alert_class if body.alert_class in allowed else "congestion_breach"
    clock_kind = (body.urgency_clock_kind or "").strip().lower()
    if body.summary:
        summary = body.summary
    elif clock_kind == "soft_ceiling" or (body.urgency_lead_head or "") == "util":
        summary = (
            "Predictive util head sees path approaching configured HTB ceiling. "
            "Orchestrator Preemption: Approve to pause autonomy and steer "
            f"to {path} before headroom collapses (soft ceiling — not hard SLA breach wording)."
        )
    else:
        summary = (
            "Predictive model sees preferred-underlay risk against hard SLA. "
            "Orchestrator Preemption: Approve to pause autonomy and steer "
            f"to {path} before SLA breach."
        )
    if body.root_cause:
        summary = f"{summary} Root cause: {body.root_cause}."

    asym_detected = bool(body.path_asymmetry_detected)
    if body.recommended_actions:
        actions = list(body.recommended_actions)
    else:
        actions = playbooks.ranked_actions(
            path=path,
            severity=body.severity,
            alert_class=alert_class,
            root_cause=body.root_cause,
            path_asymmetry_detected=asym_detected,
            rogue_ce=body.rogue_ce,
            victim_ce=body.victim_ce,
        )
    signals: dict[str, float] = dict(body.contributing_signals or {})
    if body.path_asymmetry_ms is not None:
        signals["path_asymmetry_ms"] = float(body.path_asymmetry_ms)
    if body.path_asymmetry_abs_ms is not None:
        signals["path_asymmetry_abs_ms"] = float(body.path_asymmetry_abs_ms)
    payload = {
        "title": body.title,
        "summary": summary,
        "preemption": True,
        "recommended_actions": actions,
        "q3_nlp": "",
        "q3_pending": bool(body.enrich_q3),
        "path_asymmetry_detected": asym_detected,
        "contributing_signals": signals,
    }
    if body.rogue_ce:
        payload["rogue_ce"] = body.rogue_ce
    if body.victim_ce:
        payload["victim_ce"] = body.victim_ce
    if body.rogue_sla:
        payload["rogue_sla"] = body.rogue_sla
    if body.victim_sla:
        payload["victim_sla"] = body.victim_sla
    if body.operator_id:
        payload["operator_id"] = body.operator_id
    if body.path_asymmetry_ms is not None:
        payload["path_asymmetry_ms"] = float(body.path_asymmetry_ms)
    if body.path_asymmetry_abs_ms is not None:
        payload["path_asymmetry_abs_ms"] = float(body.path_asymmetry_abs_ms)
    active = repos.list_alerts(run_id=rid, status="active", limit=50)
    if body.affected_scope:
        scope = list(body.affected_scope)
        payload["affected_scope"] = scope
        payload["correlated_alert_ids"] = []
        payload["correlation_reason"] = ""
        payload["urgency_boost"] = 0
    elif body.rogue_ce or body.victim_ce:
        scope = []
        if body.rogue_ce:
            scope.append(
                f"rogue: {body.rogue_ce}"
                + (f" ({body.rogue_sla})" if body.rogue_sla else "")
            )
        if body.victim_ce:
            scope.append(
                f"victim: {body.victim_ce}"
                + (f" ({body.victim_sla})" if body.victim_sla else "")
            )
        scope.append(f"PE {host}")
        payload["affected_scope"] = scope
        payload["correlated_alert_ids"] = []
        payload["correlation_reason"] = "ce_sla_conflict"
        payload["urgency_boost"] = 1
    else:
        corr = topology.correlate_with_active(
            host=host,
            path=path,
            alert_class=alert_class,
            active_alerts=active,
            fabric=fab,
        )
        payload["affected_scope"] = corr["affected_scope"]
        payload["correlated_alert_ids"] = corr["correlated_alert_ids"]
        payload["correlation_reason"] = corr["correlation_reason"]
        payload["urgency_boost"] = corr["urgency_boost"]
        if corr["urgency_boost"] and body.confidence < 0.99:
            # structural clique elevates urgency without inventing confidence
            body.confidence = min(0.99, float(body.confidence) + 0.02)
    payload["action_sequence"] = playbooks.action_sequence(
        path=path,
        severity=body.severity,
        alert_class=alert_class,
        root_cause=body.root_cause,
    )
    if body.eta_loss_minutes is not None:
        payload["eta_loss_minutes"] = float(body.eta_loss_minutes)
    if body.eta_jitter_minutes is not None:
        payload["eta_jitter_minutes"] = float(body.eta_jitter_minutes)
    if body.eta_util_minutes is not None:
        payload["eta_util_minutes"] = float(body.eta_util_minutes)
    if body.root_cause:
        payload["root_cause"] = body.root_cause
    if body.root_cause_label is not None:
        payload["root_cause_label"] = body.root_cause_label
    if body.severity:
        payload["severity"] = body.severity
    if body.urgency_clock_kind:
        payload["urgency_clock_kind"] = body.urgency_clock_kind
    if body.urgency_lead_head:
        payload["urgency_lead_head"] = body.urgency_lead_head
    if body.arbitration:
        payload["arbitration"] = body.arbitration
    if body.model_detection:
        payload["model_detection"] = body.model_detection
        gp = body.model_detection.get("generation_path")
        if gp:
            payload["model_generation_path"] = gp
    if body.noc_demo_fault:
        payload["noc_demo_fault"] = body.noc_demo_fault
    if body.eta_source:
        payload["eta_source"] = body.eta_source
    payload["concerns"] = _default_concerns(body, alert_class)
    alert_id = repos.upsert_alert(
        {
            "run_id": rid,
            "ts": ts,
            "host": host,
            "class": alert_class,
            "event": "confirmed_raise",
            "confidence": body.confidence,
            "eta": body.eta_minutes,
            "status": "active",
            "generation_path": "lstm_preemption",
            "payload_json": payload,
        }
    )
    if body.enrich_q3:
        try:
            import q3_lnc

            math_ctx = {
                "title": body.title,
                "summary": summary,
                "root_cause": body.root_cause,
                "severity": body.severity,
                "alert_class": alert_class,
                "host": host,
                "path": path,
                "eta_minutes": body.eta_minutes,
                "confidence": body.confidence,
                "eta_source": body.eta_source,
                "model_detection": body.model_detection,
            }
            q3_lnc.enrich_alert_async(
                alert_id,
                math_ctx,
                use_llm=body.q3_use_llm,
                prom_url=config.PROMETHEUS_URL,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[orchestrator] Q3 enrich schedule failed: {exc}")
    return {
        "ok": True,
        "alert_id": alert_id,
        "run_id": rid,
        "title": body.title,
        "path": path,
        "alert_class": alert_class,
        "root_cause": body.root_cause or None,
        "severity": body.severity or None,
        "concerns": payload.get("concerns") or [],
        "q3_pending": bool(body.enrich_q3),
    }


@router.post("/q3/explain")
def q3_explain(body: Q3ExplainBody):
    """On-demand Q3: Prom snapshot + Chroma LNC + optional Phi-3.

    Does not block Decide Approve. If alert_id is set, merges result onto that alert.
    """
    import q3_lnc

    math_ctx = {
        "title": body.title,
        "summary": body.summary,
        "root_cause": body.root_cause,
        "severity": body.severity,
        "alert_class": body.alert_class,
        "host": body.host,
        "path": body.path,
        "eta_minutes": body.eta_minutes,
    }
    result = q3_lnc.explain(
        math_ctx,
        prom_url=config.PROMETHEUS_URL,
        use_llm=body.use_llm,
    )
    if body.alert_id is not None:
        repos.merge_alert_payload(
            body.alert_id,
            {
                "q3_nlp": result.get("q3_nlp") or "",
                "q3_sources": result.get("sources") or [],
                "q3_prom_snapshot": result.get("prom_snapshot") or {},
                "q3_generation_path": result.get("generation_path") or "",
                "q3_ok": bool(result.get("ok")),
                "q3_pending": False,
            },
        )
        result["alert_id"] = body.alert_id
    return result
