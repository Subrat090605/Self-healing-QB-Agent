"""guardrails.py — Enforces the two-signal rule, n>=30 refusal, command safety, and budgets.

Implements SPEC §12:
- check_submission(question_id, verdict, evidence, n_attempts=None) -> (bool, str)
- check_command(text) -> (bool, str)
- check_budget(step, solver_calls) -> (bool, str)
- is_tool_allowed(tool_name) -> bool
"""

import re
import sqlite3
from typing import Any, Optional

from src import db
from src.config import DB_PATH, MAX_STEPS, MAX_SOLVER_CALLS

ALLOWED_TOOLS = {
    "bank_summary",
    "compute_item_stats",
    "get_suspects",
    "analyze_distractors",
    "solve_independently",
    "run_python",
    "propose_fix",
    "verify_fix",
    "submit_for_review",
    "record_clearance",
    "recall_memory",
    "request_more_data",
    "finish",
}

UNSAFE_COMMAND_PATTERNS = [
    r"apply\s+all",
    r"delete",
    r"skip\s+review",
    r"bypass\s+review",
    r"bypass\s+guardrails",
    r"auto\s*approve",
    r"no\s+review",
    r"remove\s+bad",
    r"drop\s+table",
    r"execute\s+all",
]


def check_submission(
    question_id: str,
    verdict: str,
    evidence: dict[str, Any],
    n_attempts: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> tuple[bool, str]:
    """Validate submission against strict safety guardrails.

    Enforces:
    1. n >= 30 (refuse on insufficient data).
    2. Two-signal rule (SPEC §9.3, §12.5): Requires at least one statistical signal
       AND at least one solver signal.
    """
    # 1. Check attempt count n >= 30
    if n_attempts is None:
        close_conn = False
        if conn is None:
            conn = db.get_conn(DB_PATH)
            close_conn = True
        try:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM attempts WHERE question_id=?",
                (question_id,),
            ).fetchone()
            n_attempts = row["cnt"] if row else 0
        finally:
            if close_conn:
                conn.close()

    if n_attempts < 30:
        return (
            False,
            f"Refusal: Question {question_id} has only {n_attempts} attempts (n < 30 required). "
            "Insufficient data to judge reliability.",
        )

    # 2. Enforce Two-Signal Rule
    # Extract stats signals from evidence
    stats_data = evidence.get("stats", {})
    if not isinstance(stats_data, dict):
        stats_data = {}

    has_stats_signal = bool(
        evidence.get("stats_signal")
        or stats_data.get("stats_signal")
        or evidence.get("neg_disc")
        or stats_data.get("neg_disc")
        or evidence.get("key_inversion")
        or stats_data.get("key_inversion")
        or evidence.get("split_top")
        or stats_data.get("split_top")
        or (
            (evidence.get("low_disc") or stats_data.get("low_disc"))
            and not (evidence.get("ceiling") or stats_data.get("ceiling"))
            and not (evidence.get("floor") or stats_data.get("floor"))
        )
    )

    # Extract solver signals from evidence
    solver_data = evidence.get("solver", {})
    if not isinstance(solver_data, dict):
        solver_data = {}

    solver_agreement = float(
        solver_data.get("agreement", evidence.get("agreement", 1.0))
    )
    solver_majority = solver_data.get("majority_answer", evidence.get("majority_answer"))
    stored_key = evidence.get("stored_key", stats_data.get("key"))

    solver_disagreed = (
        (solver_majority is not None and stored_key is not None and solver_majority != stored_key)
        or evidence.get("solver_disagreed", False)
        or solver_data.get("disagreed", False)
    )

    solver_multi_defensible = bool(
        evidence.get("any_multi_defensible")
        or solver_data.get("any_multi_defensible")
        or (len(solver_data.get("defensible_options", [])) >= 2)
    )

    solver_low_agreement = solver_agreement < 0.67

    has_solver_signal = bool(
        solver_disagreed or solver_multi_defensible or solver_low_agreement
    )

    # Special case for NON_DISCRIMINATING items:
    # Stats show low discrimination (not ceiling/floor), and solver confirms key is clean and unambiguous
    if verdict == "NON_DISCRIMINATING":
        is_clean_solver = (
            solver_majority == stored_key
            and not solver_multi_defensible
            and solver_agreement >= 0.67
        )
        if has_stats_signal and is_clean_solver:
            has_solver_signal = True

    if not has_stats_signal and not has_solver_signal:
        return (
            False,
            "Refusal: No statistical or solver signals found in evidence.",
        )

    if has_stats_signal and not has_solver_signal:
        return (
            False,
            "Refusal: Two-signal rule violation. Statistical anomaly detected, but solver corroboration is missing. "
            "Item must be routed to WATCHLIST rather than submitted for review.",
        )

    if has_solver_signal and not has_stats_signal:
        return (
            False,
            "Refusal: Two-signal rule violation. Solver found an issue, but statistical indicators are healthy. "
            "Item must be routed to WATCHLIST rather than submitted for review.",
        )

    return True, "Approved: Submission satisfies two-signal rule and n >= 30 threshold."


def check_command(text: str) -> tuple[bool, str]:
    """Check text command against safety policies.

    Refuses commands attempting to bypass review, auto-apply fixes, or delete questions.
    """
    clean_text = text.lower().strip()
    for pattern in UNSAFE_COMMAND_PATTERNS:
        if re.search(pattern, clean_text):
            return (
                False,
                f"Refusal: Command '{text}' violates system safety policies. "
                "Autonomous modification or bulk deletion of live questions without human review is prohibited.",
            )

    return True, "Command accepted."


def check_budget(step: int, solver_calls: int) -> tuple[bool, str]:
    """Check whether step or solver call budgets have been exceeded."""
    if step >= MAX_STEPS:
        return False, f"Budget exceeded: Step count ({step}) reached MAX_STEPS ({MAX_STEPS})."
    if solver_calls >= MAX_SOLVER_CALLS:
        return False, f"Budget exceeded: Solver calls ({solver_calls}) reached MAX_SOLVER_CALLS ({MAX_SOLVER_CALLS})."
    return True, "Within budget."


def is_tool_allowed(tool_name: str) -> bool:
    """Check whether a tool is permitted in the agent loop."""
    return tool_name in ALLOWED_TOOLS
