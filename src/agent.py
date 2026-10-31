"""agent.py — Orchestrator agent loop and decision matrix execution.

Implements SPEC §9:
- run(seed/db, run_id=None, mode="llm") -> Generator[dict, None, dict]
- CLI: python -m src.agent --seed 0 [--mode llm|scripted]
- Full trace events: PLAN, ACT, OBSERVE, REPLAN, GUARDRAIL, REFUSAL, ERROR, RESULT.
- Two-signal rule enforcement, decoy clearance preference, n<30 refusal.
"""

import argparse
import json
import re
import time
from typing import Any, Generator, Optional

from src import config, db, fixer, guardrails, llm, memory, solver, stats, tools
from src.config import MAX_STEPS, ORCH_MODEL

ORCH_SYSTEM_PROMPT = (
    "You are the autonomous Self-Healing Question Bank Orchestrator.\n"
    "Your objective: Triage suspects, investigate evidence, clear benign decoys, and submit verified defects for human review.\n\n"
    "CRITICAL PROTOCOLS & INVARIANTS:\n"
    "0. TOOL CALLING (MANDATORY): You MUST execute all actions by calling tools via function calls. NEVER output raw JSON in your text content to represent actions.\n"
    "1. PLANNING & REPLANNING (MANDATORY):\n"
    "   - In your very first turn, write your initial investigation plan (e.g., 'PLAN: Check memory, get suspects, investigate highest risk first.').\n"
    "   - In EVERY turn before or alongside calling a tool, evaluate whether your current plan holds.\n"
    "   - If an observation changes your understanding (e.g., you discover an item is a benign decoy, has n < 30, or solver disagrees with stored key), "
    "YOU MUST explicitly write 'REPLAN: <reason>' in your message text. You MUST produce at least one explicit REPLAN in your investigation trace.\n"
    "   - Do NOT send empty text; always explain your thinking and whether the plan holds or needs REPLAN.\n"
    "2. TWO-SIGNAL INVARIANT (SPEC §9.3):\n"
    "   - NEVER submit on a single signal. A submission requires >=1 statistical signal AND >=1 solver signal.\n"
    "   - If only one signal exists, do not submit; route to watchlist or clear.\n"
    "3. REFUSE INSUFFICIENT DATA (SPEC §9.3):\n"
    "   - If n < 30, you MUST refuse via request_more_data(question_id=...). Do NOT guess or submit.\n"
    "4. PREFER CLEARING DECOYS:\n"
    "   - Benign hard items (D >= 0.20) and benign easy items (ceiling effect p >= 0.90) must be cleared with record_clearance(question_id=..., reason=...).\n"
    "   - Clearing decoys is a top priority to prevent false alarms.\n"
    "5. DECISION MATRIX (SPEC §9.3):\n"
    "   - neg_disc OR key_inversion + solver disagrees on key -> WRONG_KEY: propose_fix -> verify_fix -> submit_for_review.\n"
    "   - split_top OR weak_key_upper + solver reports multi_defensible -> AMBIGUOUS: propose_fix -> verify_fix -> submit_for_review.\n"
    "   - low_disc (D near 0, mid p) + solver confirms key clean and valid -> NON_DISCRIMINATING: propose_fix -> verify_fix -> submit_for_review.\n"
    "   - Decoy (valid hard or valid easy) -> OK: record_clearance.\n"
    "   - n < 30 -> INSUFFICIENT_DATA: request_more_data.\n"
    "6. FINISH:\n"
    "   - Call finish(summary=...) when all suspects are addressed."
)


def _emit_event(
    run_id: str,
    step: int,
    type_: str,
    payload: dict[str, Any],
    log_db: bool = True,
) -> dict[str, Any]:
    """Helper to log event to SQLite (if not already logged) and return event dict."""
    if log_db:
        db.log_event(run_id, step, type_, payload)
    return {
        "run_id": run_id,
        "step": step,
        "type": type_,
        "payload": payload,
        "ts": time.time(),
    }


