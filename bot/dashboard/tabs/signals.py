"""
Signal Recall & Evaluation Audit Tab for Piploci Monitoring Dashboard.
Provides 100% recall of all evaluated trading opportunities, gate rejections, and execution rationale.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict, Any


def render_signals_tab(audits: List[Dict[str, Any]]):
    """Renders the Signal Recall & Audit log tab."""
    st.markdown('<div style="font-family: \'Inter\', sans-serif; font-size: 0.85rem; font-weight: 700; color: #F1F5F9; margin-bottom: 8px;">Signal Recall & Evaluation Audit Log</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size: 0.72rem; color: #94A3B8; margin-bottom: 14px;">Complete transparency and audit trail of every evaluated market opportunity, gate outcome, and rejection rationale.</div>', unsafe_allow_html=True)

    if not audits:
        st.info("No signal evaluations recorded yet. The engine will record every evaluation cycle once active.")
        return

    # 1. Summary Metrics
    total_evals = len(audits)
    executed = sum(1 for a in audits if a.get("status") == "EXECUTED")
    wick_rejections = sum(1 for a in audits if "WICK" in str(a.get("status", "")))
    news_rejections = sum(1 for a in audits if "NEWS" in str(a.get("status", "")))
    session_rejections = sum(1 for a in audits if "SESSION" in str(a.get("status", "")))
    spread_rejections = sum(1 for a in audits if "SPREAD" in str(a.get("status", "")))

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Total Evaluations", total_evals)
    with col2:
        st.metric("Executed", executed, delta=f"{executed / total_evals * 100:.1f}%" if total_evals else None)
    with col3:
        st.metric("Wick Filtered", wick_rejections)
    with col4:
        st.metric("News Shielded", news_rejections)
    with col5:
        st.metric("Off-Session", session_rejections)
    with col6:
        st.metric("Spread Blocked", spread_rejections)

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # 2. Filter Controls
    fcol1, fcol2 = st.columns([1, 2])
    with fcol1:
        symbols = ["ALL"] + sorted(list({a.get("symbol") for a in audits if a.get("symbol")}))
        sel_sym = st.selectbox("Filter Symbol", symbols, index=0, key="audit_sym_filter")
    with fcol2:
        statuses = ["ALL"] + sorted(list({a.get("status") for a in audits if a.get("status")}))
        sel_stat = st.selectbox("Filter Status", statuses, index=0, key="audit_stat_filter")

    filtered = audits
    if sel_sym != "ALL":
        filtered = [a for a in filtered if a.get("symbol") == sel_sym]
    if sel_stat != "ALL":
        filtered = [a for a in filtered if a.get("status") == sel_stat]

    if not filtered:
        st.warning("No audit records match the selected filters.")
        return

    df = pd.DataFrame(filtered)
    columns_order = [
        "timestamp", "symbol", "direction", "status",
        "m15_consensus", "h1_consensus", "wick_ratio", "spread", "reason"
    ]
    avail_cols = [c for c in columns_order if c in df.columns]

    st.dataframe(
        df[avail_cols],
        use_container_width=True,
        hide_index=True,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Timestamp (UTC)", format="YYYY-MM-DD HH:mm:ss"),
            "symbol": st.column_config.TextColumn("Symbol"),
            "direction": st.column_config.TextColumn("Direction"),
            "status": st.column_config.TextColumn("Gate Status"),
            "m15_consensus": st.column_config.TextColumn("M15 TA"),
            "h1_consensus": st.column_config.TextColumn("H1 TA"),
            "wick_ratio": st.column_config.NumberColumn("Wick Ratio", format="%.3f"),
            "spread": st.column_config.NumberColumn("Spread (pts)", format="%.1f"),
            "reason": st.column_config.TextColumn("Evaluation Rationale"),
        }
    )
