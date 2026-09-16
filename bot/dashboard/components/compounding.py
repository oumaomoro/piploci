"""
Compounding and Tiered Lot-Scaling Panel for Piploci Monitoring Dashboard.
Displays House-Money compounding tiers, safety cushion, and milestone progress.
"""

import streamlit as st
from typing import Dict, Any, Optional


def render_compounding_panel(status_data: Optional[Dict[str, Any]]):
    """Renders the House-Money Dynamic Compounding Tier panel."""
    tier_info = status_data.get("compounding_tier", {}) if status_data else {}
    if not tier_info:
        tier = 0
        tier_name = "TIER 0 - BASE"
        net_profit_pct = 0.0
        safety_cushion_usd = 0.0
        effective_risk_pct = 1.0
        lot_multiplier = 1.0
        drawdown_override = False
        progress = 0.0
        next_milestone_pct = 15.0
        reason = "Awaiting live telemetry"
    else:
        tier = tier_info.get("tier", 0)
        tier_name = tier_info.get("tier_name", "TIER 0 - BASE")
        net_profit_pct = tier_info.get("net_profit_pct", 0.0)
        safety_cushion_usd = tier_info.get("safety_cushion_usd", 0.0)
        effective_risk_pct = tier_info.get("effective_risk_pct", 1.0)
        lot_multiplier = tier_info.get("lot_multiplier", 1.0)
        drawdown_override = tier_info.get("drawdown_override_active", False)
        progress = tier_info.get("progress_to_next_milestone", 0.0)
        next_milestone_pct = tier_info.get("next_milestone_pct", 15.0)
        reason = tier_info.get("reason", "")

    # Choose badge style
    if drawdown_override:
        pill_html = '<span class="badge b-red"><span class="badge-dot"></span>SAFETY OVERRIDE ACTIVE</span>'
        bar_fill_color = "#EF4444"
    elif tier == 2:
        pill_html = '<span class="badge b-green"><span class="badge-dot"></span>TIER 2 (AGGRESSIVE)</span>'
        bar_fill_color = "linear-gradient(90deg, #10B981, #059669)"
    elif tier == 1:
        pill_html = '<span class="badge b-cyan"><span class="badge-dot"></span>TIER 1 (ACCELERATED)</span>'
        bar_fill_color = "linear-gradient(90deg, #06B6D4, #3B82F6)"
    else:
        pill_html = '<span class="badge b-slate"><span class="badge-dot"></span>TIER 0 (BASE CAPITAL)</span>'
        bar_fill_color = "linear-gradient(90deg, #64748B, #94A3B8)"

    pnl_sign = "+" if net_profit_pct >= 0 else ""

    html = f"""
    <div class="compounding-panel">
        <div class="comp-header">
            <div class="comp-title">
                House-Money Compounding & Dynamic Lot Scaling
            </div>
            {pill_html}
        </div>
        <div class="comp-grid">
            <div class="comp-card">
                <div class="comp-card-label">Net Profit (from $155)</div>
                <div class="comp-card-val">{pnl_sign}{net_profit_pct:.1f}%</div>
                <div class="comp-card-sub">Realized Gain</div>
            </div>
            <div class="comp-card">
                <div class="comp-card-label">Safety Cushion</div>
                <div class="comp-card-val">${safety_cushion_usd:,.2f}</div>
                <div class="comp-card-sub">Profit Buffer Only</div>
            </div>
            <div class="comp-card">
                <div class="comp-card-label">Per-Trade Risk</div>
                <div class="comp-card-val">{effective_risk_pct:.1f}%</div>
                <div class="comp-card-sub">Base 1.0%</div>
            </div>
            <div class="comp-card">
                <div class="comp-card-label">Lot Multiplier</div>
                <div class="comp-card-val">{lot_multiplier:.2f}x</div>
                <div class="comp-card-sub">Dynamic Scale</div>
            </div>
        </div>
        <div>
            <div style="display: flex; justify-content: space-between; align-items: center; font-family: 'Inter', sans-serif; font-size: 0.65rem; color: #94A3B8;">
                <span>Milestone Progress (Target: +{next_milestone_pct:.0f}% Net Profit)</span>
                <span style="font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #F1F5F9;">{progress:.1f}%</span>
            </div>
            <div class="milestone-bar-bg">
                <div class="milestone-bar-fill" style="width: {progress:.1f}%; background: {bar_fill_color};"></div>
            </div>
            <div style="font-family: 'Inter', sans-serif; font-size: 0.65rem; color: #64748B; margin-top: 4px;">
                <em>Context: {reason}</em>
            </div>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
