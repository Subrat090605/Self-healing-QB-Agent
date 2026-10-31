"""seed/simulate.py — IRT-based student simulation; writes attempt rows.

Implements SPEC §5.4:
- 500 students, ability θ ~ N(0,1).
- Each student attempts a random 65–85% of questions (except lowN_valid: 12 students).
- 2PL with guessing: P(know) = c + (1-c) * sigmoid(a * (θ - b)).
- Distractors weighted by attractiveness; tempting distractor favored by low θ.
- Planted defect behaviors (wrong key, ambiguous split, non-discriminating).
"""

from typing import Any
import numpy as np


def _sigmoid(x: float) -> float:
    """Standard logistic sigmoid function."""
    if x >= 0:
        z = np.exp(-x)
        return float(1.0 / (1.0 + z))
    else:
        z = np.exp(x)
        return float(z / (1.0 + z))


def simulate_student_attempts(
    questions: list[dict[str, Any]],
    seed: int = 0,
    n_students: int = 500,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    """Simulate attempts for n_students across all questions.

    Args:
        questions: List of question dictionaries from bank.
        seed: Random seed for reproducibility.
        n_students: Number of simulated students (default 500).

    Returns:
        attempts: List of attempt dicts (student_id, question_id, chosen, correct, ts).
        thetas: Array of student ability parameters θ ~ N(0, 1).
    """
    rng = np.random.default_rng(seed)
    thetas = rng.normal(0.0, 1.0, size=n_students)

    # Separate lowN item from standard items
    low_n_items = [q for q in questions if q.get("label") == "lowN_valid"]
    standard_items = [q for q in questions if q.get("label") != "lowN_valid"]

    # Exactly 12 students attempt each lowN item
    low_n_students: dict[str, set[int]] = {}
    for q in low_n_items:
        chosen_students = set(rng.choice(n_students, size=12, replace=False).tolist())
        low_n_students[q["id"]] = chosen_students

    attempts: list[dict[str, Any]] = []
    ts_counter = 1700000000

    all_options = ["A", "B", "C", "D"]

    for s_id in range(n_students):
        theta = float(thetas[s_id])

        # Student attempts a random 65-85% of standard questions
        frac = rng.uniform(0.65, 0.85)
        n_att = int(round(frac * len(standard_items)))
        attempted_standards = rng.choice(standard_items, size=n_att, replace=False).tolist()

        # Check if student also attempts lowN items
        student_questions = list(attempted_standards)
        for q in low_n_items:
            if s_id in low_n_students[q["id"]]:
                student_questions.append(q)

        # Shuffle presentation order for this student
        rng.shuffle(student_questions)

        for q in student_questions:
            q_id = q["id"]
            stored_key = q["key"]
            true_correct = q["true_correct"]
            label = q.get("label", "clean")

            a = float(q.get("irt_a", 1.2))
            b = float(q.get("irt_b", 0.0))
            c = float(q.get("irt_c", 0.2))

            p_know = c + (1.0 - c) * _sigmoid(a * (theta - b))

            chosen: str

            if label == "planted_nondisc":
                # P5: P(correct) = 0.40 regardless of ability; rest uniform
                if rng.random() < 0.40:
                    chosen = stored_key
                else:
                    others = [opt for opt in all_options if opt != stored_key]
                    chosen = str(rng.choice(others))

            elif label == "planted_ambiguous":
                # P3, P4: If student knows, split 55/45 across the two valid options
                opt1 = true_correct
                opt2 = q.get("alternate_valid") or true_correct
                if rng.random() < p_know:
                    chosen = opt1 if rng.random() < 0.55 else opt2
                else:
                    chosen = str(rng.choice(all_options))

            elif label == "planted_wrong_key":
                # P1, P2: Strong students know true_correct; weak guess distractors
                if rng.random() < p_know:
                    chosen = true_correct  # true_correct != stored_key
                else:
                    distractors = [opt for opt in all_options if opt != true_correct]
                    tempting = q.get("tempting_distractor", stored_key)
                    weights = []
                    for d in distractors:
                        if d == tempting:
                            weights.append(2.0 + max(0.0, -1.0 * theta))
                        else:
                            weights.append(1.0)
                    total_w = sum(weights)
                    probs = [w / total_w for w in weights]
                    chosen = str(rng.choice(distractors, p=probs))

            else:
                # clean, decoy_hard, decoy_easy, lowN_valid
                if rng.random() < p_know:
                    chosen = true_correct  # true_correct == stored_key
                else:
                    distractors = [opt for opt in all_options if opt != true_correct]
                    tempting = q.get("tempting_distractor", distractors[0])
                    weights = []
                    for d in distractors:
                        if d == tempting:
                            weights.append(2.0 + max(0.0, -1.0 * theta))
                        else:
                            weights.append(1.0)
                    total_w = sum(weights)
                    probs = [w / total_w for w in weights]
                    chosen = str(rng.choice(distractors, p=probs))

            # Correctness is computed vs stored LIVE key at seed time (SPEC §4, §5.4)
            correct = 1 if chosen == stored_key else 0
            ts_counter += 1

            attempts.append({
                "student_id": s_id,
                "question_id": q_id,
                "chosen": chosen,
                "correct": correct,
                "ts": ts_counter,
            })

    return attempts, thetas
