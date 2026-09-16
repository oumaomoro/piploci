"""
Risk Gauge Component for Piploci Monitoring Dashboard.
Visualizes daily drawdown allowance consumption against the $4.50 circuit breaker threshold.
"""

import streamlit as st
from typing import Dict, Any, Optional


def render_risk_gauge(status_data: Optional[Dict[str, Any]]):
    """Renders the horizontal risk budget gauge bar."""
    drawdown = status_data.get("current_drawdown", 0.0) if status_data else 0.0
    limit = status_data.get("daily_drawdown_limit", 4.50) if status_data else 4.50
    pct = min(100.0, max(0.0, (drawdown / limit) * 100.0)) if limit > 0 else 0.0

    if pct >= 80:
        bar_color = "linear-gradient(90deg, #F59E0B, #EF4444)"
        status_text = "CRITICAL EXPOSURE"
        status_class = "b-red"
    elif pct >= 50:
        bar_color = "linear-gradient(90deg, #10B981, #F59E0B)"
        status_text = "ELEVATED RISK"
        status_class = "b-amber"
    else:
        bar_color = "linear-gradient(90deg, #06B6D4, #10B981)"
        status_text = "HEALTHY"
        status_class = "b-green"

    html = f"""
    <div class="risk-panel">
        <div class="risk-header">
            <span class="risk-title">Daily Drawdown Circuit Breaker</span>
            <div style="display: flex; align-items: center; gap: 8px;">
                <span class="badge {status_class}"><span class="badge-dot"></span>{status_text}</span>
                <span class="risk-reading">${drawdown:.2f} / ${limit:.2f} ({pct:.1f}%)</span>
            </div>
        </div>
        <div class="risk-bar-bg">
            <div class="risk-bar-fill" style="width: {pct:.1f}%; background: {bar_color};"></div>
        </div>
        <div class="risk-tiers">
            <span class="risk-tier-label">$0.00 Base</span>
            <span class="risk-tier-label">$2.25 (50% Override)</span>
            <span class="risk-tier-label">$4.50 (24h Halt)</span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
