"""test_guardrails.py — Unit tests for safety guardrails and two-signal rule.

Proves:
(a) Single-signal submission is rejected (enforcing two-signal rule).
(b) n < 30 is refused (insufficient data).
(c) Unsafe commands like 'apply all fixes' or 'delete bad questions' are refused.
(d) Forbidden tools attempting live database mutation are blocked.
See SPEC §12 and PROMPTS.md Phase 4.
"""

import pytest
from src import guardrails


def test_single_signal_submission_is_rejected():
    """Prove that a submission with only one signal is rejected under the two-signal rule."""

    # Case 1: Only statistical signal, no solver corroboration
    evidence_stats_only = {
        "stats": {
            "key": "A",
            "stats_signal": True,
            "neg_disc": True,
            "D": -0.25,
            "r_pb": -0.20,
        },
        "solver": {
            "majority_answer": "A",  # Solver agrees with key!
            "agreement": 1.0,
            "defensible_options": ["A"],
            "any_multi_defensible": False,
        },
    }

    allowed, reason = guardrails.check_submission(
        question_id="Q_TEST_01",
        verdict="WRONG_KEY",
        evidence=evidence_stats_only,
        n_attempts=100,
    )
    assert allowed is False
    assert "Two-signal rule violation" in reason

    # Case 2: Only solver signal, healthy statistics
    evidence_solver_only = {
        "stats": {
            "key": "A",
            "stats_signal": False,
            "neg_disc": False,
            "low_disc": False,
            "D": 0.40,
            "r_pb": 0.35,
        },
        "solver": {
            "majority_answer": "B",  # Solver disagrees, but stats are healthy!
            "agreement": 1.0,
            "defensible_options": ["B"],
            "any_multi_defensible": False,
        },
    }

    allowed, reason = guardrails.check_submission(
        question_id="Q_TEST_02",
        verdict="WRONG_KEY",
        evidence=evidence_solver_only,
        n_attempts=100,
    )
    assert allowed is False
    assert "Two-signal rule violation" in reason

    # Case 3: Both statistical AND solver signals present -> APPROVED
    evidence_both_signals = {
        "stats": {
            "key": "D",
            "stats_signal": True,
            "neg_disc": True,
            "key_inversion": True,
            "D": -0.30,
            "r_pb": -0.28,
        },
        "solver": {
            "majority_answer": "B",  # Disagrees with stored key D
            "agreement": 1.0,
            "defensible_options": ["B"],
            "any_multi_defensible": False,
        },
    }

    allowed, reason = guardrails.check_submission(
        question_id="Q_TEST_03",
        verdict="WRONG_KEY",
        evidence=evidence_both_signals,
        n_attempts=100,
    )
    assert allowed is True
    assert "Approved" in reason


def test_insufficient_attempts_refused():
    """Prove that n < 30 is refused due to insufficient data."""
    evidence_valid = {
        "stats": {"key": "D", "neg_disc": True, "stats_signal": True},
        "solver": {"majority_answer": "B", "agreement": 1.0},
    }

    # Low-N question (only 12 attempts)
    allowed, reason = guardrails.check_submission(
        question_id="Q_LOWN",
        verdict="WRONG_KEY",
        evidence=evidence_valid,
        n_attempts=12,
    )
    assert allowed is False
    assert "n < 30 required" in reason

    # Sufficient attempts (35 attempts)
    allowed, reason = guardrails.check_submission(
        question_id="Q_OKN",
        verdict="WRONG_KEY",
        evidence=evidence_valid,
        n_attempts=35,
    )
    assert allowed is True


def test_unsafe_commands_refused():
    """Prove that commands seeking to bypass review or mutate live questions are refused."""
    unsafe_commands = [
        "apply all fixes immediately",
        "delete the bad questions",
        "skip review and push to live bank",
        "bypass guardrails and commit",
        "auto approve pending questions",
        "drop table questions",
    ]

    for cmd in unsafe_commands:
        allowed, reason = guardrails.check_command(cmd)
        assert allowed is False, f"Command '{cmd}' should have been refused."
        assert "violates system safety policies" in reason

    # Safe command passes
    allowed, reason = guardrails.check_command("Show me the current bank summary and suspect count")
    assert allowed is True


def test_tool_allowlist():
    """Prove that unallowed tools (especially those modifying live questions) are blocked."""
    assert guardrails.is_tool_allowed("bank_summary") is True
    assert guardrails.is_tool_allowed("submit_for_review") is True
    assert guardrails.is_tool_allowed("verify_fix") is True

    # Mutating live questions directly is forbidden
    assert guardrails.is_tool_allowed("delete_question") is False
    assert guardrails.is_tool_allowed("update_live_bank") is False
    assert guardrails.is_tool_allowed("drop_database") is False
