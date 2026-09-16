"""
Status Bar Component for Piploci Monitoring Dashboard.
Renders high-level connection badges, MT5 terminal health, and server latency.
"""

from datetime import datetime, timezone
import pytz
import streamlit as st
from typing import Dict, Any, Optional


def render_status_bar(status_data: Optional[Dict[str, Any]], latency_ms: Optional[float] = None):
    """Renders the top telemetry status bar."""
    is_online = status_data is not None
    engine_state = status_data.get("status", "OFFLINE") if status_data else "OFFLINE"
    terminal_conn = status_data.get("terminal_connected", False) if status_data else False
    circuit_active = status_data.get("circuit_breaker_active", False) if status_data else False

    # State Badge Class
    if circuit_active:
        state_badge = '<span class="badge b-red"><span class="badge-dot"></span>CIRCUIT HALTED</span>'
    elif engine_state == "RUNNING":
        state_badge = '<span class="badge b-green"><span class="badge-dot"></span>RUNNING</span>'
    elif engine_state in ["HALTED", "STOPPED"]:
        state_badge = '<span class="badge b-amber"><span class="badge-dot"></span>HALTED</span>'
    else:
        state_badge = f'<span class="badge b-slate"><span class="badge-dot"></span>{engine_state}</span>'

    # Terminal Badge
    if terminal_conn:
        terminal_badge = '<span class="badge b-green"><span class="badge-dot"></span>MT5 CONNECTED</span>'
    else:
        terminal_badge = '<span class="badge b-amber"><span class="badge-dot"></span>MT5 AWAITING</span>'

    # Gateway Badge
    if is_online:
        gateway_badge = '<span class="badge b-cyan"><span class="badge-dot"></span>GATEWAY LIVE</span>'
    else:
        gateway_badge = '<span class="badge b-red"><span class="badge-dot"></span>OFFLINE</span>'

    # EAT Time
    eat_time_str = datetime.now(pytz.timezone("Africa/Nairobi")).strftime("%H:%M:%S EAT")
    lat_str = f"{latency_ms:.0f}ms" if latency_ms is not None else "--"

    html = f"""
    <div class="status-bar">
        <div class="status-left">
            {gateway_badge}
            {terminal_badge}
            {state_badge}
        </div>
        <div class="status-right">
            <span class="status-field">EAT: <strong>{eat_time_str}</strong></span>
            <div class="status-divider"></div>
            <span class="status-field">LATENCY: <strong>{lat_str}</strong></span>
        </div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