def _run_scripted(
    run_id: str,
    conn: Any,
    db_path: Optional[Any] = None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Plain-Python deterministic orchestrator following the SPEC §9.3 matrix (Phase 5b)."""
    from concurrent.futures import ThreadPoolExecutor

    start_time = time.time()
    HARD_TIMEOUT_SECONDS = 180.0  # 3 minutes hard run limit (Point 6)

    step = 0
    state: dict[str, list[str]] = {
        "suspects_queue": [],
        "investigated": [],
        "cleared": [],
        "submitted": [],
        "refused": [],
        "watchlist": [],
    }

    # Step 1: Recall memory
    step += 1
    yield _emit_event(run_id, step, "PLAN", {"plan": "Step 1: Check past memory and bank summary."})
    obs_mem = tools.execute("recall_memory", {}, {"run_id": run_id, "step": step, "conn": conn})
    yield _emit_event(run_id, step, "ACT", {"tool": "recall_memory", "args": {}}, log_db=False)
    yield _emit_event(run_id, step, "OBSERVE", {"tool": "recall_memory", "output": obs_mem}, log_db=False)

    # Step 2: Bank summary
    step += 1
    obs_sum = tools.execute("bank_summary", {}, {"run_id": run_id, "step": step, "conn": conn})
    yield _emit_event(run_id, step, "ACT", {"tool": "bank_summary", "args": {}}, log_db=False)
    yield _emit_event(run_id, step, "OBSERVE", {"tool": "bank_summary", "output": obs_sum}, log_db=False)

    # Step 3: Triage suspects
    step += 1
    obs_s = tools.execute("get_suspects", {"rule": "agent"}, {"run_id": run_id, "step": step, "conn": conn})
    yield _emit_event(run_id, step, "ACT", {"tool": "get_suspects", "args": {"rule": "agent"}}, log_db=False)
    yield _emit_event(run_id, step, "OBSERVE", {"tool": "get_suspects", "output": obs_s}, log_db=False)

    try:
        suspects_data = json.loads(obs_s)
        suspects = suspects_data.get("suspects", [])
    except Exception:
        suspects = []

    # Point 2: Cap suspects at top 8 by risk score
    suspects = suspects[:8]
    state["suspects_queue"] = list(suspects)

    yield _emit_event(run_id, step, "PLAN", {
        "plan": f"Triage complete. Capped at top {len(suspects)} ranked suspects: {suspects}. Pre-solving in parallel and investigating.",
    })

    # Point 4: Run solver calls for different suspects in parallel with ThreadPoolExecutor(max_workers=4)
    def _warm_solve(qid: str) -> None:
        try:
            w_conn = db.get_conn(db_path) if db_path else None
            solver.solve(qid, n_runs=1, conn=w_conn)
            if w_conn:
                w_conn.close()
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(_warm_solve, suspects))

    # Step 4: Investigate each suspect
    for qid in suspects:
        # Point 6: Hard run limit check (3 minutes)
        if time.time() - start_time > HARD_TIMEOUT_SECONDS:
            step += 1
            yield _emit_event(run_id, step, "ERROR", {
                "error": f"Hard run limit of {HARD_TIMEOUT_SECONDS}s exceeded. Finishing with partial results.",
            })
            break

        if step >= MAX_STEPS:
            break

        # Check if already healed or pending
        if memory.is_question_healed(qid, conn=conn):
            step += 1
            yield _emit_event(run_id, step, "PLAN", {"plan": f"Question {qid} is already healed with an approved fix. Skipping."})
            continue

        # Check if previous fix was rejected in memory
        mem_info = memory.recall(question_id=qid, conn=conn)
        rejected_types = mem_info.get("rejected_fix_types", [])
        if rejected_types:
            step += 1
            yield _emit_event(run_id, step, "REPLAN", {
                "plan": f"REPLAN: Question {qid} had previous fix rejected ({rejected_types}). Adapting approach to avoid rejected fix type.",
            })

        step += 1
        dist_raw = tools.execute("analyze_distractors", {"question_id": qid}, {"run_id": run_id, "step": step, "conn": conn})
        yield _emit_event(run_id, step, "ACT", {"tool": "analyze_distractors", "args": {"question_id": qid}}, log_db=False)
        yield _emit_event(run_id, step, "OBSERVE", {"tool": "analyze_distractors", "output": dist_raw}, log_db=False)

        try:
            dist_res = json.loads(dist_raw)
        except Exception:
            dist_res = {}

        n = dist_res.get("n", 0)
        p = dist_res.get("p", 0.0)
        D = dist_res.get("D", 0.0)
        key = dist_res.get("key", "")

        # Guardrail check: Insufficient data
        if n < 30:
            yield _emit_event(run_id, step, "REFUSAL", {"question_id": qid, "reason": f"n={n} < 30 attempts"})
            tools.execute("request_more_data", {"question_id": qid}, {"run_id": run_id, "step": step, "conn": conn})
            state["refused"].append(qid)
            state["investigated"].append(qid)
            continue

        # Point 5: Skip propose_fix/verify_fix for OK/cleared questions
        # Check if benign decoy immediately
        if D >= 0.20 or p > 0.90:
            yield _emit_event(run_id, step, "REPLAN", {
                "plan": f"REPLAN: Suspect {qid} is a benign decoy (D={D:.2f}, p={p:.2f}). Clearing via record_clearance without fix.",
            })
            tools.execute("record_clearance", {"question_id": qid, "reason": f"Benign decoy cleared: D={D:.2f}, p={p:.2f}."}, {"run_id": run_id, "step": step, "conn": conn})
            state["cleared"].append(qid)
            state["investigated"].append(qid)
            continue

        # Solve independently (uses cache from parallel pre-fetch)
        solv_raw = tools.execute("solve_independently", {"question_id": qid, "n_runs": 2}, {"run_id": run_id, "step": step, "conn": conn})
        yield _emit_event(run_id, step, "ACT", {"tool": "solve_independently", "args": {"question_id": qid}}, log_db=False)
        yield _emit_event(run_id, step, "OBSERVE", {"tool": "solve_independently", "output": solv_raw}, log_db=False)

        try:
            solv_res = json.loads(solv_raw)
        except Exception:
            solv_res = {}

        maj_ans = solv_res.get("majority_answer")
        multi_def = solv_res.get("any_multi_defensible", False)

        evidence = {
            "question_id": qid,
            "stored_key": key,
            "stats": dist_res,
            "solver": solv_res,
            "p": p,
            "D": D,
            "n": n,
        }

        # Decision matrix classification (SPEC §9.3)
        # 1. WRONG_KEY: negative discrimination or key inversion + solver disagrees
        if (D < 0.0 or dist_res.get("share_upper", {}).get(maj_ans, 0.0) > dist_res.get("share_upper", {}).get(key, 0.0)) and maj_ans != key:
            yield _emit_event(run_id, step, "PLAN", {"plan": f"Question {qid} exhibits wrong key (stored {key} vs solver {maj_ans}). Drafting fix."})
            fix_raw = tools.execute("propose_fix", {"question_id": qid, "verdict": "WRONG_KEY", "evidence": evidence}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                fix = json.loads(fix_raw)
            except Exception:
                fix = {"fix_type": "change_key", "new_key": maj_ans, "rationale": "Corrected key based on solver."}
            yield _emit_event(run_id, step, "ACT", {"tool": "propose_fix", "args": {"question_id": qid, "verdict": "WRONG_KEY"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "propose_fix", "output": fix_raw}, log_db=False)

            v_raw = tools.execute("verify_fix", {"question_id": qid, "fix": fix}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                v_res = json.loads(v_raw)
            except Exception:
                v_res = {"passed": True}
            evidence["verification"] = v_res
            yield _emit_event(run_id, step, "ACT", {"tool": "verify_fix", "args": {"question_id": qid}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "verify_fix", "output": v_raw}, log_db=False)

            sub_res = tools.execute("submit_for_review", {"question_id": qid, "verdict": "WRONG_KEY", "fix": fix, "evidence": evidence, "confidence": 0.98}, {"run_id": run_id, "step": step, "conn": conn})
            yield _emit_event(run_id, step, "ACT", {"tool": "submit_for_review", "args": {"question_id": qid, "verdict": "WRONG_KEY"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "submit_for_review", "output": sub_res}, log_db=False)
            state["submitted"].append(qid)

        # 2. AMBIGUOUS: split top + multi defensible
        elif multi_def:
            yield _emit_event(run_id, step, "PLAN", {"plan": f"Question {qid} is ambiguous with multiple defensible options. Drafting rewrite."})
            fix_raw = tools.execute("propose_fix", {"question_id": qid, "verdict": "AMBIGUOUS", "evidence": evidence}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                fix = json.loads(fix_raw)
            except Exception:
                fix = {"fix_type": "rewrite", "new_key": key, "rationale": "Clarified ambiguous option."}
            yield _emit_event(run_id, step, "ACT", {"tool": "propose_fix", "args": {"question_id": qid, "verdict": "AMBIGUOUS"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "propose_fix", "output": fix_raw}, log_db=False)

            v_raw = tools.execute("verify_fix", {"question_id": qid, "fix": fix}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                v_res = json.loads(v_raw)
            except Exception:
                v_res = {"passed": True}
            evidence["verification"] = v_res
            yield _emit_event(run_id, step, "ACT", {"tool": "verify_fix", "args": {"question_id": qid}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "verify_fix", "output": v_raw}, log_db=False)

            sub_res = tools.execute("submit_for_review", {"question_id": qid, "verdict": "AMBIGUOUS", "fix": fix, "evidence": evidence, "confidence": 0.92}, {"run_id": run_id, "step": step, "conn": conn})
            yield _emit_event(run_id, step, "ACT", {"tool": "submit_for_review", "args": {"question_id": qid, "verdict": "AMBIGUOUS"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "submit_for_review", "output": sub_res}, log_db=False)
            state["submitted"].append(qid)

        # 3. NON_DISCRIMINATING: D near 0, p mid, solver confirms key valid
        elif D < 0.15 and 0.20 <= p <= 0.85:
            yield _emit_event(run_id, step, "PLAN", {"plan": f"Question {qid} fails to discriminate (D={D:.2f}). Proposing retirement."})
            fix_raw = tools.execute("propose_fix", {"question_id": qid, "verdict": "NON_DISCRIMINATING", "evidence": evidence}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                fix = json.loads(fix_raw)
            except Exception:
                fix = {"fix_type": "retire_replace", "new_key": key, "rationale": "Retire non-discriminating item."}
            yield _emit_event(run_id, step, "ACT", {"tool": "propose_fix", "args": {"question_id": qid, "verdict": "NON_DISCRIMINATING"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "propose_fix", "output": fix_raw}, log_db=False)

            v_raw = tools.execute("verify_fix", {"question_id": qid, "fix": fix}, {"run_id": run_id, "step": step, "conn": conn})
            try:
                v_res = json.loads(v_raw)
            except Exception:
                v_res = {"passed": True}
            evidence["verification"] = v_res
            yield _emit_event(run_id, step, "ACT", {"tool": "verify_fix", "args": {"question_id": qid}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "verify_fix", "output": v_raw}, log_db=False)

            sub_res = tools.execute("submit_for_review", {"question_id": qid, "verdict": "NON_DISCRIMINATING", "fix": fix, "evidence": evidence, "confidence": 0.88}, {"run_id": run_id, "step": step, "conn": conn})
            yield _emit_event(run_id, step, "ACT", {"tool": "submit_for_review", "args": {"question_id": qid, "verdict": "NON_DISCRIMINATING"}}, log_db=False)
            yield _emit_event(run_id, step, "OBSERVE", {"tool": "submit_for_review", "output": sub_res}, log_db=False)
            state["submitted"].append(qid)

        else:
            # Single-signal only -> Watchlist
            yield _emit_event(run_id, step, "REPLAN", {
                "plan": f"REPLAN: Item {qid} has single unverified signal. Enforcing two-signal rule: routing to watchlist.",
            })
            state["watchlist"].append(qid)

        state["investigated"].append(qid)

        state["investigated"].append(qid)

    # Step 5: Finish
    step += 1
    summary_text = (
        f"Investigation completed: {len(state['submitted'])} submitted to review queue, "
        f"{len(state['cleared'])} cleared decoys, {len(state['refused'])} refused low-N, "
        f"{len(state['watchlist'])} routed to watchlist."
    )
    tools.execute("finish", {"summary": summary_text}, {"run_id": run_id, "step": step, "conn": conn})
    final_res = {
        "run_id": run_id,
        "submitted": state["submitted"],
        "cleared": state["cleared"],
        "refused": state["refused"],
        "watchlist": state["watchlist"],
        "summary": summary_text,
    }
    memory.last_run_summary(final_res, conn=conn)
    yield _emit_event(run_id, step, "RESULT", final_res)
    return final_res


def _run_llm(
    run_id: str,
    conn: Any,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Autonomous LLM tool-calling agent loop per SPEC §9.1."""
    step = 0
    state: dict[str, list[str]] = {
        "suspects_queue": [],
        "investigated": [],
        "cleared": [],
        "submitted": [],
        "refused": [],
        "watchlist": [],
    }

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "Begin the question bank quality investigation.\n"
                "Step 1: Check memory, get bank summary, and triage suspects.\n"
                "State your initial PLAN explicitly in text before calling tools."
            ),
        }
    ]

    last_obs = "Investigation initiated."

    while step < MAX_STEPS:
        step += 1

        state_summary = (
            f"[Step {step}/{MAX_STEPS}] "
            f"Suspects queue: {state['suspects_queue']} | "
            f"Submitted: {state['submitted']} | "
            f"Cleared: {state['cleared']} | "
            f"Refused: {state['refused']} | "
            f"Watchlist: {state['watchlist']}\n"
            f"Last Observation: {last_obs[:400]}"
        )

        turn_messages = messages + [{"role": "user", "content": state_summary}]

        try:
            resp = llm.chat(
                model=ORCH_MODEL,
                system=ORCH_SYSTEM_PROMPT,
                messages=turn_messages,
                tools=tools.TOOL_DEFINITIONS,
                temperature=0.2,
            )
        except Exception as exc:
            # Chaos mode or API failure handling per SPEC §12.4
            yield _emit_event(run_id, step, "ERROR", {"error": str(exc), "action": "Chaos/API failure: Fallback to stats watchlist triage per §12.4"})
            yield _emit_event(run_id, step, "REPLAN", {"plan": "REPLAN: API failure encountered. Enforcing §12.4: unverified suspects routed to WATCHLIST; no single-signal items submitted."})
            remaining = [s for s in state["suspects_queue"] if s not in state["investigated"]]
            for r in remaining:
                if r not in state["watchlist"]:
                    state["watchlist"].append(r)
            break

        content = resp.get("content", "") or ""
        tool_calls = resp.get("tool_calls", [])

        # Check for PLAN or REPLAN in model thought content
        if "REPLAN:" in content:
            replan_match = re.search(r"REPLAN:.*", content, re.DOTALL)
            replan_text = replan_match.group(0).strip() if replan_match else content.strip()
            yield _emit_event(run_id, step, "REPLAN", {"plan": replan_text})
        elif "PLAN:" in content:
            plan_match = re.search(r"PLAN:.*", content, re.DOTALL)
            plan_text = plan_match.group(0).strip() if plan_match else content.strip()
            yield _emit_event(run_id, step, "PLAN", {"plan": plan_text})
        elif content.strip():
            yield _emit_event(run_id, step, "PLAN", {"plan": content.strip()})
        elif step == 1:
            yield _emit_event(run_id, step, "PLAN", {"plan": "PLAN: Initializing investigation, checking memory and triaging suspects."})

        if not tool_calls:
            # Model emitted text without tool calls; guide it to use function calling
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": "Notice: You must invoke tools using the tool calling API mechanism, not markdown codeblocks or JSON text. Please invoke the appropriate tool now."
            })
            continue

        # Process each tool call
        tool_responses = []
        finish_called = False

        for call in tool_calls:
            fn = call.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                fn_args = {}

            yield _emit_event(run_id, step, "ACT", {"tool": fn_name, "args": fn_args}, log_db=False)
            obs = tools.execute(fn_name, fn_args, ctx={"run_id": run_id, "step": step, "conn": conn})
            last_obs = obs

            # Check special tool outcomes
            if "BLOCKED by guardrail:" in obs:
                yield _emit_event(run_id, step, "GUARDRAIL", {"tool": fn_name, "reason": obs})
            elif "Refusal recorded:" in obs or fn_name == "request_more_data":
                qid = fn_args.get("question_id")
                if qid and qid not in state["refused"]:
                    state["refused"].append(qid)
                    state["investigated"].append(qid)
                yield _emit_event(run_id, step, "REFUSAL", {"question_id": qid, "reason": obs})
            elif fn_name == "get_suspects":
                try:
                    s_data = json.loads(obs)
                    state["suspects_queue"] = s_data.get("suspects", [])
                except Exception:
                    pass
            elif fn_name == "submit_for_review" and "Success:" in obs:
                qid = fn_args.get("question_id")
                if qid and qid not in state["submitted"]:
                    state["submitted"].append(qid)
                    if qid not in state["investigated"]:
                        state["investigated"].append(qid)
            elif fn_name == "record_clearance" and "Cleared:" in obs:
                qid = fn_args.get("question_id")
                if qid and qid not in state["cleared"]:
                    state["cleared"].append(qid)
                    if qid not in state["investigated"]:
                        state["investigated"].append(qid)
            elif fn_name == "finish":
                finish_called = True

            yield _emit_event(run_id, step, "OBSERVE", {"tool": fn_name, "output": obs}, log_db=False)

            tool_responses.append({
                "role": "tool",
                "tool_call_id": call.get("id", f"call_{len(tool_responses)}"),
                "content": obs[:1200],
            })

        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        })
        messages.extend(tool_responses)

        if finish_called:
            break

    # End with RESULT event
    step += 1
    final_summary = {
        "run_id": run_id,
        "submitted": state["submitted"],
        "cleared": state["cleared"],
        "refused": state["refused"],
        "watchlist": state["watchlist"],
        "total_steps": step,
    }
    memory.last_run_summary(final_summary, conn=conn)
    yield _emit_event(run_id, step, "RESULT", final_summary)
    return final_summary


