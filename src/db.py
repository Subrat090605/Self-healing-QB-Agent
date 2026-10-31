"""db.py — SQLite helpers: schema creation, connection management, and trace logging.

All access goes through get_conn() so the path is always sourced from config.
Schema defined in SPEC §4.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from src.config import DB_PATH

# -- Schema ---------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS questions (
    id          TEXT,
    version     INT,
    stem        TEXT,
    options_json TEXT,
    key         TEXT,
    category    TEXT,
    status      TEXT DEFAULT 'live',
    PRIMARY KEY (id, version)
);

CREATE TABLE IF NOT EXISTS attempts (
    student_id  INT,
    question_id TEXT,
    chosen      TEXT,
    correct     INT,
    ts          INT
);

CREATE TABLE IF NOT EXISTS trace_events (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    step        INT,
    type        TEXT,
    payload_json TEXT,
    ts          REAL
);

CREATE TABLE IF NOT EXISTS solver_runs (
    question_id     TEXT,
    version         INT,
    run_idx         INT,
    answer          TEXT,
    defensible_json TEXT,
    confidence      REAL,
    reasoning       TEXT,
    used_code       INT,
    PRIMARY KEY (question_id, version, run_idx)
);

CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    question_id TEXT,
    verdict     TEXT,
    evidence_json TEXT,
    status      TEXT          -- cleared|submitted|refused|watchlist
);

CREATE TABLE IF NOT EXISTS review_queue (
    id          INTEGER PRIMARY KEY,
    run_id      TEXT,
    question_id TEXT,
    verdict     TEXT,
    fix_json    TEXT,
    evidence_json TEXT,
    confidence  REAL,
    status      TEXT DEFAULT 'pending',   -- pending|approved|rejected
    reviewer_note TEXT,
    decided_ts  REAL
);

CREATE TABLE IF NOT EXISTS agent_memory (
    key         TEXT PRIMARY KEY,
    value_json  TEXT,
    updated_ts  REAL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,
    ts          REAL,
    actor       TEXT,
    action      TEXT,
    question_id TEXT,
    detail_json TEXT
);
"""

_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_attempts_qid   ON attempts (question_id);
CREATE INDEX IF NOT EXISTS idx_trace_run      ON trace_events (run_id);
CREATE INDEX IF NOT EXISTS idx_findings_run   ON findings (run_id);
CREATE INDEX IF NOT EXISTS idx_rqueue_status  ON review_queue (status);
"""


# -- Connection -----------------------------------------------------------------

def get_conn(path: Path = DB_PATH) -> sqlite3.Connection:
    """Return a sqlite3 connection with row_factory and WAL mode enabled."""
    conn = sqlite3.connect(str(path), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(path: Path = DB_PATH) -> None:
    """Create all tables and indexes if they do not exist."""
    with get_conn(path) as conn:
        conn.executescript(_DDL)
        conn.executescript(_INDEX_DDL)
        conn.commit()


# -- Trace helpers --------------------------------------------------------------

def log_event(
    run_id: str,
    step: int,
    type_: str,
    payload: dict[str, Any],
    path: Path = DB_PATH,
) -> None:
    """Insert one row into trace_events.

    Args:
        run_id:  Unique identifier for this agent run.
        step:    Step number within the run (0-indexed).
        type_:   Event type: PLAN|ACT|OBSERVE|REPLAN|GUARDRAIL|REFUSAL|ERROR|RESULT.
        payload: Arbitrary dict serialised to JSON.
    """
    with get_conn(path) as conn:
        conn.execute(
            "INSERT INTO trace_events (run_id, step, type, payload_json, ts) VALUES (?,?,?,?,?)",
            (run_id, step, type_, json.dumps(payload), time.time()),
        )
        conn.commit()


# -- Generic query helpers ------------------------------------------------------

def execute(
    sql: str,
    params: tuple = (),
    path: Path = DB_PATH,
) -> None:
    """Run a non-SELECT statement (INSERT / UPDATE / DELETE)."""
    with get_conn(path) as conn:
        conn.execute(sql, params)
        conn.commit()


def query(
    sql: str,
    params: tuple = (),
    path: Path = DB_PATH,
) -> list[dict[str, Any]]:
    """Run a SELECT and return a list of dicts."""
    with get_conn(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(
    sql: str,
    params: tuple = (),
    path: Path = DB_PATH,
) -> dict[str, Any] | None:
    """Run a SELECT and return the first row as dict, or None."""
    with get_conn(path) as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None
