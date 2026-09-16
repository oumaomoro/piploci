"""
Performance Telemetry Tab for Piploci Monitoring Dashboard.
Renders win rate, profit factor, Sharpe ratio proxy, and cumulative PnL progression.
"""

import streamlit as st
import pandas as pd
from typing import Dict, Any, List


def render_performance_tab(perf_data: Dict[str, Any], trades: List[Dict[str, Any]]):
    """Renders the Performance & Analytics tab."""
    total_trades = perf_data.get("total_trades", 0)
    win_rate = perf_data.get("win_rate_pct", 0.0)
    profit_factor = perf_data.get("profit_factor", 0.0)
    sharpe = perf_data.get("sharpe_proxy", 0.0)

    # 4 metrics row
    m_cols = st.columns(4)
    with m_cols[0]:
        st.metric("Total Executions", f"{total_trades}")
    with m_cols[1]:
        st.metric("Win Rate", f"{win_rate:.1f}%")
    with m_cols[2]:
        st.metric("Profit Factor", f"{profit_factor:.2f}")
    with m_cols[3]:
        st.metric("Sharpe Proxy", f"{sharpe:.2f}")

    st.markdown("---")

    # Cumulative PnL chart
    if trades:
        closed = [t for t in reversed(trades) if t.get("status") == "CLOSED"]
        if closed:
            df = pd.DataFrame(closed)
            df["pnl"] = df["pnl"].fillna(0.0)
            df["cumulative_pnl"] = df["pnl"].cumsum()
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            
            st.markdown("**Cumulative Realized P&L Curve ($ USD)**")
            st.line_chart(df.set_index("timestamp")["cumulative_pnl"], color="#06B6D4")
        else:
            st.info("No closed trades available for cumulative PnL plotting.")
    else:
        st.info("Performance charts will populate as trade executions complete.")
