"""SQLite store for DECA Orchestrator (stdlib sqlite3 — minimal deps)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import config

_LOCK = threading.RLock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'live',
    started_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS host_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    host TEXT NOT NULL,
    confirmed TEXT,
    advisory TEXT,
    confidence REAL,
    eta_minutes REAL,
    severity TEXT,
    UNIQUE(run_id, ts, host)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    host TEXT,
    class TEXT,
    event TEXT,
    confidence REAL,
    eta REAL,
    payload_json TEXT,
    generation_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(run_id, ts, host, class, event)
);

CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT NOT NULL,
    question TEXT NOT NULL,
    intent_json TEXT,
    answer TEXT,
    generation_path TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    ts TEXT NOT NULL,
    alert_id INTEGER,
    action TEXT NOT NULL,
    proposal_json TEXT,
    result_json TEXT,
    operator_note TEXT
);

CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(config.SQLITE_PATH)


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> Path:
    with _LOCK:
        conn = connect()
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    return db_path()


def with_conn(fn):
    """Run fn(conn) under lock; commits on success."""

    def wrapper(*args, **kwargs):
        with _LOCK:
            conn = connect()
            try:
                result = fn(conn, *args, **kwargs)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    return wrapper
