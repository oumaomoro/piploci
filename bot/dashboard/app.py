"""
Piploci Trading Desk — Principal-Grade Monitoring Dashboard.
Orchestrates modern glassmorphic UI components, live telemetry, and risk management tabs.
Features high-performance non-blocking auto-refresh via st.fragment and consolidated telemetry.
"""

import time
import streamlit as st

from bot.dashboard.styles import DASHBOARD_CSS
from bot.dashboard.api_client import fetch_telemetry, query_api
from bot.dashboard.components.status_bar import render_status_bar
from bot.dashboard.components.metric_cards import render_metric_cards
from bot.dashboard.components.risk_gauge import render_risk_gauge
from bot.dashboard.components.instruments import render_instruments
from bot.dashboard.components.sidebar import render_sidebar
from bot.dashboard.tabs.positions import render_positions_tab
from bot.dashboard.tabs.performance import render_performance_tab
from bot.dashboard.tabs.history import render_history_tab
from bot.dashboard.tabs.logs import render_logs_tab
from bot.dashboard.tabs.signals import render_signals_tab


def run_dashboard():
    """Main execution function called by Streamlit entrypoint on each rerun."""
    try:
        st.set_page_config(
            page_title="Piploci Trading Desk",
            page_icon="◆",
            layout="wide",
            initial_sidebar_state="collapsed",
        )
    except Exception:
        pass  # page_config can only be called once per script run

    # 1. Style Injection
    st.markdown(DASHBOARD_CSS, unsafe_allow_html=True)

    # 2. Sidebar Controls & Configurator
    refresh_rate = st.sidebar.slider("Auto-Refresh Rate (s)", min_value=1, max_value=10, value=3, step=1)
    live_stream = st.sidebar.toggle("Live Telemetry Stream", value=True)

    initial_telem = fetch_telemetry()
    if initial_telem:
        init_status = initial_telem.get("status", {})
        init_configs = initial_telem.get("configs", [])
    else:
        init_status = query_api("/status") or {}
        init_configs = query_api("/configs") or []

    render_sidebar(init_configs, init_status)

    # 3. Live Trading Desk Component (Non-Blocking Auto-Refresh Fragment)
    @st.fragment(run_every=f"{refresh_rate}s" if live_stream else None)
    def render_live_desk():
        t0 = time.time()
        telem = fetch_telemetry()

        if telem:
            status_data = telem.get("status", {})
            configs = telem.get("configs", [])
            signals_data = telem.get("signals", {})
            positions = telem.get("positions", [])
            trades = telem.get("trades", [])
            events = telem.get("events", [])
            signal_audits = telem.get("signal_audits", [])
            latency_ms = telem.get("latency_ms", (time.time() - t0) * 1000.0)
        else:
            status_data = query_api("/status") or {}
            configs = query_api("/configs") or []
            signals_data = query_api("/signals") or {}
            positions = query_api("/positions") or []
            trades = query_api("/trades") or []
            events = query_api("/events") or []
            signal_audits = []
            latency_ms = (time.time() - t0) * 1000.0 if status_data else None

        # Top Status Bar & Metric Cards
        render_status_bar(status_data, latency_ms)
        render_metric_cards(status_data)

        # Risk Budget Panel
        render_risk_gauge(status_data)

        # Asset Strategy Monitors
        render_instruments(configs, signals_data)

        st.markdown("<div style='height: 16px;'></div>", unsafe_allow_html=True)

        # Tabbed Analytics, History & Recall Audit
        tab_positions, tab_perf, tab_history, tab_logs, tab_signals = st.tabs([
            "Live Positions",
            "Performance Analytics",
            "Trade History",
            "Audit Logs",
            "Signal Recall & Audit",
        ])

        with tab_positions:
            render_positions_tab(positions)

        with tab_perf:
            perf_stats = status_data.get("performance", {}) if status_data else {}
            render_performance_tab(perf_stats, trades)

        with tab_history:
            render_history_tab(trades)

        with tab_logs:
            render_logs_tab(events)

        with tab_signals:
            render_signals_tab(signal_audits)

    render_live_desk()


if __name__ == "__main__":
    run_dashboard()
