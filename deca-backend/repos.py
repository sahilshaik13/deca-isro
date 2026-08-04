"""CRUD helpers for DECA Orchestrator SQLite tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from db import with_conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row) if row is not None else {}


@with_conn
def set_active_run(conn, run_id: str, mode: str = "live", notes: str = "") -> dict[str, Any]:
    started = _utcnow()
    conn.execute(
        """
        INSERT INTO runs (run_id, mode, started_at, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            mode=excluded.mode,
            notes=CASE WHEN excluded.notes != '' THEN excluded.notes ELSE runs.notes END
        """,
        (run_id, mode, started, notes or ""),
    )
    conn.execute(
        "INSERT INTO app_state(key, value) VALUES('active_run_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (run_id,),
    )
    return {"run_id": run_id, "mode": mode, "started_at": started, "notes": notes}


@with_conn
def get_active_run_id(conn) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM app_state WHERE key='active_run_id'"
    ).fetchone()
    return row["value"] if row else None


@with_conn
def list_runs(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@with_conn
def upsert_host_tick(conn, tick: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO host_ticks
            (run_id, ts, host, confirmed, advisory, confidence, eta_minutes, severity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, ts, host) DO UPDATE SET
            confirmed=excluded.confirmed,
            advisory=excluded.advisory,
            confidence=excluded.confidence,
            eta_minutes=excluded.eta_minutes,
            severity=excluded.severity
        """,
        (
            tick["run_id"],
            tick["ts"],
            tick["host"],
            tick.get("confirmed"),
            tick.get("advisory"),
            tick.get("confidence"),
            tick.get("eta_minutes"),
            tick.get("severity"),
        ),
    )


@with_conn
def latest_host_ticks(conn, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT h.* FROM host_ticks h
        INNER JOIN (
            SELECT host, MAX(ts) AS max_ts
            FROM host_ticks WHERE run_id = ?
            GROUP BY host
        ) t ON h.host = t.host AND h.ts = t.max_ts AND h.run_id = ?
        ORDER BY h.host
        """,
        (run_id, run_id),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


@with_conn
def upsert_alert(conn, alert: dict[str, Any]) -> int:
    payload = alert.get("payload_json")
    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)
    cur = conn.execute(
        """
        INSERT INTO alerts
            (run_id, ts, host, class, event, confidence, eta, payload_json,
             generation_path, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, ts, host, class, event) DO UPDATE SET
            confidence=excluded.confidence,
            eta=excluded.eta,
            payload_json=excluded.payload_json,
            generation_path=excluded.generation_path
        """,
        (
            alert["run_id"],
            alert["ts"],
            alert.get("host"),
            alert.get("class") or alert.get("event"),
            alert.get("event") or alert.get("class"),
            alert.get("confidence"),
            alert.get("eta"),
            payload,
            alert.get("generation_path"),
            alert.get("status") or "active",
        ),
    )
    # Return id of matching row
    row = conn.execute(
        """
        SELECT id FROM alerts
        WHERE run_id=? AND ts=? AND IFNULL(host,'')=IFNULL(?, '')
          AND IFNULL(class,'')=IFNULL(?, '') AND IFNULL(event,'')=IFNULL(?, '')
        """,
        (
            alert["run_id"],
            alert["ts"],
            alert.get("host"),
            alert.get("class") or alert.get("event"),
            alert.get("event") or alert.get("class"),
        ),
    ).fetchone()
    return int(row["id"]) if row else int(cur.lastrowid)


@with_conn
def list_alerts(
    conn,
    *,
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM alerts {where} ORDER BY ts DESC LIMIT ?",
        params,
    ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("payload_json"):
            try:
                d["payload"] = json.loads(d["payload_json"])
            except json.JSONDecodeError:
                d["payload"] = None
        out.append(d)
    return out


@with_conn
def get_alert(conn, alert_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        return None
    d = _row_to_dict(row)
    if d.get("payload_json"):
        try:
            d["payload"] = json.loads(d["payload_json"])
        except json.JSONDecodeError:
            d["payload"] = None
    return d


@with_conn
def set_alert_status(conn, alert_id: int, status: str) -> None:
    conn.execute("UPDATE alerts SET status=? WHERE id=?", (status, alert_id))


@with_conn
def merge_alert_payload(conn, alert_id: int, patch: dict[str, Any]) -> bool:
    """Shallow-merge keys into alerts.payload_json (for async Q3 enrichment)."""
    row = conn.execute("SELECT payload_json FROM alerts WHERE id=?", (alert_id,)).fetchone()
    if not row:
        return False
    payload: dict[str, Any] = {}
    raw = row["payload_json"]
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}
    payload.update(patch)
    conn.execute(
        "UPDATE alerts SET payload_json=? WHERE id=?",
        (json.dumps(payload), alert_id),
    )
    return True


@with_conn
def insert_query(
    conn,
    *,
    run_id: Optional[str],
    question: str,
    intent: Any,
    answer: str,
    generation_path: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO queries (run_id, ts, question, intent_json, answer, generation_path)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            _utcnow(),
            question,
            json.dumps(intent) if intent is not None else None,
            answer,
            generation_path,
        ),
    )
    return int(cur.lastrowid)


@with_conn
def list_queries(conn, *, run_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    if run_id:
        rows = conn.execute(
            "SELECT * FROM queries WHERE run_id=? ORDER BY ts DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM queries ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("intent_json"):
            try:
                d["intent"] = json.loads(d["intent_json"])
            except json.JSONDecodeError:
                d["intent"] = None
        out.append(d)
    return out


@with_conn
def insert_action(
    conn,
    *,
    run_id: Optional[str],
    alert_id: Optional[int],
    action: str,
    proposal: Any,
    result: Any,
    operator_note: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO actions
            (run_id, ts, alert_id, action, proposal_json, result_json, operator_note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            _utcnow(),
            alert_id,
            action,
            json.dumps(proposal) if proposal is not None else None,
            json.dumps(result) if result is not None else None,
            operator_note or "",
        ),
    )
    return int(cur.lastrowid)


@with_conn
def list_actions(conn, *, run_id: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
    if run_id:
        rows = conn.execute(
            "SELECT * FROM actions WHERE run_id=? ORDER BY ts DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM actions ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        for key, alias in (("proposal_json", "proposal"), ("result_json", "result")):
            if d.get(key):
                try:
                    d[alias] = json.loads(d[key])
                except json.JSONDecodeError:
                    d[alias] = None
        out.append(d)
    return out


@with_conn
def clear_run_session(conn, run_id: str) -> dict[str, int]:
    """Wipe Decide/history rows for a fabric sim run so Start shows a clean slate."""
    if not run_id:
        return {"alerts": 0, "actions": 0, "queries": 0, "ticks": 0}
    cur_a = conn.execute("DELETE FROM alerts WHERE run_id=?", (run_id,))
    cur_x = conn.execute("DELETE FROM actions WHERE run_id=?", (run_id,))
    cur_q = conn.execute("DELETE FROM queries WHERE run_id=?", (run_id,))
    cur_t = conn.execute("DELETE FROM host_ticks WHERE run_id=?", (run_id,))
    return {
        "alerts": int(cur_a.rowcount or 0),
        "actions": int(cur_x.rowcount or 0),
        "queries": int(cur_q.rowcount or 0),
        "ticks": int(cur_t.rowcount or 0),
    }
