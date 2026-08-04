"""Ingest live-operator declarations + ticks into SQLite."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

import config
import repos

_TICK_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s+"
    r"(?P<host>station\d+|[\w.-]+)\s+"
    r"confirmed=(?P<confirmed>\S+)\s+"
    r"advisory=(?P<advisory>\S+)\s+"
    r"conf=(?P<conf>[\d.]+)\s*"
    r"(?:eta_min=(?P<eta>[\d.]+|null|None))?",
    re.IGNORECASE,
)

_LAST_REFRESH: dict[str, float] = {}
_REFRESH_MIN_SEC = 8.0


def resolve_run_dir(run_id: str) -> Optional[Path]:
    """Find live/<run_id>, archive/live/<run_id>, or active working dir."""
    live = config.OPERATOR_ACTIVE / "live" / run_id
    if live.is_dir():
        return live
    archive = config.OPERATOR_ARCHIVE / run_id
    if archive.is_dir():
        return archive
    alt = config.OPERATOR_ACTIVE / run_id
    if alt.is_dir():
        return alt
    return None


def list_available_run_ids(limit: int = 40) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root, mode_hint in (
        (config.OPERATOR_ACTIVE / "live", "live"),
        (config.OPERATOR_ARCHIVE, "replay"),
    ):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not d.is_dir() or d.name in seen:
                continue
            seen.add(d.name)
            out.append(
                {
                    "run_id": d.name,
                    "mode": mode_hint,
                    "path": str(d),
                    "has_declarations": (d / "declarations.jsonl").is_file(),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _declarations_path(run_dir: Path) -> Optional[Path]:
    for cand in (run_dir / "declarations.jsonl", run_dir / "operator_declarations.jsonl"):
        if cand.is_file():
            return cand
    return None


def _feed_path(run_dir: Path) -> Optional[Path]:
    for cand in (
        run_dir / "operator_feed.log",
        run_dir / "live_operator.log",
        run_dir / "operator.log",
    ):
        if cand.is_file():
            return cand
    return None


def ingest_declarations(run_id: str, run_dir: Optional[Path] = None) -> dict[str, Any]:
    run_dir = run_dir or resolve_run_dir(run_id)
    if not run_dir:
        return {"ok": False, "error": f"run dir not found for {run_id}", "inserted": 0}
    path = _declarations_path(run_dir)
    if not path:
        return {"ok": True, "inserted": 0, "note": "no declarations.jsonl"}
    inserted = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            cls = (
                ev.get("confirmed")
                if ev.get("confirmed") not in (None, "healthy")
                else None
            ) or (
                ev.get("advisory")
                if ev.get("advisory") not in (None, "healthy")
                else None
            ) or ev.get("class") or ev.get("predicted_issue") or ev.get("event")
            host = ev.get("host") or ev.get("site")
            ts = ev.get("ts") or ev.get("timestamp") or ev.get("time")
            if not ts:
                continue
            alert_id = repos.upsert_alert(
                {
                    "run_id": run_id,
                    "ts": str(ts),
                    "host": host,
                    "class": cls,
                    "event": ev.get("event") or cls,
                    "confidence": ev.get("confidence") or ev.get("confidence_score"),
                    "eta": ev.get("eta_minutes") or ev.get("eta") or ev.get("time_to_impact_minutes"),
                    "payload_json": ev,
                    "generation_path": ev.get("generation_path") or "declaration",
                    "status": "active",
                }
            )
            if alert_id:
                inserted += 1
    return {"ok": True, "inserted": inserted, "path": str(path)}


def ingest_operator_feed(run_id: str, run_dir: Optional[Path] = None) -> dict[str, Any]:
    run_dir = run_dir or resolve_run_dir(run_id)
    if not run_dir:
        return {"ok": False, "error": "run dir missing", "ticks": 0}
    path = _feed_path(run_dir)
    if not path:
        return {"ok": True, "ticks": 0, "note": "no operator feed"}
    try:
        import sys
        from pathlib import Path as _P

        scripts = str(_P(__file__).resolve().parents[1] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from deca_test_zone import parse_latest_operator_ticks  # noqa: WPS433

        latest = parse_latest_operator_ticks(path)
    except Exception:
        latest = {}
        # Fallback: legacy regex
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines()[-400:]:
            m = _TICK_RE.search(line)
            if not m:
                continue
            host = m.group("host")
            latest[host] = {
                "ts": m.group("ts"),
                "host": host,
                "confirmed": m.group("confirmed"),
                "advisory": m.group("advisory"),
                "confidence": float(m.group("conf")),
                "eta_minutes": None,
                "active_class": m.group("confirmed"),
            }
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tick in latest.values():
        conf_v = tick.get("confirmed") or tick.get("active_class")
        repos.upsert_host_tick(
            {
                "run_id": run_id,
                "ts": str(tick.get("ts") or now),
                "host": tick["host"],
                "confirmed": conf_v,
                "advisory": tick.get("advisory"),
                "confidence": tick.get("confidence"),
                "eta_minutes": tick.get("eta_minutes"),
                "severity": "alert"
                if conf_v not in ("-", "none", "healthy", "normal", "", None)
                else "ok",
            }
        )
    return {"ok": True, "ticks": len(latest), "path": str(path)}


def refresh_run(run_id: str, *, force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    last = _LAST_REFRESH.get(run_id, 0.0)
    if not force and (now - last) < _REFRESH_MIN_SEC:
        return {
            "run_id": run_id,
            "skipped": True,
            "age_sec": round(now - last, 2),
        }
    run_dir = resolve_run_dir(run_id)
    decl = ingest_declarations(run_id, run_dir)
    ticks = ingest_operator_feed(run_id, run_dir)
    _LAST_REFRESH[run_id] = now
    return {
        "run_id": run_id,
        "declarations": decl,
        "ticks": ticks,
        "run_dir": str(run_dir) if run_dir else None,
    }
