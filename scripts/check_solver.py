"""check_solver.py — Verification script for Phase 3.

Solves the 5 planted items + 4 decoys and prints answer vs stored key and defensible options.
Expected findings:
- Wrong-key items (Q005, Q038) should show disagreement (majority_answer != stored key).
- Ambiguous items (Q012, Q042) should show multiple defensible options (any_multi_defensible=True).
- Non-disc item (Q045): solver solves or flags ambiguity.
- Decoys (Q025, Q047, Q030, Q050): solver agrees with stored key with high agreement.
"""

import sys, os
sys.path.insert(0, os.getcwd())

from src import db, solver

ITEMS = [
    ("Q005", "planted_wrong_key"),
    ("Q038", "planted_wrong_key"),
    ("Q012", "planted_ambiguous"),
    ("Q042", "planted_ambiguous"),
    ("Q045", "planted_nondisc"),
    ("Q025", "decoy_hard"),
    ("Q047", "decoy_hard"),
    ("Q030", "decoy_easy"),
    ("Q050", "decoy_easy"),
]

def main():
    print("=" * 80)
    print("SOLVER VERIFICATION CHECK (5 PLANTED + 4 DECOYS)")
    print("=" * 80)
    print(f"{'ID':<6} {'Label':<20} {'Stored':<7} {'Solver':<7} {'Agree':<7} {'MultiDef':<9} {'Defensible Options'}")
    print("-" * 80)

    for qid, label in ITEMS:
        row = db.query_one("SELECT key FROM questions WHERE id=?", (qid,))
        stored_key = row["key"] if row else "?"

        res = solver.solve(qid, n_runs=2, use_code=False)
        maj = res["majority_answer"]
        agree = res["agreement"]
        multi = "YES" if res["any_multi_defensible"] else "no"

        # Unique defensible options across all runs
        all_def = sorted(set(opt for r in res["runs"] for opt in r.get("defensible_options", [])))
        def_str = ", ".join(all_def)

        # Highlight disagreement
        disagree_mark = " (!)" if maj != stored_key else "    "

        print(
            f"{qid:<6} {label:<20} {stored_key:<7} {maj + disagree_mark:<7} "
            f"{agree:<7.2f} {multi:<9} {def_str}"
        )

    print("=" * 80)
    print("Note: '(!)' marks where the solver disagrees with the stored live key.")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
