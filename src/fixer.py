"""fixer.py — Fix proposal generation and self-verification on patched copies.

Implements SPEC §10:
- propose_fix(question_id, verdict, evidence, model) -> dict
- verify_fix(question_id, fix, n_runs=3) -> dict
"""

import json
import sqlite3
from typing import Any, Optional

from src import db, llm, solver
from src.config import DB_PATH, SOLVER_MODEL

PROPOSE_FIX_SYSTEM = (
    "You are an expert curriculum developer and psychometrician.\n"
    "Your job is to propose a high-quality fix for a defective exam question.\n"
    "Respond with valid JSON only in the following schema:\n"
    "{\n"
    '  "fix_type": "change_key" | "rewrite" | "retire_replace",\n'
    '  "new_key": "A" | "B" | "C" | "D",\n'
    '  "new_stem": "revised question stem or null",\n'
    '  "new_options": {"A": "...", "B": "...", "C": "...", "D": "..."} or null,\n'
    '  "rationale": "Short justification <=60 words",\n'
    '  "replacement_question": null or {"stem": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."}, "key": "..."}\n'
    "}\n"
    "Rules:\n"
    "- WRONG_KEY: use fix_type='change_key' with new_key set to the mathematically/logically correct answer.\n"
    "- AMBIGUOUS: use fix_type='rewrite', clarifying the stem or options so exactly ONE option is correct.\n"
    "- NON_DISCRIMINATING: use fix_type='retire_replace' with a well-posed replacement question testing the same category."
)


def propose_fix(
    question_id: str,
    verdict: str,
    evidence: dict[str, Any],
    model: str = SOLVER_MODEL,
    conn: Optional[sqlite3.Connection] = None,
) -> dict[str, Any]:
    """Generate a fix proposal JSON for a flagged question (SPEC §10)."""
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        row = conn.execute(
            "SELECT stem, options_json, key, category FROM questions WHERE id=? AND status='live'",
            (question_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Question {question_id} not found in database.")

        stem = row["stem"]
        options = json.loads(row["options_json"])
        current_key = row["key"]
        category = row["category"]

        # Fast path for WRONG_KEY if solver provided a clear majority answer
        solver_ans = evidence.get("solver", {}).get("majority_answer") or evidence.get("majority_answer")
        if verdict == "WRONG_KEY" and solver_ans and solver_ans in options:
            return {
                "fix_type": "change_key",
                "new_key": solver_ans,
                "new_stem": None,
                "new_options": None,
                "rationale": f"Update answer key from {current_key} to {solver_ans} based on verified calculation.",
                "replacement_question": None,
            }

        # Otherwise prompt model to draft a fix
        opts_str = "\n".join(f"{k}: {options[k]}" for k in sorted(options.keys()))
        ev_summary = json.dumps({
            "verdict": verdict,
            "current_key": current_key,
            "category": category,
            "evidence": evidence,
        }, indent=2)

        user_prompt = (
            f"Question ID: {question_id}\n"
            f"Category: {category}\n"
            f"Current Key: {current_key}\n"
            f"Stem: {stem}\n"
            f"Options:\n{opts_str}\n\n"
            f"Investigation Evidence:\n{ev_summary}\n\n"
            "Propose the fix JSON:"
        )

        resp = llm.json_chat(model=model, system=PROPOSE_FIX_SYSTEM, user=user_prompt, temperature=0.2)

        # Ensure required keys exist
        fix_type = resp.get("fix_type", "rewrite")
        new_key = resp.get("new_key", current_key)
        new_stem = resp.get("new_stem")
        new_options = resp.get("new_options")
        rationale = resp.get("rationale", f"Remediate {verdict} defect.")
        replacement_question = resp.get("replacement_question")

        return {
            "fix_type": fix_type,
            "new_key": new_key,
            "new_stem": new_stem,
            "new_options": new_options,
            "rationale": rationale,
            "replacement_question": replacement_question,
        }

    finally:
        if close_conn:
            conn.close()


def verify_fix(
    question_id: str,
    fix: dict[str, Any],
    n_runs: int = 3,
    conn: Optional[sqlite3.Connection] = None,
    model: str = SOLVER_MODEL,
) -> dict[str, Any]:
    """Test the fix by solving a patched in-memory copy of the question 3 times (SPEC §10).

    Passes iff:
    - All n_runs answer new_key (agreement == 1.0).
    - defensible_options == [new_key] (no residual ambiguity).
    """
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        row = conn.execute(
            "SELECT stem, options_json, key FROM questions WHERE id=? AND status='live'",
            (question_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Question {question_id} not found in database.")

        orig_stem = row["stem"]
        orig_options = json.loads(row["options_json"])

        # Create patched in-memory copy (NEVER mutates live DB)
        fix_type = fix.get("fix_type", "change_key")
        target_key = fix.get("new_key", "A")

        if fix_type == "retire_replace" and fix.get("replacement_question"):
            rep = fix["replacement_question"]
            patched_stem = rep.get("stem", orig_stem)
            patched_options = rep.get("options", orig_options)
            target_key = rep.get("key", target_key)
        else:
            patched_stem = fix.get("new_stem") or orig_stem
            patched_options = fix.get("new_options") or orig_options

        # Solve patched question
        patched_data = {"stem": patched_stem, "options": patched_options}
        solver_res = solver.solve(
            question_data=patched_data,
            n_runs=n_runs,
            use_code=False,
            model=model,
        )

        all_runs = solver_res.get("runs", [])
        total_runs = len(all_runs)

        # Check conditions:
        # 1. All runs answer target_key
        runs_agree = sum(1 for r in all_runs if r.get("answer") == target_key)
        agrees_on_key = (runs_agree == total_runs)

        # 2. Defensible options contains only target_key across runs
        has_ambiguity = any(
            any(opt != target_key for opt in r.get("defensible_options", []))
            for r in all_runs
        )

        passed = agrees_on_key and not has_ambiguity
        badge = f"Self-verification: {runs_agree}/{total_runs} \u2713" if passed else f"Self-verification: {runs_agree}/{total_runs} \u2717"

        return {
            "passed": passed,
            "badge": badge,
            "target_key": target_key,
            "solver_majority": solver_res.get("majority_answer"),
            "runs_agreed": runs_agree,
            "total_runs": total_runs,
            "has_ambiguity": has_ambiguity,
        }

    finally:
        if close_conn:
            conn.close()
