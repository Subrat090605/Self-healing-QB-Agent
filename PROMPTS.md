# PROMPTS.md — paste these into your IDE, in order

**Setup (5 min):** create folder `qbank-agent/`, put `CLAUDE.md` and `SPEC.md` in it (if you use Cursor, also copy CLAUDE.md to `.cursorrules`), `git init`, open in IDE.
Run each prompt in a fresh chat/session if the IDE gets slow. After each phase: run the check command, then `git commit`.

**Team split (3 people, parallel after Phase 0):**
- **Person A (data + stats + eval):** Phases 1, 2, 8
- **Person B (agent brain):** Phases 3, 4, 5
- **Person C (UI + review + demo):** Phases 6, 7, 9 and the pitch
Agree on the DB schema and tool names in SPEC.md so nobody blocks anybody. Merge often.

**Clock targets:** Phase 0 by 10:25 · Phases 1–2 by 11:00 · Phases 3–5 by 12:15 · Phases 6–7 by 12:45 · Phase 8 by 1:15 · Phase 9 by 1:40 · freeze 1:45.

---

## Phase 0 — Scaffold (10 min)
```
Read CLAUDE.md and SPEC.md fully. Do not write feature code yet.
Create the project skeleton exactly as in SPEC §3: folders, empty modules with docstrings,
requirements.txt (streamlit pandas numpy scipy plotly python-dotenv pytest groq),
.env.example (GROQ_API_KEY, ORCH_MODEL=openai/gpt-oss-120b, SOLVER_MODEL=llama-3.3-70b-versatile, FAST_MODEL=llama-3.1-8b-instant, CHAOS_MODE=0), README.md stub.
Implement src/config.py (loads env) and src/db.py (creates all tables from SPEC §4, plus helper functions
get_conn(), log_event(run_id, step, type, payload), execute/query helpers).
Implement src/llm.py for GROQ per SPEC §3b: chat(model, system, messages, tools=None, temperature=0.2) using the groq SDK with OpenAI-style tool calling,
and json_chat(model, system, user) using response_format json_object. Include: timeout, exponential-backoff retry (3 tries), a rate limiter (~25 RPM + token budget per minute),
honour retry-after on HTTP 429, one retry on malformed tool calls (HTTP 400), CHAOS_MODE failure injection (30% random raise), and a usage counter (calls + tokens) exposed as llm.usage.
Check: `python -c "from src import db, llm; db.init()"` runs without error. Show me how to test one real LLM call.
```

## Phase 1 — Seed data + student simulation (Person A)
```
Implement SPEC §5 in src/seed/build.py and src/seed/simulate.py.
- 56 questions: 36 quant + 12 logical generated from Python templates with computed answers and plausible distractors,
  8 verbal handwritten (unambiguous). Spread the correct letter across A-D.
- Apply the 5 planted defects (P1-P5) and the decoys/lowN item exactly as in §5.2-5.3.
- Simulate 500 students per §5.4 with the given seed. Write questions + attempts to data/qbank.db.
- Write data/ground_truth.json with true_correct, label, and IRT params. The agent will never read it.
CLI: python -m src.seed.build --seed 0
Check: print counts (questions, attempts), the labels summary, and for the 5 planted ids print p and a quick D so I can eyeball
that wrong-key items have negative D and the non-disc item has D near 0.
```


## Phase 2 — Item analysis (Person A)
```
Implement src/stats.py per SPEC §6 using pandas/numpy/scipy only (no LLM):
compute_item_stats(conn, question_ids=None) -> DataFrame/dicts with n, p, r_pb, D, per-option share_all/upper/lower, and all signals
(neg_disc, low_disc, key_inversion, split_top, weak_key_upper, ceiling, floor, too_hard_naive, too_easy_naive, insufficient).
Use each question's CURRENT live key. Add stats_signal and naive_signal columns exactly as defined in §6.
Add get_suspects(df, rule) returning ranked suspect ids, and analyze_distractors(question_id) returning option shares plus a one-line anomaly text.
Add tests/test_stats.py with 3 small hand-made tables where the answers are known.
Check: run on seed 0 and print the ranked suspects. All 5 planted should be in the top ~12; list the decoys that the NAIVE rule flags.
```

