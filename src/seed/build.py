"""seed/build.py — Entry point: build qbank.db + hidden ground_truth.json.

Usage: python -m src.seed.build --seed 0
See SPEC §5.
"""

import argparse
import json
from collections import Counter
from typing import Any, Optional

import numpy as np

from src.config import DB_PATH, GROUND_TRUTH_PATH
from src import db
from src.seed.bank import get_all_questions
from src.seed.simulate import simulate_student_attempts


def compute_quick_stats(attempts: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Compute n, p, and discrimination index D using upper/lower 27% by rest_pct.

    Follows SPEC §6 definition:
    - rest_pct = (total_correct - this_item_correct) / (attempted - 1)
    - D = p(upper 27%) - p(lower 27%)
    """
    # 1. Total correct and attempts per student
    student_total: dict[int, int] = {}
    student_n_att: dict[int, int] = {}
    for att in attempts:
        s_id = att["student_id"]
        c = att["correct"]
        student_total[s_id] = student_total.get(s_id, 0) + c
        student_n_att[s_id] = student_n_att.get(s_id, 0) + 1

    # 2. Group attempts by question
    q_attempts: dict[str, list[tuple[float, int]]] = {}
    for att in attempts:
        s_id = att["student_id"]
        q_id = att["question_id"]
        c = att["correct"]

        tot = student_total[s_id]
        n_att = student_n_att[s_id]
        rest_pct = (tot - c) / (n_att - 1) if n_att > 1 else 0.0

        if q_id not in q_attempts:
            q_attempts[q_id] = []
        q_attempts[q_id].append((rest_pct, c))

    # 3. Compute p and D for each question
    stats: dict[str, dict[str, float]] = {}
    for q_id, pairs in q_attempts.items():
        n = len(pairs)
        if n == 0:
            stats[q_id] = {"n": 0, "p": 0.0, "D": 0.0}
            continue

        p = sum(c for _, c in pairs) / n

        # Sort by rest_pct to get upper and lower 27%
        pairs.sort(key=lambda x: x[0])
        k = max(1, int(round(0.27 * n)))
        lower_group = pairs[:k]
        upper_group = pairs[-k:]

        p_lower = sum(c for _, c in lower_group) / k
        p_upper = sum(c for _, c in upper_group) / k
        D = p_upper - p_lower

        stats[q_id] = {"n": float(n), "p": round(p, 4), "D": round(D, 4)}

    return stats


def build(
    seed: int = 0,
    db_path: Optional[Any] = None,
    write_gt: bool = True,
    quiet: bool = False,
) -> None:
    """Build the database and ground truth files for the given seed."""
    target_db = db_path if db_path is not None else DB_PATH
    if not quiet:
        print(f"Building question bank and simulating attempts with seed={seed} (db={target_db})...")

    # 1. Initialize SQLite schema
    db.init(target_db)

    # 2. Load questions
    questions = get_all_questions()

    # 3. Clear existing questions and attempts
    conn = db.get_conn(target_db)
    with conn:
        conn.execute("DELETE FROM questions")
        conn.execute("DELETE FROM attempts")
        conn.execute("DELETE FROM trace_events")
        conn.execute("DELETE FROM solver_runs")
        conn.execute("DELETE FROM findings")
        conn.execute("DELETE FROM review_queue")
        conn.execute("DELETE FROM agent_memory")
        conn.execute("DELETE FROM audit_log")

        # 4. Insert questions
        for q in questions:
            conn.execute(
                """
                INSERT INTO questions (id, version, stem, options_json, key, category, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    q["id"],
                    1,
                    q["stem"],
                    json.dumps(q["options"]),
                    q["key"],
                    q["category"],
                    "live",
                ),
            )

    # 5. Simulate student attempts
    attempts, thetas = simulate_student_attempts(questions, seed=seed)

    # 6. Insert attempts
    with conn:
        conn.executemany(
            """
            INSERT INTO attempts (student_id, question_id, chosen, correct, ts)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (a["student_id"], a["question_id"], a["chosen"], a["correct"], a["ts"])
                for a in attempts
            ],
        )

    # 7. Write hidden ground_truth.json
    ground_truth: dict[str, Any] = {}
    for q in questions:
        ground_truth[q["id"]] = {
            "id": q["id"],
            "true_correct": q["true_correct"],
            "label": q["label"],
            "alternate_valid": q.get("alternate_valid"),
            "category": q["category"],
            "irt": {
                "a": q.get("irt_a", 1.2),
                "b": q.get("irt_b", 0.0),
                "c": q.get("irt_c", 0.2),
            },
        }

    if write_gt:
        with open(GROUND_TRUTH_PATH, "w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)

    if not quiet:
        # 8. Compute quick stats and display check output
        quick_stats = compute_quick_stats(attempts)
        label_counts = Counter(q["label"] for q in questions)

        print("\n" + "=" * 60)
        print("SEED BUILD SUMMARY")
        print("=" * 60)
        print(f"Total Questions: {len(questions)}")
        print(f"Total Attempts : {len(attempts)}")
        print("\nLabels Breakdown:")
        for lbl, count in sorted(label_counts.items()):
            print(f"  - {lbl:<22}: {count}")

        print("\n" + "-" * 72)
        print(f"{'ID':<6} {'Label':<22} {'Stored':<7} {'True':<6} {'N':<6} {'p':<8} {'D':<8}")
        print("-" * 72)

        # Print planted items
        planted_labels = {"planted_wrong_key", "planted_ambiguous", "planted_nondisc"}
        planted_items = [q for q in questions if q["label"] in planted_labels]
        for q in planted_items:
            qid = q["id"]
            st = quick_stats.get(qid, {"n": 0, "p": 0.0, "D": 0.0})
            print(
                f"{qid:<6} {q['label']:<22} {q['key']:<7} {q['true_correct']:<6} "
                f"{int(st['n']):<6} {st['p']:<8.3f} {st['D']:<8.3f}"
            )

        print("\nDecoys & Low-N Items:")
        print("-" * 72)
        decoy_items = [q for q in questions if q["label"] in {"decoy_hard", "decoy_easy", "lowN_valid"}]
        for q in decoy_items:
            qid = q["id"]
            st = quick_stats.get(qid, {"n": 0, "p": 0.0, "D": 0.0})
            print(
                f"{qid:<6} {q['label']:<22} {q['key']:<7} {q['true_correct']:<6} "
                f"{int(st['n']):<6} {st['p']:<8.3f} {st['D']:<8.3f}"
            )

        print("=" * 72 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build qbank.db and ground_truth.json")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for simulation (default: 0)")
    args = parser.parse_args()
    build(seed=args.seed)


if __name__ == "__main__":
    main()
