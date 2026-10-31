"""test_review.py — Unit tests for human review flow (SPEC §13)."""

import json
from src import db, memory, review
from src.config import DB_PATH


def test_review_approve_and_reject_flow():
    conn = db.get_conn(DB_PATH)
    try:
        # Create a mock pending item
        test_qid = "Q_UNIT_REV"
        conn.execute(
            """
            INSERT OR REPLACE INTO questions (id, version, stem, options_json, key, category, status)
            VALUES (?, 1, 'Unit test stem', '{"A":"1","B":"2","C":"3","D":"4"}', 'A', 'quant', 'live')
            """,
            (test_qid,),
        )
        fix_dict = {"fix_type": "change_key", "new_key": "B", "rationale": "Key error in question"}
        ev_dict = {"stats": {"D": -0.25}, "solver": {"majority_answer": "B"}}

        cur = conn.execute(
            """
            INSERT INTO review_queue (run_id, question_id, verdict, fix_json, evidence_json, confidence, status)
            VALUES ('run_unit', ?, 'WRONG_KEY', ?, ?, 0.95, 'pending')
            """,
            (test_qid, json.dumps(fix_dict), json.dumps(ev_dict)),
        )
        rev_id = cur.lastrowid
        conn.commit()

        # Test list_pending
        pending = review.list_pending(conn=conn)
        pending_ids = [p["id"] for p in pending]
        assert rev_id in pending_ids

        # Test approve
        app_res = review.approve(rev_id, conn=conn)
        assert app_res["status"] == "approved"
        assert app_res["new_version"] == 2

        # Check question table
        new_q = conn.execute("SELECT version, key, status FROM questions WHERE id=? AND status='live'", (test_qid,)).fetchone()
        assert new_q["version"] == 2
        assert new_q["key"] == "B"

        old_q = conn.execute("SELECT status FROM questions WHERE id=? AND version=1", (test_qid,)).fetchone()
        assert old_q["status"] == "superseded"

        # Check audit log
        audit = conn.execute("SELECT * FROM audit_log WHERE question_id=? AND action='approve'", (test_qid,)).fetchone()
        assert audit is not None
        assert audit["actor"] == "human_reviewer"

        # Check memory healed check
        assert memory.is_question_healed(test_qid, conn=conn) is True

        # Test reject on a second item
        test_qid2 = "Q_UNIT_REJ"
        conn.execute(
            """
            INSERT OR REPLACE INTO questions (id, version, stem, options_json, key, category, status)
            VALUES (?, 1, 'Unit test stem 2', '{"A":"1","B":"2","C":"3","D":"4"}', 'A', 'quant', 'live')
            """,
            (test_qid2,),
        )
        cur2 = conn.execute(
            """
            INSERT INTO review_queue (run_id, question_id, verdict, fix_json, evidence_json, confidence, status)
            VALUES ('run_unit', ?, 'NON_DISCRIMINATING', '{"fix_type":"retire_replace"}', '{}', 0.90, 'pending')
            """,
            (test_qid2,),
        )
        rev_id2 = cur2.lastrowid
        conn.commit()

        rej_res = review.reject(rev_id2, note="Please do not retire; rewrite instead", conn=conn)
        assert rej_res["status"] == "rejected"

        # Check memory rejection record
        mem_info = memory.recall(question_id=test_qid2, conn=conn)
        assert "retire_replace" in mem_info["rejected_fix_types"]

        # Check audit log for reject
        audit2 = conn.execute("SELECT * FROM audit_log WHERE question_id=? AND action='reject'", (test_qid2,)).fetchone()
        assert audit2 is not None

    finally:
        conn.close()
