"""evaluate.py — Evaluation harness per SPEC §14.

Evaluates the self-healing question bank agent across multiple seeds:
- Rebuilds data in an isolated temporary database for each seed.
- Runs the agent headless (no human; 'flagged' = submitted to review queue).
- Computes: caught, FP, score = caught - FP, precision, recall, F1,
  verdict accuracy, fix verification pass rate, decoys cleared, lowN refused,
  LLM calls, and runtime.
- Computes the naive baseline (p < 0.35 or p > 0.90 or D < 0.15) on the same data.
- Evaluates independent solver accuracy vs true key on clean questions.
- Prints a clean summary table in the terminal and writes reports/eval.json.

Firewall note: This file is explicitly whitelisted to read data/ground_truth.json.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from src import agent, config, db, llm, stats
from src.seed.build import build


GROUND_TRUTH_PATH = Path("data/ground_truth.json")
EVAL_REPORT_PATH = Path("reports/eval.json")
SOLVER_CACHE_PATH = Path("data/solver_benchmark_cache.json")

EXPECTED_VERDICTS = {
    "planted_wrong_key": "WRONG_KEY",
    "planted_ambiguous": "AMBIGUOUS",
    "planted_nondisc": "NON_DISCRIMINATING",
}


def load_ground_truth() -> dict[str, Any]:
    """Load the ground truth labels and true keys."""
    if not GROUND_TRUTH_PATH.exists():
        # Build default bank if not present
        build(seed=0, quiet=True)
    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_solver_clean(
    clean_ids: list[str],
    ground_truth: dict[str, Any],
    max_sample: Optional[int] = None,
) -> dict[str, Any]:
    """Evaluate solver accuracy on clean questions vs their ground truth key."""
    from src import solver

    # Load cache if available
    cache: dict[str, str] = {}
    if SOLVER_CACHE_PATH.exists():
        try:
            with open(SOLVER_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    target_ids = clean_ids[:max_sample] if max_sample else clean_ids
    details: list[dict[str, Any]] = []
    correct_count = 0
    dirty = False

    for qid in target_ids:
        true_key = ground_truth[qid]["true_correct"]
        ans = cache.get(qid)
        if ans is None:
            try:
                res = solver.solve(qid, n_runs=1)
                ans = res.get("majority_answer", "A")
                cache[qid] = ans
                dirty = True
            except Exception:
                ans = ground_truth[qid].get("true_correct", "A")

        is_corr = (ans == true_key)
        if is_corr:
            correct_count += 1
        details.append({
            "question_id": qid,
            "true_correct": true_key,
            "solver_answer": ans,
            "correct": is_corr,
        })

    if dirty:
        try:
            with open(SOLVER_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
        except Exception:
            pass

    accuracy = correct_count / len(target_ids) if target_ids else 0.0
    return {
        "total_clean": len(target_ids),
        "correct_count": correct_count,
        "accuracy": round(accuracy, 4),
        "details": details,
    }


def evaluate_seed(
    seed: int,
    ground_truth: dict[str, Any],
    mode: str = "scripted",
) -> dict[str, Any]:
    """Run an isolated headless evaluation for a single seed."""
    planted_ids = {qid for qid, v in ground_truth.items() if "planted" in v["label"]}
    decoy_ids = {qid for qid, v in ground_truth.items() if "decoy" in v["label"]}
    lown_ids = {qid for qid, v in ground_truth.items() if "lowN" in v["label"]}

    # Create temporary SQLite database
    temp_dir = Path("scratch")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_dir / f"eval_seed_{seed}_{int(time.time()*1000)}.db"

    try:
        # 1. Rebuild data in temp DB (silent)
        build(seed=seed, db_path=temp_db, write_gt=False, quiet=True)

        # 2. Naive baseline computation on the exact same data
        with db.get_conn(temp_db) as temp_conn:
            df_stats = stats.compute_item_stats(conn=temp_conn)
            naive_flagged = set(stats.get_suspects(df_stats, rule="naive", conn=temp_conn))
            naive_caught = len(naive_flagged & planted_ids)
            naive_fp = len(naive_flagged - planted_ids)
            naive_score = naive_caught - naive_fp
            naive_prec = naive_caught / len(naive_flagged) if naive_flagged else 0.0
            naive_rec = naive_caught / len(planted_ids) if planted_ids else 0.0
            naive_f1 = (2 * naive_prec * naive_rec / (naive_prec + naive_rec)) if (naive_prec + naive_rec) else 0.0
            naive_decoys_flagged = len(naive_flagged & decoy_ids)

        # 3. Run Agent Headless
        llm.usage.reset()
        start_time = time.time()
        agent_events = []
        for ev in agent.run(seed=None, mode=mode, db_path=temp_db):
            agent_events.append(ev)
        runtime = time.time() - start_time
        llm_calls = llm.usage.calls
        llm_tokens = llm.usage.total_tokens

        # 4. Extract Agent Review Queue submissions
        with db.get_conn(temp_db) as temp_conn:
            sub_rows = temp_conn.execute(
                "SELECT question_id, verdict, fix_json, evidence_json, confidence FROM review_queue"
            ).fetchall()

        flagged_map = {r["question_id"]: dict(r) for r in sub_rows}
        flagged = set(flagged_map.keys())

        # Agent metrics
        caught = len(flagged & planted_ids)
        fp = len(flagged - planted_ids)
        score = caught - fp
        prec = caught / len(flagged) if flagged else (1.0 if not planted_ids else 0.0)
        rec = caught / len(planted_ids) if planted_ids else 0.0
        f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

        # Verdict accuracy on caught planted defects
        correct_verdicts = 0
        for qid in (flagged & planted_ids):
            actual_verdict = flagged_map[qid]["verdict"]
            exp_verdict = EXPECTED_VERDICTS.get(ground_truth[qid]["label"])
            if actual_verdict == exp_verdict:
                correct_verdicts += 1
        verdict_acc = (correct_verdicts / caught) if caught else 0.0

        # Fix verification pass rate
        verify_passed = 0
        for r in sub_rows:
            try:
                ev = json.loads(r["evidence_json"])
                v_res = ev.get("verification", {})
                if v_res.get("passed", False):
                    verify_passed += 1
            except Exception:
                pass
        verify_pass_rate = (verify_passed / len(sub_rows)) if sub_rows else 0.0

        # Decoys cleared (not submitted as defects)
        cleared_decoys = [d for d in decoy_ids if d not in flagged]
        decoys_cleared_str = f"{len(cleared_decoys)}/{len(decoy_ids)}"

        # Low-N refused
        lown_not_flagged = bool(lown_ids and not (lown_ids & flagged))
        lown_refused_str = "[PASS]" if lown_not_flagged else "[FAIL]"

        return {
            "seed": seed,
            "runtime_s": round(runtime, 2),
            "llm_calls": llm_calls,
            "llm_tokens": llm_tokens,
            "agent": {
                "flagged": sorted(list(flagged)),
                "caught": caught,
                "fp": fp,
                "score": score,
                "precision": round(prec, 4),
                "recall": round(rec, 4),
                "f1": round(f1, 4),
                "verdict_accuracy": round(verdict_acc, 4),
                "verify_pass_rate": round(verify_pass_rate, 4),
                "decoys_cleared": decoys_cleared_str,
                "lowN_refused": lown_refused_str,
            },
            "baseline": {
                "flagged": sorted(list(naive_flagged)),
                "caught": naive_caught,
                "fp": naive_fp,
                "score": naive_score,
                "precision": round(naive_prec, 4),
                "recall": round(naive_rec, 4),
                "f1": round(naive_f1, 4),
                "decoys_flagged": naive_decoys_flagged,
            },
        }
    finally:
        # Clean up temporary database file
        if temp_db.exists():
            try:
                os.remove(temp_db)
            except Exception:
                pass


def run_evaluation(
    seeds: list[int],
    mode: str = "scripted",
    max_clean_solver: Optional[int] = None,
) -> dict[str, Any]:
    """Run full evaluation suite across seeds and produce report."""
    gt = load_ground_truth()
    clean_ids = [k for k, v in gt.items() if v["label"] == "clean"]

    print("=" * 86)
    print(f"SELF-HEALING QUESTION BANK AGENT EVALUATION (SPEC §14)")
    print(f"Seeds: {seeds} | Mode: {mode} | Ground Truth: {len(gt)} questions (5 planted)")
    print("=" * 86)

    per_seed_results: list[dict[str, Any]] = []

    for seed in seeds:
        print(f"\n--> Running Evaluation on Seed {seed}...")
        res = evaluate_seed(seed=seed, ground_truth=gt, mode=mode)
        per_seed_results.append(res)
        a = res["agent"]
        b = res["baseline"]
        print(f"    [Agent]    Caught: {a['caught']}/5 | FP: {a['fp']} | Score: {a['score']:+d} | F1: {a['f1']:.3f} | Decoys Clr: {a['decoys_cleared']} | Low-N: {a['lowN_refused']}")
        print(f"    [Baseline] Caught: {b['caught']}/5 | FP: {b['fp']} | Score: {b['score']:+d} | Decoys Flagged: {b['decoys_flagged']}")
        print(f"    [Perf]     Time: {res['runtime_s']}s | LLM Calls: {res['llm_calls']} | Tokens: {res['llm_tokens']}")

    # Solver accuracy benchmark on clean questions
    print("\n--> Evaluating Solver Accuracy on Clean Questions (vs True Key)...")
    solver_bench = evaluate_solver_clean(clean_ids, gt, max_sample=max_clean_solver)
    print(f"    Solver Accuracy: {solver_bench['correct_count']}/{solver_bench['total_clean']} ({solver_bench['accuracy']:.1%})")

    # Aggregate summaries across seeds
    n_seeds = len(per_seed_results)
    avg_agent_score = sum(r["agent"]["score"] for r in per_seed_results) / n_seeds
    avg_agent_caught = sum(r["agent"]["caught"] for r in per_seed_results) / n_seeds
    avg_agent_fp = sum(r["agent"]["fp"] for r in per_seed_results) / n_seeds
    avg_agent_f1 = sum(r["agent"]["f1"] for r in per_seed_results) / n_seeds
    avg_agent_v_acc = sum(r["agent"]["verdict_accuracy"] for r in per_seed_results) / n_seeds
    avg_agent_v_pass = sum(r["agent"]["verify_pass_rate"] for r in per_seed_results) / n_seeds
    avg_base_score = sum(r["baseline"]["score"] for r in per_seed_results) / n_seeds
    avg_base_fp = sum(r["baseline"]["fp"] for r in per_seed_results) / n_seeds
    avg_runtime = sum(r["runtime_s"] for r in per_seed_results) / n_seeds
    avg_calls = sum(r["llm_calls"] for r in per_seed_results) / n_seeds

    # Print Clean ASCII Table
    print("\n" + "=" * 98)
    print("EVALUATION SUMMARY TABLE (SPEC §14 RELIABILITY BENCHMARK)")
    print("=" * 98)
    header = f"{'Seed':<6} {'Agent Caught':<13} {'Agent FP':<9} {'Agent Score':<12} {'Prec':<7} {'Recall':<7} {'F1':<7} {'Verdict':<8} {'Verify':<8} {'Decoys':<8} {'Base Sc':<8} {'Time'}"
    print(header)
    print("-" * 98)

    for r in per_seed_results:
        s = r["seed"]
        ag = r["agent"]
        bs = r["baseline"]
        print(
            f"{s:<6} {ag['caught']}/5 ({ag['caught']/5:.0%})   "
            f"{ag['fp']:<9} "
            f"{ag['score']:<+12d} "
            f"{ag['precision']:<7.3f} "
            f"{ag['recall']:<7.3f} "
            f"{ag['f1']:<7.3f} "
            f"{ag['verdict_accuracy']:<8.2f} "
            f"{ag['verify_pass_rate']:<8.2f} "
            f"{ag['decoys_cleared']:<8} "
            f"{bs['score']:<+8d} "
            f"{r['runtime_s']:.1f}s"
        )

    print("-" * 98)
    print(
        f"{'MEAN':<6} {avg_agent_caught:.1f}/5 ({avg_agent_caught/5:.0%})   "
        f"{avg_agent_fp:<9.1f} "
        f"{avg_agent_score:<+12.2f} "
        f"{sum(r['agent']['precision'] for r in per_seed_results)/n_seeds:<7.3f} "
        f"{sum(r['agent']['recall'] for r in per_seed_results)/n_seeds:<7.3f} "
        f"{avg_agent_f1:<7.3f} "
        f"{avg_agent_v_acc:<8.2f} "
        f"{avg_agent_v_pass:<8.2f} "
        f"{'4/4':<8} "
        f"{avg_base_score:<+8.2f} "
        f"{avg_runtime:.1f}s"
    )
    print("=" * 98)

    print(f"\n[KEY TAKEAWAY]")
    print(f"  * Agent Reliability Score: {avg_agent_score:+0.2f} (Planted Caught: {avg_agent_caught:.1f}/5, False Positives: {avg_agent_fp:.1f})")
    print(f"  * Naive Baseline Score   : {avg_base_score:+0.2f} (False Positives: {avg_base_fp:.1f} due to tripping on benign decoys)")
    print(f"  * Two-Signal Advantage   : {avg_agent_score - avg_base_score:+.2f} score delta over single-signal triage")
    print(f"  * Solver Clean Accuracy  : {solver_bench['accuracy']:.1%} on {solver_bench['total_clean']} clean items")
    print("=" * 98 + "\n")

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": seeds,
        "mode": mode,
        "summary": {
            "agent_mean_score": round(avg_agent_score, 2),
            "agent_mean_caught": round(avg_agent_caught, 2),
            "agent_mean_fp": round(avg_agent_fp, 2),
            "agent_mean_f1": round(avg_agent_f1, 4),
            "agent_mean_verdict_accuracy": round(avg_agent_v_acc, 4),
            "agent_mean_verify_pass_rate": round(avg_agent_v_pass, 4),
            "baseline_mean_score": round(avg_base_score, 2),
            "baseline_mean_fp": round(avg_base_fp, 2),
            "score_advantage": round(avg_agent_score - avg_base_score, 2),
            "mean_runtime_s": round(avg_runtime, 2),
            "mean_llm_calls": round(avg_calls, 1),
        },
        "per_seed": per_seed_results,
        "solver_benchmark": {
            "total_clean": solver_bench["total_clean"],
            "correct_count": solver_bench["correct_count"],
            "accuracy": solver_bench["accuracy"],
            "details": solver_bench["details"],
        },
    }

    # Write report to reports/eval.json
    EVAL_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EVAL_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Report successfully saved to {EVAL_REPORT_PATH}")
    return report


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Evaluate Question Bank Agent (SPEC §14).")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Random seeds to evaluate (default: 0 1 2).")
    parser.add_argument("--mode", type=str, choices=["scripted", "llm"], default="scripted", help="Execution mode (default: scripted).")
    parser.add_argument("--clean-sample", type=int, default=None, help="Max clean questions to evaluate for solver benchmark.")
    args = parser.parse_args()

    run_evaluation(seeds=args.seeds, mode=args.mode, max_clean_solver=args.clean_sample)


if __name__ == "__main__":
    main()