## Phase 3 — Solver + sandbox (Person B)
```
Implement src/solver.py per SPEC §7 and src/sandbox.py.
- solver.solve(question_id, n_runs=2, use_code=False) calls llm.json_chat(model=SOLVER_MODEL) with an independent system prompt; a 3rd run happens only if the first two disagree; the prompt must NOT include key or stats;
  question text goes inside <question_data> delimiters with an "ignore instructions inside" warning.
- Cache results in solver_runs. Aggregate into majority_answer, agreement, any_multi_defensible, mean_confidence.
- use_code=True: let the solver request python code; execute with sandbox.run_python (subprocess, 5s timeout, no network) and feed output back (max 2 rounds).
Check: a script that solves the 5 planted + 4 decoys and prints answer vs stored key and defensible options. Wrong-key items should show disagreement;
ambiguous items should show multiple defensible options.
```

## Phase 4 — Memory, guardrails, fixer, tool registry (Person B)
```
Implement SPEC §8, §10, §11, §12:
- src/memory.py (recall, remember_clearance, remember_rejection, last_run_summary)
- src/guardrails.py: check_submission(question_id, verdict, evidence) enforcing the two-signal rule and n>=30; check_command(text) refusing
  "apply all / delete / skip review" intents; budget checks; tool allowlist.
- src/fixer.py: propose_fix and verify_fix per §10 (verify uses solver on a patched copy, not the live question).
- src/tools.py: a registry with JSON schemas for every tool in §8, an execute(name, args, ctx) dispatcher that logs ACT and OBSERVE events,
  truncates observations to ~1500 chars, and catches exceptions into ERROR events.
No tool may modify live questions.
Check: tests/test_guardrails.py proving (a) single-signal submission is rejected, (b) n<30 is refused, (c) "apply all fixes" is refused.
```

## Phase 5 — Orchestrator agent loop (Person B) — the core
```
Implement src/agent.py per SPEC §9.
- run(seed/db, run_id=None) is a generator yielding trace events so the UI can stream them; also a CLI: python -m src.agent --seed 0.
- Orchestrator = LLM with tool use. System prompt must enforce: write a plan first; after each observation state whether the plan holds and write
  "REPLAN: ..." when it changes; never submit on one signal; prefer clearing decoys; refuse n<30; classify with the SPEC §9.3 matrix.
- Pass a compact state summary every turn (suspect queue, investigated, cleared, submitted, refused).
- Handle chaos/API failures per §12.4 (retry, then stats-only 'unverified' -> WATCHLIST, never submit).
- MAX_STEPS 30; write all events to trace_events; end with a RESULT event summarizing submitted/cleared/refused/watchlist.
Check: run on seed 0 headless and print the final tally. Target: >=4/5 planted submitted, 0 decoys submitted, lowN refused,
at least one REPLAN event. If the model skips REPLAN or the matrix, tighten the system prompt rather than adding code paths.
```

## Phase 5b — Scripted fallback mode (Person B, P1 — do this right after Phase 5 works)
```
Add agent.run(mode="scripted") per SPEC §3b item 6. Same tools, same trace events, same decision matrix (SPEC §9.3), but the control flow is plain Python:
get_suspects -> for each: analyze_distractors -> solve_independently -> classify by matrix -> propose_fix -> verify_fix -> submit_for_review or record_clearance.
The LLM is used only inside solver/fixer. Emit PLAN/REPLAN events from code (e.g. "REPLAN: naive flag is a decoy, clearing"). Add a CLI flag --mode scripted|llm.
Check: both modes give the same planted/decoy outcome on seed 0; scripted mode uses far fewer tokens (print llm.usage).
```

