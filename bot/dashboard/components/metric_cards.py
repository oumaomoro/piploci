"""
Metric Cards Component for Piploci Monitoring Dashboard.
Renders high-level account performance metrics: Equity, Balance, Floating PnL, Drawdown.
"""

import streamlit as st
from typing import Dict, Any, Optional


def render_metric_cards(status_data: Optional[Dict[str, Any]]):
    """Renders the top 4 core metric cards."""
    if not status_data:
        balance = 1000.0
        equity = 1000.0
        floating_pnl = 0.0
        drawdown = 0.0
        starting_bal = 1000.0
    else:
        balance = status_data.get("balance", 1000.0)
        equity = status_data.get("equity", 1000.0)
        floating_pnl = status_data.get("floating_pnl", 0.0)
        drawdown = status_data.get("current_drawdown", 0.0)
        starting_bal = status_data.get("starting_daily_balance", 1000.0)

    pnl_class = "mc-positive" if floating_pnl > 0 else ("mc-negative" if floating_pnl < 0 else "mc-neutral")
    pnl_sign = "+" if floating_pnl > 0 else ""
    pnl_pct = (floating_pnl / balance * 100) if balance > 0 else 0.0

    dd_limit = status_data.get("daily_drawdown_limit", 4.50) if status_data else 4.50
    dd_pct = (drawdown / dd_limit * 100) if dd_limit > 0 else 0.0
    dd_class = "mc-negative" if drawdown > 2.25 else ("mc-positive" if drawdown == 0 else "mc-neutral")

    cols = st.columns(4)

    with cols[0]:
        st.markdown(f"""
        <div class="metric-card">
            <div class="mc-label">Account Equity</div>
            <div class="mc-value">${equity:,.2f}</div>
            <div class="mc-sub">Live MT5 Portfolio</div>
        </div>
        """, unsafe_allow_html=True)

    with cols[1]:
        st.markdown(f"""
        <div class="metric-card">
            <div class="mc-label">Balance</div>
            <div class="mc-value">${balance:,.2f}</div>
            <div class="mc-sub">Base: ${starting_bal:,.2f}</div>
        </div>
        """, unsafe_allow_html=True)

    with cols[2]:
        st.markdown(f"""
        <div class="metric-card">
            <div class="mc-label">Floating P&L</div>
            <div class="mc-value {pnl_class}">{pnl_sign}${floating_pnl:,.2f}</div>
            <div class="mc-sub {pnl_class}">{pnl_sign}{pnl_pct:.2f}% Floating</div>
        </div>
        """, unsafe_allow_html=True)

    with cols[3]:
        st.markdown(f"""
        <div class="metric-card">
            <div class="mc-label">Daily Drawdown</div>
            <div class="mc-value {dd_class}">${drawdown:,.2f}</div>
            <div class="mc-sub">Limit: ${dd_limit:,.2f} ({dd_pct:.1f}%)</div>
        </div>
        """, unsafe_allow_html=True)
