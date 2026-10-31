"""test_firewall.py — Ensures agent code never imports or reads ground_truth.json.

See CLAUDE.md firewall rule:
Ground-truth firewall: data/ground_truth.json may ONLY be read by src/seed/*
and src/evaluate.py and the Scoreboard tab in app.py. Agent code
(agent.py, tools.py, solver.py, fixer.py, stats.py, memory.py, guardrails.py)
must NEVER read or import it.
"""

from pathlib import Path
import pytest

# Modules forbidden from touching ground_truth
FORBIDDEN_FILES = [
    "agent.py",
    "tools.py",
    "solver.py",
    "fixer.py",
    "stats.py",
    "memory.py",
    "guardrails.py",
    "review.py",
    "sandbox.py",
]


def test_ground_truth_firewall():
    src_dir = Path(__file__).parent.parent / "src"

    violations = []
    for fname in FORBIDDEN_FILES:
        fpath = src_dir / fname
        if not fpath.exists():
            continue
        content = fpath.read_text(encoding="utf-8")
        if "ground_truth" in content.lower():
            violations.append(fname)

    assert not violations, f"Firewall violation! Ground truth referenced in: {violations}"
