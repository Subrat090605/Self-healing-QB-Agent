"""app.py — Interactive Streamlit UI for the Self-Healing Question Bank Agent.

Implements SPEC §15:
- 5 Tabs: Bank Health, Agent Run, Review Queue, Scoreboard, Memory & Audit.
- Live streaming of agent events with badge indicators and running tally.
- Offline replay mode, Chaos mode toggle, Engine toggle (Scripted vs LLM).
- Safety command console demonstrating guardrail refusals.
- Rich evidence cards with Plotly distractor shares and before/after diffs.
- Ground truth scoreboard and persistent audit log.
"""

import json
import os
import sqlite3
import time
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import agent, config, db, guardrails, memory, review, stats
from src.config import DB_PATH

# -- Page Configuration & Styling ---------------------------------------------
st.set_page_config(
    page_title="Self-Healing Question Bank Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .metric-card {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 12px 16px;
        border-left: 4px solid #1f77b4;
        margin-bottom: 8px;
    }
    .badge-plan { background-color: #e3f2fd; color: #0d47a1; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-act { background-color: #ede7f6; color: #4a148c; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-observe { background-color: #f1f8e9; color: #33691e; padding: 3px 8px; border-radius: 4px; font-weight: 600; }
    .badge-replan { background-color: #fff8e1; color: #f57f17; padding: 3px 8px; border-radius: 4px; font-weight: 700; }
    .badge-guardrail { background-color: #ffebee; color: #b71c1c; padding: 3px 8px; border-radius: 4px; font-weight: 700; }
    .badge-refusal { background-color: #fce4ec; color: #880e4f; padding: 3px 8px; border-radius: 4px; font-weight: 700; }
    .badge-result { background-color: #e8f5e9; color: #1b5e20; padding: 3px 8px; border-radius: 4px; font-weight: 700; }
    .badge-error { background-color: #ffcdd2; color: #b71c1c; padding: 3px 8px; border-radius: 4px; font-weight: 700; }
    .stButton>button { border-radius: 6px; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -- Initialize Session State --------------------------------------------------
if "trace_events" not in st.session_state:
    st.session_state.trace_events = []
if "agent_running" not in st.session_state:
    st.session_state.agent_running = False
if "latest_summary" not in st.session_state:
    st.session_state.latest_summary = None
if "submitted_ids" not in st.session_state:
    st.session_state.submitted_ids = set()
if "cleared_ids" not in st.session_state:
    st.session_state.cleared_ids = set()
if "refused_ids" not in st.session_state:
    st.session_state.refused_ids = set()
if "watchlist_ids" not in st.session_state:
    st.session_state.watchlist_ids = set()


def get_db():
    return db.get_conn(DB_PATH)


# -- Sidebar Controls ----------------------------------------------------------
with st.sidebar:
    st.title("🛡️ Agent Control")
    st.markdown("Autonomous psychometric self-healing system.")
    st.divider()

    engine_mode = st.radio(
        "Agent Engine",
        options=["scripted", "llm"],
        index=0,
        help="Scripted runs plain-Python control flow (<90s). LLM runs autonomous orchestrator.",
    )

    chaos_toggle = st.toggle(
        "Chaos Mode (30% API failure)",
        value=bool(config.CHAOS_MODE),
        help="Simulates 30% API failures/timeouts to test retry and §12.4 watchlist fallback.",
    )
    config.CHAOS_MODE = int(chaos_toggle)

    st.divider()
    st.subheader("Data & Replay")
    seed_input = st.number_input("Random Seed", min_value=0, max_value=999, value=0, step=1)

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Rebuild DB", use_container_width=True):
            from src.seed.build import build
            with st.spinner("Generating 56 items and simulating attempts..."):
                build(seed=int(seed_input))
            st.success("Rebuilt!")
            st.rerun()

    with col_btn2:
        replay_mode = st.button("Replay Last", use_container_width=True)

    st.divider()
    st.caption("Self-Healing Question Bank Agent • SPEC §15")


# -- Main Navigation Tabs ------------------------------------------------------
tab_health, tab_run, tab_review, tab_score, tab_audit = st.tabs([
    "📊 Bank Health",
    "⚡ Agent Run",
    "📝 Review Queue",
    "🎯 Scoreboard",
    "🧠 Memory & Audit",
])


# ==============================================================================
# TAB 1: Bank Health
# ==============================================================================
with tab_health:
    st.header("Item Statistics & Bank Health")
    conn = get_db()
    try:
        df_stats = stats.compute_item_stats(conn=conn)
        q_rows = conn.execute("SELECT id, category FROM questions WHERE status='live'").fetchall()
        cat_map = {r["id"]: r["category"] for r in q_rows}
        df_stats["category"] = df_stats["question_id"].map(cat_map).fillna("quant")

        # Color-coded decision based on the latest run's findings table
        latest_finding = conn.execute(
            "SELECT run_id FROM findings WHERE run_id NOT LIKE 'run_unit%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        latest_run_id = latest_finding["run_id"] if latest_finding else None

        decision_map = {}
        if latest_run_id:
            f_rows = conn.execute(
                "SELECT question_id, status FROM findings WHERE run_id = ?",
                (latest_run_id,),
            ).fetchall()
            for r in f_rows:
                st_val = r["status"]
                if st_val == "submitted":
                    decision_map[r["question_id"]] = "submitted for review"
                elif st_val == "cleared":
                    decision_map[r["question_id"]] = "cleared decoy"
                elif st_val == "refused":
                    decision_map[r["question_id"]] = "refused (insufficient data)"

        # Overlay any decisions from the active session run
        for qid in st.session_state.submitted_ids:
            decision_map[qid] = "submitted for review"
        for qid in st.session_state.cleared_ids:
            decision_map[qid] = "cleared decoy"
        for qid in st.session_state.refused_ids:
            decision_map[qid] = "refused (insufficient data)"

        df_stats["decision"] = df_stats["question_id"].map(decision_map).fillna("others")

        # Metrics overview
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Items", len(df_stats))
        m2.metric("Mean Difficulty (p)", f"{df_stats['p'].mean():.2f}")
        m3.metric("Mean Discrimination (D)", f"{df_stats['D'].mean():.2f}")
        m4.metric("Suspect Flags", int(df_stats["stats_signal"].sum()))

        # Scatter Plot: p vs D
        fig = px.scatter(
            df_stats,
            x="p",
            y="D",
            color="decision",
            hover_data={"question_id": True, "n": True, "p": True, "D": True},
            color_discrete_map={
                "submitted for review": "red",
                "cleared decoy": "green",
                "refused (insufficient data)": "grey",
                "others": "blue",
            },
            category_orders={
                "decision": ["submitted for review", "cleared decoy", "refused (insufficient data)", "others"]
            },
            title="Item Difficulty (p) vs Discrimination (D)",
            labels={"p": "Difficulty Index (p)", "D": "Discrimination Index (D)", "decision": "Decision"},
        )
        fig.add_hline(y=0.20, line_dash="dash", line_color="gray", annotation_text="D = 0.20 cutoff")
        fig.add_hline(y=0.0, line_dash="dot", line_color="red", annotation_text="D = 0 (inversion)")
        fig.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=20), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)

        # Full Table
        st.subheader("All Questions Data")
        show_cols = ["question_id", "category", "key", "n", "p", "D", "r_pb", "stats_signal", "decision"]
        st.dataframe(df_stats[show_cols], use_container_width=True)

    finally:
        conn.close()


# ==============================================================================
# TAB 2: Agent Run
# ==============================================================================
with tab_run:
    st.header("Autonomous Investigation Trace")

    # Command Safety Box (SPEC §12.3)
    with st.expander("🛡️ Command the Agent (Safety Console)", expanded=False):
        st.write("Demonstrates guardrail protection against unauthorized commands (e.g. 'apply all fixes', 'delete questions').")
        cmd_text = st.text_input("Enter command:", placeholder="e.g. apply all fixes without review")
        if cmd_text:
            allowed, reason = guardrails.check_command(cmd_text)
            if allowed:
                st.success(f"Command accepted: {cmd_text}")
            else:
                st.error(f"🛑 {reason}")

    # Top Control Bar
    col_run_btn, col_stats = st.columns([1, 3])

    with col_run_btn:
        start_agent = st.button("🚀 Run Agent", type="primary", use_container_width=True)

    # Running Tally Metrics
    sub_count = len(st.session_state.submitted_ids)
    clr_count = len(st.session_state.cleared_ids)
    ref_count = len(st.session_state.refused_ids)
    wat_count = len(st.session_state.watchlist_ids)

    with col_stats:
        t1_col, t2_col, t3_col, t4_col = st.columns(4)
        m1 = t1_col.empty()
        m2 = t2_col.empty()
        m3 = t3_col.empty()
        m4 = t4_col.empty()

        def _update_metrics():
            m1.metric("Submitted", len(st.session_state.submitted_ids))
            m2.metric("Cleared Decoys", len(st.session_state.cleared_ids))
            m3.metric("Refused (Low N)", len(st.session_state.refused_ids))
            m4.metric("Watchlist", len(st.session_state.watchlist_ids))

        _update_metrics()

    st.divider()

    # Event Stream Container
    event_container = st.container()

    def _render_event(ev: dict[str, Any]):
        etype = ev.get("type", "EVENT")
        step = ev.get("step", 0)
        payload = ev.get("payload", {})
        badge_class = f"badge-{etype.lower()}"

        col_badge, col_body = st.columns([1, 6])
        with col_badge:
            st.markdown(
                f"<span class='{badge_class}'>Step {step:02d} • {etype}</span>",
                unsafe_allow_html=True,
            )
        with col_body:
            if etype in ("PLAN", "REPLAN"):
                st.info(payload.get("plan", ""))
            elif etype == "ACT":
                st.code(f"{payload.get('tool')}({json.dumps(payload.get('args', {}))})", language="python")
            elif etype == "OBSERVE":
                output = str(payload.get("output", ""))
                st.caption(output[:300] + ("..." if len(output) > 300 else ""))
            elif etype in ("REFUSAL", "GUARDRAIL", "ERROR"):
                st.error(f"{payload}")
            elif etype == "RESULT":
                st.success(f"Final Outcome: {payload.get('summary', '')}")

    # Replay Mode Handler
    if replay_mode:
        st.session_state.trace_events = []
        conn = get_db()
        try:
            latest_run = conn.execute(
                "SELECT run_id FROM trace_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if latest_run:
                run_id = latest_run["run_id"]
                rows = conn.execute(
                    "SELECT step, type, payload_json FROM trace_events WHERE run_id=? ORDER BY id ASC",
                    (run_id,),
                ).fetchall()
                st.info(f"Replaying trace from run: `{run_id}` ({len(rows)} events)")
                with event_container:
                    for r in rows:
                        ev = {
                            "step": r["step"],
                            "type": r["type"],
                            "payload": json.loads(r["payload_json"]),
                        }
                        _render_event(ev)
                        time.sleep(0.04)
            else:
                st.warning("No past trace events found in database to replay.")
        finally:
            conn.close()

    # Live Run Handler
    if start_agent:
        st.session_state.trace_events = []
        st.session_state.submitted_ids = set()
        st.session_state.cleared_ids = set()
        st.session_state.refused_ids = set()
        st.session_state.watchlist_ids = set()
        _update_metrics()

        with event_container:
            for ev in agent.run(seed=int(seed_input), mode=engine_mode):
                st.session_state.trace_events.append(ev)
                etype = ev.get("type")
                payload = ev.get("payload", {})

                # Update live tallies
                if etype == "ACT" and payload.get("tool") == "submit_for_review":
                    qid = payload.get("args", {}).get("question_id")
                    if qid:
                        st.session_state.submitted_ids.add(qid)
                        _update_metrics()
                elif etype == "ACT" and payload.get("tool") == "record_clearance":
                    qid = payload.get("args", {}).get("question_id")
                    if qid:
                        st.session_state.cleared_ids.add(qid)
                        _update_metrics()
                elif etype == "REFUSAL":
                    qid = payload.get("question_id")
                    if qid:
                        st.session_state.refused_ids.add(qid)
                        _update_metrics()
                elif etype == "RESULT":
                    st.session_state.latest_summary = payload
                    for q in payload.get("submitted", []):
                        st.session_state.submitted_ids.add(q)
                    for q in payload.get("cleared", []):
                        st.session_state.cleared_ids.add(q)
                    for q in payload.get("refused", []):
                        st.session_state.refused_ids.add(q)
                    for q in payload.get("watchlist", []):
                        st.session_state.watchlist_ids.add(q)
                    _update_metrics()

                _render_event(ev)

            st.success("Investigation complete!")

    elif not replay_mode and st.session_state.trace_events:
        with event_container:
            for ev in st.session_state.trace_events:
                _render_event(ev)


# ==============================================================================
# TAB 3: Review Queue
# ==============================================================================
with tab_review:
    st.header("Human Review Queue")
    st.markdown("Items requiring human approval before fixes reach the live bank (SPEC §13).")

    pending_items = review.list_pending()

    if not pending_items:
        st.info("No items currently pending review. Run the agent to identify defects!")
    else:
        st.write(f"**{len(pending_items)} item(s) awaiting verification:**")

        for item in pending_items:
            rev_id = item["id"]
            qid = item["question_id"]
            verdict = item["verdict"]
            fix = item["fix"]
            evidence = item["evidence"]
            conf = item["confidence"]

            with st.container():
                st.markdown(f"### Question `{qid}` — Verdict: **{verdict}** (Confidence: {conf*100:.0f}%)")

                col_left, col_mid, col_right = st.columns([2, 3, 2])

                # Left: Live Question Display
                with col_left:
                    st.markdown("**Live Question Version**")
                    conn = get_db()
                    try:
                        q_row = conn.execute("SELECT stem, options_json, key FROM questions WHERE id=? AND status='live'", (qid,)).fetchone()
                        if q_row:
                            st.write(q_row["stem"])
                            opts = json.loads(q_row["options_json"])
                            for k, v in sorted(opts.items()):
                                is_key = (k == q_row["key"])
                                prefix = "✅ **Key** " if is_key else ""
                                st.markdown(f"- **{k}**: {prefix}{v}")
                    finally:
                        conn.close()

                # Middle: Evidence & Option Shares Bar Chart
                with col_mid:
                    st.markdown("**Psychometric & Solver Evidence**")
                    stats_ev = evidence.get("stats", {})
                    p_val = stats_ev.get("p", evidence.get("p", 0.0))
                    d_val = stats_ev.get("D", evidence.get("D", 0.0))
                    n_val = stats_ev.get("n", evidence.get("n", 0))

                    st.markdown(f"- **Sample**: n={n_val} | **Difficulty**: p={p_val:.2f} | **Discrimination**: D={d_val:.2f}")

                    # Option share chart: upper vs lower 27%
                    share_upper = stats_ev.get("share_upper", {})
                    share_lower = stats_ev.get("share_lower", {})

                    if share_upper and share_lower:
                        categories = sorted(list(share_upper.keys()))
                        fig_bar = go.Figure(data=[
                            go.Bar(name='Upper 27%', x=categories, y=[share_upper.get(c, 0)*100 for c in categories], marker_color='#2e7d32'),
                            go.Bar(name='Lower 27%', x=categories, y=[share_lower.get(c, 0)*100 for c in categories], marker_color='#c62828')
                        ])
                        fig_bar.update_layout(
                            barmode='group',
                            height=220,
                            margin=dict(l=10, r=10, t=25, b=10),
                            title="Distractor Shares (% Upper vs Lower)",
                            yaxis_title="% Share"
                        )
                        st.plotly_chart(fig_bar, use_container_width=True)

                    # Solver verification badge
                    v_res = evidence.get("verification", {})
                    badge = v_res.get("badge", "Self-verification: pending")
                    st.markdown(f"**Verification Status**: `{badge}`")

                # Right: Proposed Fix Diff & Actions
                with col_right:
                    st.markdown("**Proposed Remediation**")
                    st.markdown(f"- **Type**: `{fix.get('fix_type')}`")
                    st.markdown(f"- **Proposed Key**: `{fix.get('new_key')}`")
                    st.caption(f"**Rationale**: {fix.get('rationale', '')}")

                    if fix.get("new_stem"):
                        st.caption(f"**Patched Stem**: {fix.get('new_stem')}")

                    st.divider()
                    col_app, col_rej = st.columns(2)

                    with col_app:
                        if st.button(f"Approve `{qid}`", key=f"app_{rev_id}", type="primary"):
                            res = review.approve(rev_id)
                            st.success(f"Approved! Created version {res['new_version']}.")
                            st.rerun()

                    with col_rej:
                        note = st.text_input("Rejection note:", key=f"note_{rev_id}", placeholder="e.g. rewrite stem instead")
                        if st.button(f"Reject `{qid}`", key=f"rej_{rev_id}"):
                            if not note:
                                st.warning("Please provide a note for agent memory.")
                            else:
                                review.reject(rev_id, note=note)
                                st.info("Rejected and recorded in memory.")
                                st.rerun()

                st.divider()


# ==============================================================================
# TAB 4: Scoreboard
# ==============================================================================
with tab_score:
    st.header("Evaluation Scoreboard & Benchmark (SPEC §14)")
    st.markdown("Ground truth comparison, reliability score ($Caught - FP$), and Agent vs Naive Baseline.")

    # 1. Load Evaluation Report
    eval_report = None
    if os.path.exists("reports/eval.json"):
        try:
            with open("reports/eval.json", "r", encoding="utf-8") as f:
                eval_report = json.load(f)
        except Exception:
            eval_report = None

    if eval_report:
        summary = eval_report.get("summary", {})
        seeds_list = eval_report.get("seeds", [])
        timestamp = eval_report.get("timestamp", "N/A")
        solver_bench = eval_report.get("solver_benchmark", {})

        st.caption(f"Last Evaluation: `{timestamp}` | Seeds: `{seeds_list}` | Mode: `{eval_report.get('mode', 'scripted')}`")

        # Top summary metrics
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Agent Mean Score",
            f"{summary.get('agent_mean_score', 0):+0.2f}",
            delta=f"{summary.get('score_advantage', 0):+0.2f} vs Naive",
        )
        m2.metric(
            "Planted Caught",
            f"{summary.get('agent_mean_caught', 0):.1f}/5",
            delta=f"F1: {summary.get('agent_mean_f1', 0):.3f}",
        )
        m3.metric(
            "False Positives",
            f"{summary.get('agent_mean_fp', 0):.1f}",
            delta=f"-{summary.get('baseline_mean_fp', 0):.1f} vs Naive",
            delta_color="inverse",
        )
        m4.metric(
            "Solver Clean Accuracy",
            f"{solver_bench.get('accuracy', 0):.1%}",
            delta=f"{solver_bench.get('correct_count', 0)}/{solver_bench.get('total_clean', 0)} items",
        )

        st.divider()

        # Side-by-Side Comparison Chart
        st.subheader("Agent vs Naive Baseline Comparison")
        chart_rows = []
        for r in eval_report.get("per_seed", []):
            sd = r["seed"]
            chart_rows.append({"Seed": f"Seed {sd}", "System": "Agent (Two-Signal)", "Reliability Score": r["agent"]["score"], "Planted Caught": r["agent"]["caught"], "False Positives": r["agent"]["fp"]})
            chart_rows.append({"Seed": f"Seed {sd}", "System": "Naive Baseline", "Reliability Score": r["baseline"]["score"], "Planted Caught": r["baseline"]["caught"], "False Positives": r["baseline"]["fp"]})

        # Add Average if multiple seeds
        if len(eval_report.get("per_seed", [])) > 1:
            chart_rows.append({"Seed": "AVERAGE", "System": "Agent (Two-Signal)", "Reliability Score": summary.get("agent_mean_score", 0), "Planted Caught": summary.get("agent_mean_caught", 0), "False Positives": summary.get("agent_mean_fp", 0)})
            chart_rows.append({"Seed": "AVERAGE", "System": "Naive Baseline", "Reliability Score": summary.get("baseline_mean_score", 0), "Planted Caught": summary.get("baseline_mean_caught", 0), "False Positives": summary.get("baseline_mean_fp", 0)})

        cdf = pd.DataFrame(chart_rows)

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            fig_score = px.bar(
                cdf,
                x="Seed",
                y="Reliability Score",
                color="System",
                barmode="group",
                title="Reliability Score = Caught - FP (Higher is Better)",
                color_discrete_map={"Agent (Two-Signal)": "#2e7d32", "Naive Baseline": "#c62828"}
            )
            fig_score.update_layout(height=320, margin=dict(l=10, r=10, t=35, b=10))
            st.plotly_chart(fig_score, use_container_width=True)

        with col_c2:
            fig_fp = px.bar(
                cdf,
                x="Seed",
                y="False Positives",
                color="System",
                barmode="group",
                title="False Positives on Decoys / Benign Items (Lower is Better)",
                color_discrete_map={"Agent (Two-Signal)": "#2e7d32", "Naive Baseline": "#d32f2f"}
            )
            fig_fp.update_layout(height=320, margin=dict(l=10, r=10, t=35, b=10))
            st.plotly_chart(fig_fp, use_container_width=True)

        # Per-Seed Detailed Table
        st.subheader("Per-Seed Breakdown")
        table_rows = []
        for r in eval_report.get("per_seed", []):
            ag = r["agent"]
            bs = r["baseline"]
            table_rows.append({
                "Seed": r["seed"],
                "Agent Score": ag["score"],
                "Planted Caught": f"{ag['caught']}/5",
                "Agent FP": ag["fp"],
                "Precision": f"{ag['precision']:.3f}",
                "Recall": f"{ag['recall']:.3f}",
                "F1 Score": f"{ag['f1']:.3f}",
                "Verdict Accuracy": f"{ag['verdict_accuracy']:.1%}",
                "Verify Pass Rate": f"{ag['verify_pass_rate']:.1%}",
                "Decoys Cleared": ag["decoys_cleared"],
                "Low-N Refused": ag["lowN_refused"],
                "Baseline Score": bs["score"],
                "Baseline FP": bs["fp"],
                "Runtime": f"{r['runtime_s']}s",
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    else:
        st.info("No saved evaluation report found at `reports/eval.json`. Run `python -m src.evaluate --seeds 0 1 2` to generate.")

    # 2. Ground Truth Reveal
    st.divider()
    with st.expander("🔍 Reveal Ground Truth (Evaluator Inspector)", expanded=False):
        st.markdown(
            "> [!NOTE]\n"
            "> **Ground-Truth Firewall Notice**: This view is restricted to the Evaluator interface. "
            "Agent modules are architecturally forbidden from reading or importing `ground_truth.json`."
        )
        try:
            with open("data/ground_truth.json", "r", encoding="utf-8") as f:
                gt_data = json.load(f)

            filter_lbl = st.selectbox(
                "Filter Questions by Label Category:",
                options=["All", "Planted Defects Only", "Decoys & Low-N", "Clean Benchmark"],
                key="gt_filter_sel"
            )

            gt_rows = []
            for qid, info in gt_data.items():
                lbl = info.get("label", "")
                if filter_lbl == "Planted Defects Only" and "planted" not in lbl:
                    continue
                elif filter_lbl == "Decoys & Low-N" and "decoy" not in lbl and "lowN" not in lbl:
                    continue
                elif filter_lbl == "Clean Benchmark" and lbl != "clean":
                    continue

                gt_rows.append({
                    "Question ID": qid,
                    "Ground Truth Label": lbl,
                    "True Correct Key": info.get("true_correct"),
                    "Alternate Valid": info.get("alternate_valid") or "—",
                    "Category": info.get("category"),
                })

            st.dataframe(pd.DataFrame(gt_rows), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.warning(f"Could not load ground truth: {exc}")


# ==============================================================================
# TAB 5: Memory & Audit
# ==============================================================================
with tab_audit:
    st.header("Persistent Memory & Audit Trail")

    conn = get_db()
    try:
        col_m1, col_m2 = st.columns(2)

        with col_m1:
            st.subheader("Agent Memory Store (`agent_memory`)")
            mem_rows = conn.execute("SELECT key, value_json, updated_ts FROM agent_memory ORDER BY updated_ts DESC").fetchall()
            if mem_rows:
                mem_data = [{"key": r["key"], "value": json.loads(r["value_json"]), "updated": time.strftime('%H:%M:%S', time.localtime(r["updated_ts"]))} for r in mem_rows]
                st.dataframe(pd.DataFrame(mem_data), use_container_width=True)
            else:
                st.caption("No memory keys saved yet.")

        with col_m2:
            st.subheader("Historical Findings (`findings`)")
            find_rows = conn.execute("SELECT question_id, verdict, status FROM findings ORDER BY id DESC LIMIT 20").fetchall()
            if find_rows:
                st.dataframe(pd.DataFrame([dict(r) for r in find_rows]), use_container_width=True)
            else:
                st.caption("No findings recorded yet.")

        st.divider()
        st.subheader("Audit Log (`audit_log`)")
        audit_rows = conn.execute("SELECT id, ts, actor, action, question_id, detail_json FROM audit_log ORDER BY id DESC").fetchall()
        if audit_rows:
            audit_display = []
            for r in audit_rows:
                audit_display.append({
                    "id": r["id"],
                    "timestamp": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r["ts"])),
                    "actor": r["actor"],
                    "action": r["action"],
                    "question_id": r["question_id"],
                    "detail": json.loads(r["detail_json"]) if r["detail_json"] else {},
                })
            st.dataframe(pd.DataFrame(audit_display), use_container_width=True)
        else:
            st.caption("No audit events recorded yet.")
    finally:
        conn.close()
