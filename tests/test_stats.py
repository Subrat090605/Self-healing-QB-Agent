"""test_stats.py — Unit tests for item analysis using hand-made tables.

Tests 3 distinct cases with known, mathematically verifiable outputs:
1. Clean, highly discriminating item (D > 0, r_pb > 0, stats_signal=False).
2. Planted wrong-key item (key inversion, D < 0, stats_signal=True).
3. Planted ambiguous item (split top >= 0.25 on multiple options, stats_signal=True).
Plus low-N refusal test (n < 30 -> insufficient=True).
"""

import json
import sqlite3
import pytest
import pandas as pd

from src.stats import compute_item_stats, get_suspects, analyze_distractors

DDL = """
CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    version INT,
    stem TEXT,
    options_json TEXT,
    key TEXT,
    category TEXT,
    status TEXT DEFAULT 'live'
);

CREATE TABLE attempts (
    student_id INT,
    question_id TEXT,
    chosen TEXT,
    correct INT,
    ts INT
);
"""


@pytest.fixture
def mock_db():
    """Create an in-memory database with hand-crafted attempt data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return conn


def test_hand_crafted_tables(mock_db):
    conn = mock_db

    # Insert 4 test questions
    questions = [
        ("Q_CLEAN", "A", "quant"),      # Hand-made clean item
        ("Q_WRONG_KEY", "D", "quant"),  # Hand-made wrong-key item (true answer is B)
        ("Q_AMBIGUOUS", "A", "logical"),# Hand-made ambiguous item (A and B both valid)
        ("Q_LOWN", "C", "verbal"),      # Hand-made low-N item (only 10 attempts)
    ]

    for qid, key, cat in questions:
        conn.execute(
            "INSERT INTO questions (id, version, stem, options_json, key, category, status) VALUES (?, 1, 'stem', '{}', ?, ?, 'live')",
            (qid, key, cat),
        )

    # 40 students total so n >= 30 for Q_CLEAN, Q_WRONG_KEY, Q_AMBIGUOUS
    # Students 0-19: lower ability (weaker overall)
    # Students 20-39: upper ability (stronger overall)
    attempts = []

    # Insert 5 anchor questions where students 20-39 get all 5 right (score 5)
    # and students 0-19 get all 5 wrong (score 0)
    for a_idx in range(5):
        a_id = f"Q_ANCHOR_{a_idx}"
        conn.execute(
            "INSERT INTO questions (id, version, stem, options_json, key, category, status) VALUES (?, 1, 'stem', '{}', 'A', 'quant', 'live')",
            (a_id,),
        )
        for sid in range(40):
            c_anchor = "A" if sid >= 20 else "B"
            attempts.append((sid, a_id, c_anchor, 1 if sid >= 20 else 0, sid))

    for sid in range(40):
        # 1. Q_CLEAN (key A):
        # High ability (>= 20) choose A (correct)
        # Low ability (< 20) choose B (incorrect)
        ch_clean = "A" if sid >= 20 else "B"
        attempts.append((sid, "Q_CLEAN", ch_clean, 1 if ch_clean == "A" else 0, sid))

        # 2. Q_WRONG_KEY (stored key D, true correct B):
        # High ability (>= 20) choose B (true correct, but marked 0 against key D)
        # Low ability (< 20) guess D (stored key)
        ch_wk = "B" if sid >= 20 else "D"
        attempts.append((sid, "Q_WRONG_KEY", ch_wk, 1 if ch_wk == "D" else 0, sid))

        # 3. Q_AMBIGUOUS (key A, but B also valid):
        # High ability (>= 20) split between A and B
        # Low ability (< 20) choose C
        if sid >= 20:
            ch_amb = "A" if sid % 2 != 0 else "B"
        else:
            ch_amb = "C"
        attempts.append((sid, "Q_AMBIGUOUS", ch_amb, 1 if ch_amb == "A" else 0, sid))

    # 4. Q_LOWN: only 10 students attempt it
    for sid in range(10):
        attempts.append((sid, "Q_LOWN", "C", 1, sid))

    conn.executemany(
        "INSERT INTO attempts (student_id, question_id, chosen, correct, ts) VALUES (?, ?, ?, ?, ?)",
        attempts,
    )
    conn.commit()

    # Run item stats
    df = compute_item_stats(conn=conn)
    assert not df.empty
    assert len(df) == 9  # 4 questions + 5 anchor questions

    # Table 1: Verify Q_CLEAN
    clean_row = df[df["question_id"] == "Q_CLEAN"].iloc[0]
    assert clean_row["n"] == 40
    assert clean_row["p"] == 0.50
    assert clean_row["D"] > 0.80  # Upper group 100%, lower group 0%
    assert clean_row["r_pb"] > 0.80
    assert bool(clean_row["neg_disc"]) is False
    assert bool(clean_row["low_disc"]) is False
    assert bool(clean_row["stats_signal"]) is False

    # Table 2: Verify Q_WRONG_KEY (Key Inversion)
    wk_row = df[df["question_id"] == "Q_WRONG_KEY"].iloc[0]
    assert wk_row["n"] == 40
    assert wk_row["D"] < -0.80     # Upper group 0% on key D, lower group 100% on key D
    assert wk_row["r_pb"] < -0.80
    assert bool(wk_row["neg_disc"]) is True
    assert bool(wk_row["key_inversion"]) is True
    assert bool(wk_row["stats_signal"]) is True
    assert wk_row["share_upper"]["B"] > wk_row["share_upper"]["D"]

    # Table 3: Verify Q_AMBIGUOUS (Split Top)
    amb_row = df[df["question_id"] == "Q_AMBIGUOUS"].iloc[0]
    assert amb_row["n"] == 40
    assert amb_row["share_upper"]["A"] >= 0.25
    assert amb_row["share_upper"]["B"] >= 0.25
    assert bool(amb_row["split_top"]) is True
    assert bool(amb_row["stats_signal"]) is True

    # Table 4: Verify Q_LOWN (Insufficient Data)
    lown_row = df[df["question_id"] == "Q_LOWN"].iloc[0]
    assert lown_row["n"] == 10
    assert bool(lown_row["insufficient"]) is True

    # Test get_suspects ranking
    suspects = get_suspects(df, rule="agent")
    # Q_WRONG_KEY has the most negative D, should rank first
    assert suspects[0] == "Q_WRONG_KEY"
    assert "Q_AMBIGUOUS" in suspects
    assert "Q_LOWN" in suspects
    assert "Q_CLEAN" not in suspects

    # Test analyze_distractors
    res_wk = analyze_distractors("Q_WRONG_KEY", conn=conn, stats_df=df)
    assert "Key inversion" in res_wk["anomaly"]

    res_amb = analyze_distractors("Q_AMBIGUOUS", conn=conn, stats_df=df)
    assert "Split top" in res_amb["anomaly"]

    res_lown = analyze_distractors("Q_LOWN", conn=conn, stats_df=df)
    assert "Insufficient data" in res_lown["anomaly"]
