"""memory.py — Within-run state and cross-session persistent SQLite memory.

Implements SPEC §11:
- recall(question_id=None, conn=None) -> dict
- remember_clearance(question_id, reason, run_id, conn) -> None
- remember_rejection(question_id, fix_type, note, conn) -> None
- last_run_summary(summary=None, conn=None) -> dict | None
- Question lifecycle checks: healed, pending, cleared.
"""

import json
import sqlite3
import time
from typing import Any, Optional

from src import db
from src.config import DB_PATH


def _get_conn(conn: Optional[sqlite3.Connection]) -> tuple[sqlite3.Connection, bool]:
    if conn is None:
        return db.get_conn(DB_PATH), True
    return conn, False


def recall(
    question_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Retrieve memory across sessions from SQLite.

    If question_id is provided, returns question-specific past findings and reviewer decisions.
    Otherwise returns global summary: cleared items, approved/rejected fixes, pending items.
    """
    c, close = _get_conn(conn)
    try:
        if question_id:
            # Question-specific memory
            mem_row = c.execute(
                "SELECT value_json FROM agent_memory WHERE key=?",
                (f"cleared:{question_id}",),
            ).fetchone()
            cleared_info = json.loads(mem_row["value_json"]) if mem_row else None

            rej_row = c.execute(
                "SELECT value_json FROM agent_memory WHERE key=?",
                (f"rejected_fix_types:{question_id}",),
            ).fetchone()
            rejected_types = json.loads(rej_row["value_json"]) if rej_row else []

            rq_rows = c.execute(
                "SELECT id, verdict, status, reviewer_note, decided_ts FROM review_queue WHERE question_id=? ORDER BY id DESC",
                (question_id,),
            ).fetchall()
            reviews = [dict(r) for r in rq_rows]

            findings_rows = c.execute(
                "SELECT id, run_id, verdict, status FROM findings WHERE question_id=? ORDER BY id DESC",
                (question_id,),
            ).fetchall()

            return {
                "question_id": question_id,
                "is_cleared": cleared_info is not None,
                "cleared_info": cleared_info,
                "rejected_fix_types": rejected_types,
                "reviews": reviews,
                "findings": [dict(r) for r in findings_rows],
            }

        # Global memory
        cleared_rows = c.execute(
            "SELECT key, value_json FROM agent_memory WHERE key LIKE 'cleared:%'"
        ).fetchall()
        cleared_map = {
            r["key"].replace("cleared:", ""): json.loads(r["value_json"])
            for r in cleared_rows
        }

        approved_rows = c.execute(
            "SELECT DISTINCT question_id FROM review_queue WHERE status='approved'"
        ).fetchall()
        approved_qids = [r["question_id"] for r in approved_rows]

        pending_rows = c.execute(
            "SELECT DISTINCT question_id FROM review_queue WHERE status='pending'"
        ).fetchall()
        pending_qids = [r["question_id"] for r in pending_rows]

        summary_row = c.execute(
            "SELECT value_json FROM agent_memory WHERE key='last_run_summary'"
        ).fetchone()
        last_summary = json.loads(summary_row["value_json"]) if summary_row else None

        return {
            "cleared_questions": list(cleared_map.keys()),
            "cleared_details": cleared_map,
            "approved_healed_questions": approved_qids,
            "pending_review_questions": pending_qids,
            "last_run_summary": last_summary,
        }
    finally:
        if close:
            c.close()


def remember_clearance(
    question_id: str,
    reason: str,
    run_id: str = "agent_run",
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Record that an item was cleared as a decoy or false alarm (SPEC §11)."""
    c, close = _get_conn(conn)
    try:
        now = time.time()
        payload = json.dumps({"reason": reason, "run_id": run_id, "cleared_ts": now})
        c.execute(
            """
            INSERT OR REPLACE INTO agent_memory (key, value_json, updated_ts)
            VALUES (?, ?, ?)
            """,
            (f"cleared:{question_id}", payload, now),
        )
        c.execute(
            """
            INSERT INTO findings (run_id, question_id, verdict, evidence_json, status)
            VALUES (?, ?, 'OK', ?, 'cleared')
            """,
            (run_id, question_id, json.dumps({"reason": reason})),
        )
        c.commit()
    finally:
        if close:
            c.close()


def remember_rejection(
    question_id: str,
    fix_type: str,
    reviewer_note: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Record a rejected fix type so agent tries a different approach on re-run (SPEC §11)."""
    c, close = _get_conn(conn)
    try:
        now = time.time()
        row = c.execute(
            "SELECT value_json FROM agent_memory WHERE key=?",
            (f"rejected_fix_types:{question_id}",),
        ).fetchone()
        types_list = json.loads(row["value_json"]) if row else []
        if fix_type not in types_list:
            types_list.append(fix_type)

        c.execute(
            """
            INSERT OR REPLACE INTO agent_memory (key, value_json, updated_ts)
            VALUES (?, ?, ?)
            """,
            (f"rejected_fix_types:{question_id}", json.dumps(types_list), now),
        )
        c.commit()
    finally:
        if close:
            c.close()


def record_finding(
    run_id: str,
    question_id: str,
    verdict: str,
    evidence: dict[str, Any],
    status: str,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Log an investigation outcome into the findings table."""
    c, close = _get_conn(conn)
    try:
        c.execute(
            """
            INSERT INTO findings (run_id, question_id, verdict, evidence_json, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, question_id, verdict, json.dumps(evidence), status),
        )
        c.commit()
    finally:
        if close:
            c.close()


def last_run_summary(
    summary: Optional[dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[dict[str, Any]]:
    """Get or set the last agent run summary in agent_memory."""
    c, close = _get_conn(conn)
    try:
        if summary is not None:
            c.execute(
                """
                INSERT OR REPLACE INTO agent_memory (key, value_json, updated_ts)
                VALUES ('last_run_summary', ?, ?)
                """,
                (json.dumps(summary), time.time()),
            )
            c.commit()
            return summary
        else:
            row = c.execute(
                "SELECT value_json FROM agent_memory WHERE key='last_run_summary'"
            ).fetchone()
            return json.loads(row["value_json"]) if row else None
    finally:
        if close:
            c.close()


def is_question_healed(question_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Check if question has an approved fix in review_queue (SPEC §11)."""
    c, close = _get_conn(conn)
    try:
        row = c.execute(
            "SELECT 1 FROM review_queue WHERE question_id=? AND status='approved' LIMIT 1",
            (question_id,),
        ).fetchone()
        return row is not None
    finally:
        if close:
            c.close()


def is_question_pending(question_id: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Check if question is currently pending review (SPEC §11)."""
    c, close = _get_conn(conn)
    try:
        row = c.execute(
            "SELECT 1 FROM review_queue WHERE question_id=? AND status='pending' LIMIT 1",
            (question_id,),
        ).fetchone()
        return row is not None
    finally:
        if close:
            c.close()
