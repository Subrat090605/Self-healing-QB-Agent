"""tools.py — Tool registry and execution dispatcher for the orchestrator agent.

Implements SPEC §8:
- Tool registry with OpenAI function calling schemas.
- execute(name, args, ctx) dispatcher with tracing, guardrails, and error handling.
- Strictly prevents live question modification.
"""

import json
import sqlite3
from typing import Any, Optional

from src import db, fixer, guardrails, memory, sandbox, solver, stats
from src.config import DB_PATH


def _fn(name: str, desc: str, props: Optional[dict[str, Any]] = None, req: Optional[list[str]] = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": req or []},
        },
    }


TOOL_DEFINITIONS = [
    _fn("bank_summary", "Get counts of questions, categories, attempts, and pending reviews."),
    _fn("compute_item_stats", "Compute item stats (n, p, D, r_pb, shares) and signals for questions.",
        {"question_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional list of question IDs."}}),
    _fn("get_suspects", "Triage questions and return ranked suspect IDs sorted by defect risk.",
        {"rule": {"type": "string", "enum": ["agent", "naive"]}, "max_suspects": {"type": "integer"}}),
    _fn("analyze_distractors", "Analyze upper/lower 27% option shares and anomaly diagnostic for a question.",
        {"question_id": {"type": "string"}}, ["question_id"]),
    _fn("solve_independently", "Solve a question using independent LLM solver (2 runs, 3rd on disagreement).",
        {"question_id": {"type": "string"}, "n_runs": {"type": "integer"}, "use_code": {"type": "boolean"}}, ["question_id"]),
    _fn("run_python", "Execute Python code in a secure sandbox (5s timeout, no network).",
        {"code": {"type": "string"}}, ["code"]),
    _fn("propose_fix", "Draft a proposed fix JSON (change_key, rewrite, or retire_replace).",
        {"question_id": {"type": "string"}, "verdict": {"type": "string", "enum": ["WRONG_KEY", "AMBIGUOUS", "NON_DISCRIMINATING"]}, "evidence": {"type": "object"}},
        ["question_id", "verdict", "evidence"]),
    _fn("verify_fix", "Verify a proposed fix by re-solving a patched copy 3x in solver.",
        {"question_id": {"type": "string"}, "fix": {"type": "object"}}, ["question_id", "fix"]),
    _fn("submit_for_review", "Enqueue a defective question and proposed fix for human review (enforces two-signal rule and n>=30).",
        {"question_id": {"type": "string"}, "verdict": {"type": "string", "enum": ["WRONG_KEY", "AMBIGUOUS", "NON_DISCRIMINATING"]}, "fix": {"type": "object"}, "evidence": {"type": "object"}, "confidence": {"type": "number"}},
        ["question_id", "verdict", "fix", "evidence", "confidence"]),
    _fn("record_clearance", "Clear a suspect question as a false alarm or valid decoy.",
        {"question_id": {"type": "string"}, "reason": {"type": "string"}}, ["question_id", "reason"]),
    _fn("recall_memory", "Recall past reviewer decisions, healed items, and cleared decoys.",
        {"question_id": {"type": "string"}}),
    _fn("request_more_data", "Refuse to judge a question with insufficient attempts (n < 30). Logs REFUSAL.",
        {"question_id": {"type": "string"}}, ["question_id"]),
    _fn("finish", "Terminate the investigation run with an executive summary.",
        {"summary": {"type": "string"}}, ["summary"]),
]


def _bank_summary_impl(conn: sqlite3.Connection) -> dict[str, Any]:
    q_counts = conn.execute("SELECT category, COUNT(*) as cnt FROM questions WHERE status='live' GROUP BY category").fetchall()
    total_q = sum(r["cnt"] for r in q_counts)
    total_att = conn.execute("SELECT COUNT(*) as cnt FROM attempts").fetchone()["cnt"]
    pending_rev = conn.execute("SELECT COUNT(*) as cnt FROM review_queue WHERE status='pending'").fetchone()["cnt"]
    cleared_cnt = conn.execute("SELECT COUNT(*) as cnt FROM agent_memory WHERE key LIKE 'cleared:%'").fetchone()["cnt"]
    return {
        "total_questions": total_q, "by_category": {r["category"]: r["cnt"] for r in q_counts},
        "total_attempts": total_att, "pending_reviews": pending_rev, "cleared_items": cleared_cnt,
    }


