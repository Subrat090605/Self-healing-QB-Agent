"""review.py — Human review queue management, fix application, and audit logging.

Implements SPEC §13:
- list_pending(): Returns pending items in review_queue.
- approve(review_id, edited_fix=None, actor="human_reviewer"):
  Applies fix, creates question version+1, supersedes old version, logs audit entry, marks healed.
- reject(review_id, note, actor="human_reviewer"):
  Rejects fix, remembers note in agent_memory, logs audit entry.
"""

import json
import sqlite3
import time
from typing import Any, Optional

from src import db, memory
from src.config import DB_PATH


def list_pending(conn: Optional[sqlite3.Connection] = None) -> list[dict[str, Any]]:
    """Return all pending review queue items."""
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        rows = conn.execute(
            """
            SELECT id, run_id, question_id, verdict, fix_json, evidence_json, confidence, status
            FROM review_queue
            WHERE status='pending'
            ORDER BY id ASC
            """
        ).fetchall()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "run_id": r["run_id"],
                "question_id": r["question_id"],
                "verdict": r["verdict"],
                "fix": json.loads(r["fix_json"]),
                "evidence": json.loads(r["evidence_json"]),
                "confidence": float(r["confidence"]),
                "status": r["status"],
            })
        return items
    finally:
        if close_conn:
            conn.close()


def approve(
    review_id: int,
    edited_fix: Optional[dict[str, Any]] = None,
    actor: str = "human_reviewer",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Approve a review item, creating a new question version and writing audit log."""
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        row = conn.execute(
            "SELECT * FROM review_queue WHERE id=?",
            (review_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Review queue item {review_id} not found.")

        qid = row["question_id"]
        run_id = row["run_id"]
        fix = edited_fix or json.loads(row["fix_json"])

        # Fetch live question
        q_row = conn.execute(
            "SELECT * FROM questions WHERE id=? AND status='live'",
            (qid,),
        ).fetchone()
        if not q_row:
            raise ValueError(f"Live question {qid} not found.")

        old_version = int(q_row["version"])
        new_version = old_version + 1
        fix_type = fix.get("fix_type", "change_key")

        old_stem = q_row["stem"]
        old_options = json.loads(q_row["options_json"])
        old_key = q_row["key"]
        category = q_row["category"]

        before_state = {
            "version": old_version,
            "stem": old_stem,
            "options": old_options,
            "key": old_key,
        }

        # Compute new state
        if fix_type == "change_key":
            new_stem = old_stem
            new_options = old_options
            new_key = fix.get("new_key", old_key)
        elif fix_type == "rewrite":
            new_stem = fix.get("new_stem") or old_stem
            new_options = fix.get("new_options") or old_options
            new_key = fix.get("new_key", old_key)
        elif fix_type == "retire_replace":
            rep = fix.get("replacement_question") or {}
            new_stem = rep.get("stem", fix.get("new_stem") or old_stem)
            new_options = rep.get("options", fix.get("new_options") or old_options)
            new_key = rep.get("key", fix.get("new_key", old_key))
        else:
            new_stem = fix.get("new_stem") or old_stem
            new_options = fix.get("new_options") or old_options
            new_key = fix.get("new_key", old_key)

        after_state = {
            "version": new_version,
            "stem": new_stem,
            "options": new_options,
            "key": new_key,
            "fix_type": fix_type,
            "rationale": fix.get("rationale", ""),
        }

        # 1. Supersede old question
        conn.execute(
            "UPDATE questions SET status='superseded' WHERE id=? AND version=?",
            (qid, old_version),
        )

        # 2. Insert new question version
        conn.execute(
            """
            INSERT INTO questions (id, version, stem, options_json, key, category, status)
            VALUES (?, ?, ?, ?, ?, ?, 'live')
            """,
            (qid, new_version, new_stem, json.dumps(new_options), new_key, category),
        )

        # 3. Update review queue
        now = time.time()
        conn.execute(
            "UPDATE review_queue SET status='approved', decided_ts=? WHERE id=?",
            (now, review_id),
        )

        # 4. Write audit log
        conn.execute(
            """
            INSERT INTO audit_log (ts, actor, action, question_id, detail_json)
            VALUES (?, ?, 'approve', ?, ?)
            """,
            (
                now,
                actor,
                qid,
                json.dumps({
                    "review_id": review_id,
                    "before": before_state,
                    "after": after_state,
                }),
            ),
        )

        # 5. Record finding healed
        memory.record_finding(
            run_id=run_id,
            question_id=qid,
            verdict=row["verdict"],
            evidence=after_state,
            status="healed",
            conn=conn,
        )

        conn.commit()
        return {
            "status": "approved",
            "question_id": qid,
            "new_version": new_version,
            "before": before_state,
            "after": after_state,
        }
    finally:
        if close_conn:
            conn.close()


def reject(
    review_id: int,
    note: str,
    actor: str = "human_reviewer",
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Reject a review item, storing the feedback note in memory so future runs adapt."""
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        row = conn.execute(
            "SELECT * FROM review_queue WHERE id=?",
            (review_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Review queue item {review_id} not found.")

        qid = row["question_id"]
        run_id = row["run_id"]
        fix = json.loads(row["fix_json"])
        fix_type = fix.get("fix_type", "unknown")

        now = time.time()
        # 1. Update review queue
        conn.execute(
            "UPDATE review_queue SET status='rejected', reviewer_note=?, decided_ts=? WHERE id=?",
            (note, now, review_id),
        )

        # 2. Store rejection in memory for this question
        memory.remember_rejection(qid, fix_type, note, conn=conn)

        # 3. Write audit log
        conn.execute(
            """
            INSERT INTO audit_log (ts, actor, action, question_id, detail_json)
            VALUES (?, ?, 'reject', ?, ?)
            """,
            (
                now,
                actor,
                qid,
                json.dumps({
                    "review_id": review_id,
                    "fix_type": fix_type,
                    "note": note,
                }),
            ),
        )

        # 4. Record finding rejected
        memory.record_finding(
            run_id=run_id,
            question_id=qid,
            verdict=row["verdict"],
            evidence={"note": note, "rejected_fix": fix},
            status="rejected",
            conn=conn,
        )

        conn.commit()
        return {
            "status": "rejected",
            "question_id": qid,
            "note": note,
        }
    finally:
        if close_conn:
            conn.close()
