"""stats.py — Item analysis using pandas/numpy/scipy only (no LLM).

Implements SPEC §6:
- compute_item_stats(conn, question_ids) -> DataFrame
- get_suspects(df, rule) -> list[str] of ranked question IDs
- analyze_distractors(question_id, conn, stats_df) -> dict
"""

import sqlite3
from typing import Any, Optional

import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from src import db
from src.config import DB_PATH


def compute_item_stats(
    conn: Optional[sqlite3.Connection] = None,
    question_ids: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Compute item statistics and signals for questions.

    Recomputes correctness on the fly from attempts.chosen vs questions.key (live key).
    Never trusts attempts.correct directly (SPEC §4, §6).
    """
    close_conn = False
    if conn is None:
        conn = db.get_conn(DB_PATH)
        close_conn = True

    try:
        # 1. Fetch current live questions
        q_sql = "SELECT id, key, category FROM questions WHERE status='live'"
        if question_ids:
            ph = ",".join("?" for _ in question_ids)
            q_sql += f" AND id IN ({ph})"
            q_df = pd.read_sql_query(q_sql, conn, params=tuple(question_ids))
        else:
            q_df = pd.read_sql_query(q_sql, conn)

        if q_df.empty:
            return pd.DataFrame()

        # 2. Fetch all attempts and join live question keys
        att_df = pd.read_sql_query("SELECT student_id, question_id, chosen FROM attempts", conn)
        if att_df.empty:
            return pd.DataFrame()

        all_q_df = pd.read_sql_query("SELECT id, key FROM questions WHERE status='live'", conn)
        att_df = att_df.merge(all_q_df, left_on="question_id", right_on="id", how="inner")
        att_df["is_correct"] = (att_df["chosen"] == att_df["key"]).astype(int)

        # 3. Student totals & rest_pct = (total_correct - this_item) / (attempted - 1)
        st_totals = att_df.groupby("student_id")["is_correct"].agg(
            total_correct="sum", total_attempted="count"
        ).reset_index()
        att_df = att_df.merge(st_totals, on="student_id", how="left")
        att_df["rest_pct"] = np.where(
            att_df["total_attempted"] > 1,
            (att_df["total_correct"] - att_df["is_correct"]) / (att_df["total_attempted"] - 1),
            0.0,
        )

        target_att = att_df[att_df["question_id"].isin(set(q_df["id"]))]
        records: list[dict[str, Any]] = []

        for q_row in q_df.itertuples(index=False):
            qid, live_key, cat = q_row.id, q_row.key, q_row.category
            grp = target_att[target_att["question_id"] == qid]
            n = len(grp)

            if n == 0:
                records.append({
                    "question_id": qid, "category": cat, "key": live_key,
                    "n": 0, "p": 0.0, "r_pb": 0.0, "D": 0.0,
                    "share_all": {o: 0.0 for o in "ABCD"},
                    "share_upper": {o: 0.0 for o in "ABCD"},
                    "share_lower": {o: 0.0 for o in "ABCD"},
                    "neg_disc": False, "low_disc": True, "key_inversion": False,
                    "split_top": False, "weak_key_upper": True, "ceiling": False,
                    "floor": True, "too_hard_naive": True, "too_easy_naive": False,
                    "insufficient": True, "stats_signal": False, "naive_signal": True,
                })
                continue

            p = float(grp["is_correct"].mean())

            # Point-biserial correlation r_pb
            if grp["is_correct"].std() > 0 and grp["rest_pct"].std() > 0 and n > 2:
                r_val, _ = pearsonr(grp["is_correct"], grp["rest_pct"])
                r_pb = float(r_val) if not np.isnan(r_val) else 0.0
            else:
                r_pb = 0.0

            # Discrimination index D via upper and lower 27% by rest_pct
            sorted_g = grp.sort_values("rest_pct")
            k = max(1, int(round(0.27 * n)))
            lower_g, upper_g = sorted_g.iloc[:k], sorted_g.iloc[-k:]
            D = float(upper_g["is_correct"].mean() - lower_g["is_correct"].mean())

            # Option shares
            su = {o: float((upper_g["chosen"] == o).mean()) for o in "ABCD"}
            sl = {o: float((lower_g["chosen"] == o).mean()) for o in "ABCD"}
            sa = {o: float((grp["chosen"] == o).mean()) for o in "ABCD"}

            # Signals per SPEC §6
            neg_disc = bool(D < 0.0 or r_pb < 0.0)
            low_disc = bool(D < 0.15 or r_pb < 0.10)
            key_upper = su.get(live_key, 0.0)
            key_inversion = any(su[o] > key_upper for o in "ABCD" if o != live_key)
            split_top = sum(1 for o in "ABCD" if su[o] >= 0.25) >= 2
            weak_key_upper = bool(key_upper < 0.50)
            ceiling, floor = bool(p > 0.90), bool(p < 0.20)
            too_hard_naive, too_easy_naive = bool(p < 0.35), bool(p > 0.90)
            insufficient = bool(n < 30)

            stats_signal = bool(neg_disc or key_inversion or split_top or (low_disc and not ceiling and not floor))
            naive_signal = bool(neg_disc or low_disc or too_hard_naive or too_easy_naive)

            records.append({
                "question_id": qid, "category": cat, "key": live_key,
                "n": n, "p": round(p, 4), "r_pb": round(r_pb, 4), "D": round(D, 4),
                "share_all": sa, "share_upper": su, "share_lower": sl,
                "neg_disc": neg_disc, "low_disc": low_disc, "key_inversion": key_inversion,
                "split_top": split_top, "weak_key_upper": weak_key_upper,
                "ceiling": ceiling, "floor": floor,
                "too_hard_naive": too_hard_naive, "too_easy_naive": too_easy_naive,
                "insufficient": insufficient,
                "stats_signal": stats_signal, "naive_signal": naive_signal,
            })

        return pd.DataFrame(records)
    finally:
        if close_conn:
            conn.close()


def get_suspects(
    df: Optional[pd.DataFrame] = None,
    rule: str = "agent",
    max_suspects: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> list[str]:
    """Return ranked suspect question IDs sorted by risk (lowest/negative D first)."""
    if df is None:
        df = compute_item_stats(conn=conn)
    if df.empty:
        return []

    if rule == "agent":
        suspects_df = df[df["stats_signal"] | df["insufficient"]].copy()
    elif rule == "naive":
        suspects_df = df[df["naive_signal"]].copy()
    else:
        suspects_df = df[df["stats_signal"]].copy()

    if suspects_df.empty:
        return []

    suspects_df = suspects_df.sort_values(by=["D", "r_pb"], ascending=[True, True])
    ids = suspects_df["question_id"].tolist()
    return ids[:max_suspects] if max_suspects else ids


def analyze_distractors(
    question_id: str,
    conn: Optional[sqlite3.Connection] = None,
    stats_df: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    """Return option shares and one-line anomaly text for question evidence cards."""
    if stats_df is None or question_id not in stats_df["question_id"].values:
        stats_df = compute_item_stats(conn=conn, question_ids=[question_id])

    matches = stats_df[stats_df["question_id"] == question_id]
    if matches.empty:
        return {
            "question_id": question_id, "key": "", "n": 0, "p": 0.0, "D": 0.0,
            "share_all": {}, "share_upper": {}, "share_lower": {},
            "anomaly": f"Question {question_id} not found.",
        }

    row = matches.iloc[0]
    live_key, n, p, D, r_pb = str(row["key"]), int(row["n"]), float(row["p"]), float(row["D"]), float(row["r_pb"])
    su, sl, sa = dict(row["share_upper"]), dict(row["share_lower"]), dict(row["share_all"])

    if row["insufficient"]:
        anomaly = f"Insufficient data: only {n} attempts recorded (n < 30 required)."
    elif row["key_inversion"]:
        non_keys = [o for o in "ABCD" if o != live_key]
        best_non_key = max(non_keys, key=lambda o: su.get(o, 0.0))
        anomaly = (
            f"Key inversion: Top students preferred Option {best_non_key} ({su.get(best_non_key, 0.0):.1%}) "
            f"over stored key {live_key} ({su.get(live_key, 0.0):.1%}) (D={D:.2f})."
        )
    elif row["split_top"]:
        top_opts = [o for o in "ABCD" if su.get(o, 0.0) >= 0.25]
        s_str = ", ".join(f"{o}: {su.get(o, 0.0):.1%}" for o in top_opts)
        anomaly = f"Split top: Upper students split across multiple options ({s_str}); suggests ambiguity."
    elif row["neg_disc"]:
        anomaly = f"Negative discrimination: D={D:.2f}, r_pb={r_pb:.2f}. Weaker students pick key more than upper students."
    elif row["low_disc"] and not row["ceiling"] and not row["floor"]:
        anomaly = f"Non-discriminating item: D={D:.2f}, r_pb={r_pb:.2f} despite mid difficulty p={p:.2f}."
    elif row["ceiling"]:
        anomaly = f"Ceiling effect: p={p:.2f} > 0.90 explains low discrimination D={D:.2f}; valid easy item."
    elif row["floor"]:
        anomaly = f"Floor effect: p={p:.2f} < 0.20 explains low discrimination D={D:.2f}; valid hard item."
    else:
        anomaly = f"Healthy discrimination: key {live_key} leads upper students ({su.get(live_key, 0.0):.1%}) with D={D:.2f}."

    return {
        "question_id": question_id, "key": live_key, "n": n, "p": p, "D": D, "r_pb": r_pb,
        "share_all": sa, "share_upper": su, "share_lower": sl, "anomaly": anomaly,
    }


def main() -> None:
    """Run item analysis on current database, print ranked suspects and decoy comparison."""
    print("=" * 72)
    print("ITEM ANALYSIS & SUSPECT TRIAGE (SPEC §6)")
    print("=" * 72)

    df = compute_item_stats()
    if df.empty:
        print("No attempts data found. Run 'python -m src.seed.build' first.")
        return

    agent_suspects = get_suspects(df, rule="agent")
    naive_suspects = get_suspects(df, rule="naive")

    print(f"\nTotal Items Evaluated: {len(df)}")
    print(f"Agent Suspects (stats_signal or insufficient) : {len(agent_suspects)}")
    print(f"Naive Suspects (naive_signal)                 : {len(naive_suspects)}")

    print("\n" + "-" * 72)
    print("RANKED AGENT SUSPECTS (Risk Priority Order):")
    print("-" * 72)
    print(f"{'Rank':<5} {'ID':<7} {'Cat':<9} {'Key':<5} {'N':<6} {'p':<7} {'D':<8} {'r_pb':<8} {'Primary Anomaly'}")
    print("-" * 72)

    for rank, qid in enumerate(agent_suspects, start=1):
        row = df[df["question_id"] == qid].iloc[0]
        dist_info = analyze_distractors(qid, stats_df=df)
        anomaly_short = dist_info["anomaly"].split(":")[0] if ":" in dist_info["anomaly"] else dist_info["anomaly"][:35]
        print(
            f"{rank:<5} {qid:<7} {row['category']:<9} {row['key']:<5} {row['n']:<6} "
            f"{row['p']:<7.3f} {row['D']:<8.3f} {row['r_pb']:<8.3f} {anomaly_short}"
        )

    decoy_ids = {"Q025", "Q030", "Q047", "Q050", "Q053"}
    flagged_decoys = [qid for qid in naive_suspects if qid in decoy_ids]
    planted_ids = {"Q005", "Q012", "Q038", "Q042", "Q045"}
    planted_in_top12 = [qid for qid in agent_suspects[:12] if qid in planted_ids]

    print("\n" + "=" * 72)
    print("ACCEPTANCE CHECK:")
    print("=" * 72)
    print(f"Planted items in Agent Top 12 : {len(planted_in_top12)}/5 -> {sorted(planted_in_top12)}")
    print(f"Decoys flagged by NAIVE rule  : {len(flagged_decoys)}/5 -> {sorted(flagged_decoys)}")
    for d_id in sorted(flagged_decoys):
        d_row = df[df["question_id"] == d_id].iloc[0]
        reasons = []
        if d_row["too_hard_naive"]:
            reasons.append("too_hard (p<0.35)")
        if d_row["too_easy_naive"]:
            reasons.append("too_easy (p>0.90)")
        if d_row["low_disc"]:
            reasons.append("low_disc (D<0.15)")
        print(f"   * {d_id}: p={d_row['p']:.3f}, D={d_row['D']:.3f} -> flagged for {', '.join(reasons)}")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
