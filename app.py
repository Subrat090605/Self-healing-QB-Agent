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

        # Color-coded status based on session findings
        def _get_status(qid):
            if qid in st.session_state.submitted_ids:
                return "Submitted to Review"
            if qid in st.session_state.cleared_ids:
                return "Cleared Decoy"
            if qid in st.session_state.refused_ids:
                return "Refused (Low N)"
            if qid in st.session_state.watchlist_ids:
                return "Watchlist"
            return "Live / Healthy"

        df_stats["status"] = df_stats["question_id"].apply(_get_status)

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
            color="status",
            hover_data=["question_id", "key", "n", "r_pb", "category"],
            color_discrete_map={
                "Submitted to Review": "#d32f2f",
                "Cleared Decoy": "#388e3c",
                "Refused (Low N)": "#7b1fa2",
                "Watchlist": "#f57c00",
                "Live / Healthy": "#1976d2",
            },
            title="Item Difficulty (p) vs Discrimination (D)",
            labels={"p": "Difficulty Index (p)", "D": "Discrimination Index (D)"},
        )
        fig.add_hline(y=0.20, line_dash="dash", line_color="gray", annotation_text="D = 0.20 cutoff")
        fig.add_hline(y=0.0, line_dash="dot", line_color="red", annotation_text="D = 0 (inversion)")
        fig.update_layout(height=450, margin=dict(l=20, r=20, t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

        # Full Table
        st.subheader("All Questions Data")
        show_cols = ["question_id", "category", "key", "n", "p", "D", "r_pb", "stats_signal", "status"]
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
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Submitted", sub_count)
        t2.metric("Cleared Decoys", clr_count)
        t3.metric("Refused (Low N)", ref_count)
        t4.metric("Watchlist", wat_count)

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

        progress_text = st.empty()
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
                elif etype == "ACT" and payload.get("tool") == "record_clearance":
                    qid = payload.get("args", {}).get("question_id")
                    if qid:
                        st.session_state.cleared_ids.add(qid)
                elif etype == "REFUSAL":
                    qid = payload.get("question_id")
                    if qid:
                        st.session_state.refused_ids.add(qid)
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

                _render_event(ev)

        st.success("Investigation complete!")
        st.rerun()

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
    st.header("Evaluation Scoreboard")
    st.markdown("Ground truth comparison and agent vs baseline benchmark.")

    col_eval_btn, col_eval_disp = st.columns([1, 4])
    with col_eval_btn:
        run_eval_btn = st.button("Evaluate Seed 0", use_container_width=True)

    # Ground truth reveal
    with st.expander("🔍 Reveal Ground Truth (Evaluator View)"):
        st.write("Reads `data/ground_truth.json` for benchmarking purposes only.")
        try:
            with open("data/ground_truth.json", "r") as f:
                gt_data = json.load(f)
            gt_df = pd.DataFrame([
                {"id": k, "label": v["label"], "true_correct": v["true_correct"]}
                for k, v in gt_data.items()
            ])
            st.dataframe(gt_df, use_container_width=True)
        except Exception as exc:
            st.warning(f"Ground truth not found: {exc}")

    # Load eval report if available
    try:
        with open("reports/eval.json", "r") as f:
            eval_report = json.load(f)
        st.subheader("Summary Benchmark")
        st.json(eval_report)
    except Exception:
        # Compute live evaluation on seed 0 if requested
        if run_eval_btn:
            with st.spinner("Computing evaluation metrics..."):
                conn = get_db()
                try:
                    with open("data/ground_truth.json", "r") as f:
                        gt = json.load(f)
                    planted = {k for k, v in gt.items() if "planted" in v["label"]}
                    decoys = {k for k, v in gt.items() if "decoy" in v["label"]}

                    # Submitted items
                    sub_rows = conn.execute("SELECT question_id FROM review_queue").fetchall()
                    flagged = {r["question_id"] for r in sub_rows}

                    caught = len(flagged & planted)
                    fp = len(flagged - planted)
                    score = caught - fp

                    st.markdown("### Performance Metrics")
                    e1, e2, e3 = st.columns(3)
                    e1.metric("Planted Caught", f"{caught}/5")
                    e2.metric("False Positives", fp)
                    e3.metric("Reliability Score", score)

                    # Comparison Chart: Agent vs Naive Baseline
                    # Compute naive baseline
                    df_stats = stats.compute_item_stats(conn=conn)
                    naive_flagged = set(df_stats[df_stats["naive_signal"]]["question_id"])
                    naive_caught = len(naive_flagged & planted)
                    naive_fp = len(naive_flagged - planted)

                    chart_df = pd.DataFrame([
                        {"Method": "Agent (Two-Signal)", "Planted Caught": caught, "False Positives": fp},
                        {"Method": "Naive (Single-Signal)", "Planted Caught": naive_caught, "False Positives": naive_fp},
                    ])

                    fig_cmp = px.bar(
                        chart_df,
                        x="Method",
                        y=["Planted Caught", "False Positives"],
                        barmode="group",
                        title="Agent vs Naive Baseline Comparison",
                        color_discrete_map={"Planted Caught": "#2e7d32", "False Positives": "#c62828"}
                    )
                    st.plotly_chart(fig_cmp, use_container_width=True)
                finally:
                    conn.close()


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