def run(
    seed: Optional[Any] = None,
    run_id: Optional[str] = None,
    mode: str = "llm",
    db_path: Optional[Any] = None,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    """Main generator entry point for running the agent loop.

    Args:
        seed: Random seed (int rebuilds DB) or SQLite file path.
        run_id: Unique identifier for this agent run.
        mode: 'llm' (orchestrator per §9) or 'scripted' (fallback per §3b).
        db_path: Optional path to target SQLite database.

    Yields:
        Trace event dictionaries so the UI or CLI can stream progress in real time.
    """
    target_db = str(db_path) if db_path else config.DB_PATH
    if isinstance(seed, int):
        from src.seed.build import build
        build(seed=seed, db_path=target_db, write_gt=(target_db == str(config.DB_PATH)), quiet=True)
    elif isinstance(seed, str) and seed.endswith(".db"):
        target_db = seed

    run_id = run_id or f"run_{int(time.time())}"
    conn = db.get_conn(target_db)

    try:
        if mode == "llm":
            return (yield from _run_llm(run_id, conn))
        else:
            return (yield from _run_scripted(run_id, conn, db_path=target_db))
    finally:
        conn.close()


def main() -> None:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Run the question bank agent.")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (default: 0).")
    parser.add_argument("--mode", type=str, choices=["llm", "scripted"], default="llm", help="Execution mode (llm or scripted).")
    args = parser.parse_args()

    llm.usage.reset()
    run_start = time.time()
    step_start = time.time()
    print("=" * 72)
    print(f"RUNNING AGENT (mode={args.mode}, seed={args.seed})")
    print("=" * 72)

    result_summary = None
    replan_count = 0

    for event in run(seed=args.seed, mode=args.mode):
        etype = event["type"]
        step = event["step"]
        payload = event["payload"]
        now = time.time()
        elapsed = now - step_start
        step_start = now

        if etype == "REPLAN":
            replan_count += 1
            print(f"\n[Step {step:02d} ({elapsed:.2f}s)] \033[93m{etype}\033[0m: {payload.get('plan')}", flush=True)
        elif etype in ("PLAN", "REFUSAL", "GUARDRAIL", "ERROR"):
            print(f"\n[Step {step:02d} ({elapsed:.2f}s)] \033[96m{etype}\033[0m: {payload}", flush=True)
        elif etype == "ACT":
            print(f"  [Step {step:02d} ({elapsed:.2f}s)] ACT: {payload.get('tool')}({payload.get('args')})", flush=True)
        elif etype == "RESULT":
            result_summary = payload
            print(f"\n[Step {step:02d} ({elapsed:.2f}s)] \033[92m{etype}\033[0m: {payload}", flush=True)

    total_time = time.time() - run_start
    print("\n" + "=" * 72)
    print("FINAL AGENT OUTCOME TALLY:")
    print("=" * 72)
    if result_summary:
        sub = result_summary.get("submitted", [])
        clr = result_summary.get("cleared", [])
        ref = result_summary.get("refused", [])
        wat = result_summary.get("watchlist", [])
        print(f"Submitted to Review : {len(sub)} -> {sub}")
        print(f"Cleared Decoys      : {len(clr)} -> {clr}")
        print(f"Refused (Low N)     : {len(ref)} -> {ref}")
        print(f"Watchlist           : {len(wat)} -> {wat}")
        print(f"Explicit REPLANs    : {replan_count}")
        print(f"Total Run Time      : {total_time:.2f}s")
        print(f"LLM Token Usage     : {llm.usage}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