def execute(name: str, args: dict[str, Any], ctx: Optional[dict[str, Any]] = None) -> str:
    """Execute a tool call with tracing, error handling, and guardrail enforcement."""
    ctx = ctx or {}
    run_id, step = ctx.get("run_id", "standalone_run"), ctx.get("step", 0)
    conn = ctx.get("conn")

    # 1. Guardrail check tool allowlist
    if not guardrails.is_tool_allowed(name):
        err_msg = f"Security Error: Tool '{name}' is not in the allowed tool registry."
        db.log_event(run_id, step, "GUARDRAIL", {"tool": name, "blocked": err_msg})
        return err_msg

    # 2. Log ACT event
    db.log_event(run_id, step, "ACT", {"tool": name, "args": args})

    result_str = ""
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        if name == "bank_summary":
            result_str = json.dumps(_bank_summary_impl(conn), indent=2)
        elif name == "compute_item_stats":
            qids = args.get("question_ids")
            df = stats.compute_item_stats(conn=conn, question_ids=qids)
            compact = [
                {"id": r["question_id"], "key": r["key"], "n": r["n"], "p": r["p"], "D": r["D"],
                 "r_pb": r["r_pb"], "stats_signal": r["stats_signal"], "insufficient": r["insufficient"]}
                for _, r in df.iterrows()
            ]
            result_str = json.dumps(compact)
        elif name == "get_suspects":
            rule, max_s = args.get("rule", "agent"), args.get("max_suspects")
            suspects = stats.get_suspects(rule=rule, max_suspects=max_s, conn=conn)
            result_str = json.dumps({"rule": rule, "suspects": suspects})
        elif name == "analyze_distractors":
            result_str = json.dumps(stats.analyze_distractors(args["question_id"], conn=conn), indent=2)
        elif name == "solve_independently":
            qid, n_runs = args["question_id"], int(args.get("n_runs", 2))
            res = solver.solve(qid, n_runs=n_runs, use_code=bool(args.get("use_code", False)), conn=conn)
            compact_res = {
                "question_id": res.get("question_id"),
                "majority_answer": res.get("majority_answer"),
                "agreement": res.get("agreement"),
                "any_multi_defensible": res.get("any_multi_defensible"),
                "mean_confidence": res.get("mean_confidence"),
                "runs": [
                    {
                        "answer": r.get("answer"),
                        "confidence": r.get("confidence"),
                        "defensible_options": r.get("defensible_options", []),
                        "reasoning": (r.get("reasoning", "")[:100] + "...") if len(r.get("reasoning", "")) > 100 else r.get("reasoning", ""),
                    }
                    for r in res.get("runs", [])
                ],
            }
            result_str = json.dumps(compact_res, indent=2)
        elif name == "run_python":
            result_str = sandbox.run_python(args["code"])
        elif name == "propose_fix":
            fix = fixer.propose_fix(args["question_id"], args["verdict"], args["evidence"], conn=conn)
            result_str = json.dumps(fix, indent=2)
        elif name == "verify_fix":
            v_res = fixer.verify_fix(args["question_id"], args["fix"], n_runs=3, conn=conn)
            result_str = json.dumps(v_res, indent=2)
        elif name == "submit_for_review":
            qid, verdict, fix, ev = args["question_id"], args["verdict"], args["fix"], args["evidence"]
            conf = float(args.get("confidence", 0.90))
            allowed, reason = guardrails.check_submission(qid, verdict, ev, conn=conn)
            if not allowed:
                db.log_event(run_id, step, "GUARDRAIL", {"tool": name, "blocked": reason, "question_id": qid})
                result_str = f"BLOCKED by guardrail: {reason}"
            else:
                conn.execute(
                    "INSERT INTO review_queue (run_id, question_id, verdict, fix_json, evidence_json, confidence, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                    (run_id, qid, verdict, json.dumps(fix), json.dumps(ev), conf),
                )
                memory.record_finding(run_id, qid, verdict, ev, status="submitted", conn=conn)
                conn.commit()
                result_str = f"Success: Question {qid} enqueued for human review (verdict: {verdict})."
        elif name == "record_clearance":
            qid, reason = args["question_id"], args.get("reason", "Cleared as benign decoy.")
            memory.remember_clearance(qid, reason, run_id=run_id, conn=conn)
            result_str = f"Cleared: Question {qid} marked as cleared decoy / false alarm."
        elif name == "recall_memory":
            result_str = json.dumps(memory.recall(question_id=args.get("question_id"), conn=conn), indent=2)
        elif name == "request_more_data":
            qid = args["question_id"]
            db.log_event(run_id, step, "REFUSAL", {"question_id": qid, "reason": "Insufficient attempts (n < 30)"})
            memory.record_finding(run_id, qid, "INSUFFICIENT_DATA", {"reason": "n < 30"}, status="refused", conn=conn)
            result_str = f"Refusal recorded: Question {qid} has insufficient data (n < 30); cannot evaluate."
        elif name == "finish":
            result_str = f"Run finished: {args.get('summary', 'Completed.')}"
        else:
            result_str = f"Unknown tool: {name}"
    except Exception as exc:
        err_msg = f"Tool execution failed ({name}): {exc}"
        db.log_event(run_id, step, "ERROR", {"tool": name, "error": str(exc)})
        result_str = err_msg
    finally:
        if close_conn:
            conn.close()

    if len(result_str) > 1500:
        result_str = result_str[:1450] + "\n... [truncated]"

    db.log_event(run_id, step, "OBSERVE", {"tool": name, "output": result_str})
    return result_str