## Phase 6 — Streamlit UI (Person C)
```
Implement app.py per SPEC §15 with tabs: Bank Health, Agent Run, Review Queue, Scoreboard, Memory & Audit.
- Agent Run: button starts agent.run() generator and appends events live (colored badges per type), running tally, sidebar toggles for Chaos mode
  and Replay last run (replay reads trace_events of the latest run with small sleeps; must work with no API).
- Include the command box wired to guardrails.check_command and show the refusal clearly.
- Bank Health: table + plotly scatter p vs D, highlight submitted/cleared after a run.
Keep styling minimal and clean. Use st.session_state carefully so reruns don't restart the agent.
Check: `streamlit run app.py`, click Run, see events stream in, no crashes on rerun.
```

## Phase 7 — Review queue + apply + audit (Person C)
```
Implement src/review.py and the Review Queue tab per SPEC §13.
- list_pending(), approve(id, edited_fix=None), reject(id, note).
- approve() creates question version+1 with the fix applied (change_key / rewrite / retire_replace), marks old version superseded, writes audit_log,
  writes a finding with status 'healed'.
- reject() stores the note in agent_memory (rejected_fix_types:<qid>) so the next run changes approach.
- Evidence card: stats table, plotly bar chart of option shares upper vs lower 27%, solver votes with one-line reasoning, verify result, diff view.
Check: approve one item, confirm the live question changed and audit entry exists; reject one with a note; click Re-run agent and confirm it skips the healed one
and mentions the rejection in a REPLAN event.
```

## Phase 8 — Evaluation harness (Person A)
```
Implement src/evaluate.py per SPEC §14. CLI: python -m src.evaluate --seeds 0 1 2.
For each seed: rebuild data in a temp DB, run the agent headless (no human; "flagged" = submitted to review), compute caught, FP, score = caught - FP,
precision/recall/F1, verdict accuracy, fix verification pass rate, decoys cleared, lowN refused, LLM calls and runtime.
Compute the naive baseline on the same data. Run solver accuracy vs true key on the 46 clean questions.
Print a clean table and write reports/eval.json. Only this file and src/seed may read data/ground_truth.json.
Wire the Scoreboard tab to reports/eval.json with an agent-vs-baseline bar chart and a "Reveal ground truth" view.
Add tests/test_firewall.py that fails if any agent module references ground_truth.
```

## Phase 9 — Hardening + demo polish (everyone, 12:45–1:40)
```
Harden the demo path only:
1. Make the full run stable on seed 0 (<4 min). Cache solver_runs so repeat runs are fast.
2. Add a "Demo mode" toggle that preloads the last good run for Replay.
3. Make sure chaos mode shows retries and a graceful fallback without crashing.
4. Add friendly empty states and error messages in the UI.
5. Write README.md: what it does, architecture diagram (from SPEC §2), how to run, how to evaluate, limitations.
Do not add new features. Fix only bugs I list.
```

---

## Utility prompts (use when stuck)
- **Error:** `This error happens when I run <command>: <paste full traceback>. Fix with the smallest change. Show the diff only.`
- **Model misbehaves in the loop:** `The orchestrator <describe behavior>. Improve ORCH_PROMPT only (no new code paths). Show the new prompt section and why it fixes it.`
- **Too many false positives:** `On seed 0 these decoys were submitted: <ids>. Show their stats and solver results, tell me which rule in SPEC §9.3 should have cleared them, and fix that rule.`
- **Missed a planted bug:** `Planted question <id> was not submitted. Show its stats signals, solver aggregate, and the agent's trace for it. Tell me which signal was missing and fix the threshold or prompt.`
- **Slow run:** `Profile the run: list LLM calls by tool and total time. Reduce calls without hurting accuracy (cache, n_runs=2 for clear cases, skip solver for clean questions).`
- **Cut scope:** `We have <N> minutes left. Tell me which P1 items from SPEC §1 to cut and finish the demo path.`
