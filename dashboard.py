"""
Institutional Real-Time Monitoring & Execution Dashboard for Piploci.
Professional Bloomberg/Terminal aesthetic with zero emojis, high-contrast typography,
live terminal telemetry, strict circuit breaker metrics, and real-time asset controls.
"""

import os
import time
from datetime import datetime, timezone
import requests
import streamlit as st
import pandas as pd

# Dynamic API endpoint resolution (Supports Streamlit Cloud st.secrets & env vars)
DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
try:
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        API_BASE = st.secrets["API_BASE"]
    else:
        API_BASE = os.getenv("API_BASE", DEFAULT_API_URL)
except Exception:
    API_BASE = os.getenv("API_BASE", DEFAULT_API_URL)

st.set_page_config(
    page_title="Piploci",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Professional Institutional Dark Theme (No Emojis, Pure Financial Precision)
st.markdown("""
<style>
    /* Global Reset & Base Palette */
    .stApp {
        background-color: #06090E;
        color: #E2E8F0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Helvetica Neue", Arial, sans-serif;
    }
    
    /* Headers & Typography */
    h1, h2, h3, h4, h5, h6 {
        font-weight: 600;
        letter-spacing: -0.02em;
        color: #F8FAFC;
    }
    
    /* Metrics */
    div[data-testid="stMetricValue"] {
        font-family: "JetBrains Mono", "SF Mono", "Consolas", monospace !important;
        font-size: 1.55rem !important;
        font-weight: 700 !important;
        color: #FFFFFF !important;
        letter-spacing: -0.03em;
    }
    div[data-testid="stMetricLabel"] {
        font-size: 0.72rem !important;
        color: #64748B !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
    }

    /* Cards & Containers */
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background-color: #0B0F19;
        border: 1px solid #1E293B;
        border-radius: 6px;
        padding: 16px;
    }
    
    /* Institutional Status Badges */
    .status-pill {
        display: inline-flex;
        align-items: center;
        padding: 3px 9px;
        border-radius: 4px;
        font-family: "JetBrains Mono", monospace;
        font-size: 0.70rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .pill-active {
        background-color: rgba(16, 185, 129, 0.12);
        color: #10B981;
        border: 1px solid rgba(16, 185, 129, 0.35);
    }
    .pill-neutral {
        background-color: rgba(56, 189, 248, 0.12);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.35);
    }
    .pill-warning {
        background-color: rgba(245, 158, 11, 0.12);
        color: #F59E0B;
        border: 1px solid rgba(245, 158, 11, 0.35);
    }
    .pill-critical {
        background-color: rgba(239, 68, 68, 0.12);
        color: #EF4444;
        border: 1px solid rgba(239, 68, 68, 0.35);
    }
    .pill-muted {
        background-color: rgba(100, 116, 139, 0.12);
        color: #94A3B8;
        border: 1px solid rgba(100, 116, 139, 0.3);
    }

    /* Table & Monospace Display */
    .dataframe {
        font-family: "JetBrains Mono", monospace !important;
        font-size: 0.80rem !important;
    }
    
    /* Audit Log Terminal Box */
    .audit-terminal {
        background-color: #030508;
        border: 1px solid #1E2638;
        border-radius: 4px;
        padding: 14px;
        font-family: "JetBrains Mono", Consolas, monospace;
        font-size: 11.5px;
        color: #CBD5E1;
        line-height: 1.6;
    }
    
    /* Buttons */
    .stButton > button {
        border-radius: 4px !important;
        font-weight: 600 !important;
        letter-spacing: 0.04em !important;
        font-size: 0.78rem !important;
        text-transform: uppercase !important;
    }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# DATA INGESTION
# ==============================================================================
def query_api(endpoint: str):
    try:
        res = requests.get(f"{API_BASE}/{endpoint}", timeout=2.0)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return None

def send_command(endpoint: str, payload: dict = None):
    try:
        res = requests.post(f"{API_BASE}/{endpoint}", json=payload, timeout=3.0)
        return res.status_code == 200, res.json() if res.status_code == 200 else res.text
    except Exception as e:
        return False, str(e)


# ==============================================================================
# SIDEBAR: SYSTEM CONTROLS & PARAMS
# ==============================================================================
with st.sidebar:
    st.markdown("### PIPLOCI")
    st.caption("QUANTITATIVE EXECUTION & RISK MANAGEMENT")
    
    with st.expander("GATEWAY ENDPOINT", expanded=False):
        gateway_input = st.text_input("Backend API Base URL", value=API_BASE, key="custom_gateway_url")
        if gateway_input and gateway_input.strip() != API_BASE:
            API_BASE = gateway_input.strip().rstrip("/")
            st.rerun()

    st.divider()

    st.markdown("#### SYSTEM OVERRIDES")
    
    status_data = query_api("status") or {}
    is_halted = status_data.get("circuit_breaker_active", False) or status_data.get("status") in ["HALTED", "CIRCUIT_BREAKER_HALTED"]

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("KILL SWITCH", type="primary", use_container_width=True, disabled=is_halted):
            ok, msg = send_command("control/emergency-stop")
            if ok:
                st.error("KILL SWITCH ACTIVATED: Closed all open bot positions.")
                time.sleep(0.4)
                st.rerun()
            else:
                st.error(f"Execution failed: {msg}")

    with col_btn2:
        if st.button("RESUME", use_container_width=True, disabled=not is_halted):
            ok, msg = send_command("control/resume")
            if ok:
                st.success("System resumed.")
                time.sleep(0.4)
                st.rerun()
            else:
                st.error(f"Execution failed: {msg}")

    st.divider()
    st.markdown("#### EXECUTION PARAMETERS")
    st.markdown("""
    - **Max Daily Drawdown:** `$4.50 USD`
    - **Cooldown Period:** `24 Hours`
    - **Risk Allocation:** `1.0% / Trade`
    - **Gold Magic ID:** `100201`
    - **USDJPY Magic ID:** `100202`
    - **Protected IDs:** `Discretionary (0)`
    """)
    st.divider()
    auto_refresh = st.checkbox("Live Refresh (2.0s)", value=True)


# ==============================================================================
# MAIN DASHBOARD CONTROLLER (FRAGMENT REFRESH)
# ==============================================================================
@st.fragment(run_every="2.0s" if auto_refresh else None)
def display_portfolio():
    status = query_api("status")
    is_live_conn = status is not None

    if not status:
        status = {
            "status": "OFFLINE",
            "terminal_connected": False,
            "balance": 0.0,
            "equity": 0.0,
            "floating_pnl": 0.0,
            "starting_daily_balance": 0.0,
            "current_drawdown": 0.0,
            "daily_drawdown_limit": 4.50,
            "circuit_breaker_active": False,
            "allowed_magic_numbers": [100201, 100202],
        }

    # Top Telemetry Bar
    c_title, c_badges = st.columns([3, 2])
    with c_title:
        st.markdown("### INSTITUTIONAL MULTI-ASSET TRADING DESK")
    with c_badges:
        if status.get("terminal_connected"):
            badge_term = '<span class="status-pill pill-active">MT5 TERMINAL: CONNECTED</span>'
        else:
            badge_term = '<span class="status-pill pill-critical">MT5 TERMINAL: DISCONNECTED</span>'

        if status.get("circuit_breaker_active") or status.get("status") in ["HALTED", "CIRCUIT_BREAKER_HALTED"]:
            badge_state = '<span class="status-pill pill-critical">CIRCUIT BREAKER: HALTED</span>'
        elif status.get("status") == "RUNNING":
            badge_state = '<span class="status-pill pill-active">STATE: ACTIVE SCANNING</span>'
        else:
            badge_state = '<span class="status-pill pill-muted">STATE: STANDBY</span>'

        badge_sec = '<span class="status-pill pill-muted">MAGIC ISOLATION: ENFORCED</span>'
        st.markdown(f"<div style='text-align: right; padding-top: 4px;'>{badge_term} &nbsp; {badge_state} &nbsp; {badge_sec}</div>", unsafe_allow_html=True)

    st.markdown("<hr style='margin-top: 8px; margin-bottom: 20px; border-color: #1E293B;'>", unsafe_allow_html=True)

    # 1. Financial KPIs
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    balance = status.get("balance", 0.0)
    equity = status.get("equity", 0.0)
    floating_pnl = status.get("floating_pnl", 0.0)
    drawdown = status.get("current_drawdown", 0.0)
    drawdown_limit = status.get("daily_drawdown_limit", 4.50)

    with kpi1:
        st.metric("NET ASSET VALUE (EQUITY)", f"${equity:,.2f}" if is_live_conn else "--")
    with kpi2:
        st.metric("STARTING DAILY BALANCE", f"${status.get('starting_daily_balance', balance):,.2f}" if is_live_conn else "--")
    with kpi3:
        pnl_str = f"${floating_pnl:+,.2f}" if is_live_conn else "--"
        st.metric("UNREALIZED FLOATING P&L", pnl_str, delta=f"{floating_pnl:+.2f}" if is_live_conn else None)
    with kpi4:
        dd_str = f"${drawdown:.2f} / ${drawdown_limit:.2f}" if is_live_conn else "--"
        st.metric("DAILY DRAWDOWN EXPOSURE", dd_str, delta=f"-${drawdown:.2f}" if drawdown > 0 else "0.00", delta_color="inverse")

    # 2. Risk Circuit Breaker Meter
    st.markdown("<br>", unsafe_allow_html=True)
    ratio = min(max(drawdown / drawdown_limit, 0.0), 1.0) if drawdown_limit > 0 else 0.0
    
    st.markdown(f"**DAILY FLOATING DRAWDOWN RISK BUDGET** &nbsp; `[THRESHOLD: ${drawdown_limit:.2f} USD]`")
    st.progress(ratio)
    
    if ratio >= 0.8:
        st.markdown(f"<span style='color: #EF4444; font-size: 0.80rem; font-weight: 600;'>[ALERT] HIGH RISK EXPOSURE: ${drawdown:.2f} OF ${drawdown_limit:.2f} BUDGET EXPENDED ({(ratio * 100):.1f}%)</span>", unsafe_allow_html=True)
    elif ratio >= 0.5:
        st.markdown(f"<span style='color: #F59E0B; font-size: 0.80rem; font-weight: 600;'>[NOTICE] MODERATE DRAWDOWN: ${drawdown:.2f} OF ${drawdown_limit:.2f} BUDGET EXPENDED ({(ratio * 100):.1f}%)</span>", unsafe_allow_html=True)
    else:
        st.markdown(f"<span style='color: #10B981; font-size: 0.80rem; font-weight: 600;'>[NORMAL] WITHIN RISK LIMITS: ${drawdown:.2f} EXPENDED ({(ratio * 100):.1f}%)</span>", unsafe_allow_html=True)

    st.markdown("<hr style='margin-top: 24px; margin-bottom: 24px; border-color: #1E293B;'>", unsafe_allow_html=True)

    # 3. Asset Execution & Strategy Alignment Panels
    st.markdown("#### ASSET SCANNING & MULTI-TIMEFRAME CONSENSUS")
    
    configs = query_api("configs") or []
    cfg_map = {c["symbol"]: c["active"] for c in configs}
    signals = query_api("signals") or {}

    col_gold, col_jpy = st.columns(2)

    with col_gold:
        with st.container():
            cg_h1, cg_h2 = st.columns([3, 1])
            with cg_h1:
                st.markdown("**XAUUSD // SPOT GOLD**")
                st.caption("MAGIC ID: `100201` | SESSION: `15:30 - 19:30 EAT`")
            with cg_h2:
                gold_active = cfg_map.get("XAUUSD", True)
                if st.button("DISABLE" if gold_active else "ENABLE", key="btn_xau", use_container_width=True):
                    send_command("control/toggle", {"symbol": "XAUUSD", "active": not gold_active})
                    st.rerun()

            sig_info = signals.get("XAUUSD", {})
            sig = sig_info.get("signal", {})
            dir_str = sig.get("direction", "NEUTRAL")
            sess_str = sig_info.get("session_message", "STANDBY")
            in_sess = sig_info.get("session_active", False)
            news_blk = sig_info.get("news_blackout", False)
            news_msg = sig_info.get("news_message", "NEWS SHIELD: NORMAL (NO HIGH-IMPACT EVENTS)")

            sess_badge = '<span class="status-pill pill-active">SESSION: ACTIVE</span>' if in_sess else '<span class="status-pill pill-muted">SESSION: CLOSED</span>'
            news_badge = '<span class="status-pill pill-critical">NEWS: BLACKOUT ACTIVE</span>' if news_blk else '<span class="status-pill pill-active">NEWS: CLEAR</span>'

            st.markdown(f"STATUS: &nbsp; {sess_badge} &nbsp; {news_badge}", unsafe_allow_html=True)
            st.markdown(f"WINDOW: `{sess_str}`")
            st.markdown(f"CALENDAR: `{news_msg or 'Normal'}`")
            st.markdown(f"CONSENSUS (M15+H1): `{sig.get('reason', 'Evaluating technical indicators...')}`")
            
            if dir_str == "BUY":
                st.markdown('<span class="status-pill pill-active">RECOMMENDATION: STRONG BUY ALIGNED</span>', unsafe_allow_html=True)
            elif dir_str == "SELL":
                st.markdown('<span class="status-pill pill-critical">RECOMMENDATION: STRONG SELL ALIGNED</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-pill pill-warning">RECOMMENDATION: STANDBY (NO ALIGNMENT)</span>', unsafe_allow_html=True)

    with col_jpy:
        with st.container():
            cj_h1, cj_h2 = st.columns([3, 1])
            with cj_h1:
                st.markdown("**USDJPY // US DOLLAR / JAPANESE YEN**")
                st.caption("MAGIC ID: `100202` | SESSIONS: `03:00-07:00 / 15:30-19:30 EAT`")
            with cj_h2:
                jpy_active = cfg_map.get("USDJPY", True)
                if st.button("DISABLE" if jpy_active else "ENABLE", key="btn_jpy", use_container_width=True):
                    send_command("control/toggle", {"symbol": "USDJPY", "active": not jpy_active})
                    st.rerun()

            sig_info_j = signals.get("USDJPY", {})
            sig_j = sig_info_j.get("signal", {})
            dir_str_j = sig_j.get("direction", "NEUTRAL")
            sess_str_j = sig_info_j.get("session_message", "STANDBY")
            in_sess_j = sig_info_j.get("session_active", False)
            news_blk_j = sig_info_j.get("news_blackout", False)
            news_msg_j = sig_info_j.get("news_message", "NEWS SHIELD: NORMAL (NO HIGH-IMPACT EVENTS)")

            sess_badge_j = '<span class="status-pill pill-active">SESSION: ACTIVE</span>' if in_sess_j else '<span class="status-pill pill-muted">SESSION: CLOSED</span>'
            news_badge_j = '<span class="status-pill pill-critical">NEWS: BLACKOUT ACTIVE</span>' if news_blk_j else '<span class="status-pill pill-active">NEWS: CLEAR</span>'

            st.markdown(f"STATUS: &nbsp; {sess_badge_j} &nbsp; {news_badge_j}", unsafe_allow_html=True)
            st.markdown(f"WINDOW: `{sess_str_j}`")
            st.markdown(f"CALENDAR: `{news_msg_j or 'Normal'}`")
            st.markdown(f"CONSENSUS (M15+H1): `{sig_j.get('reason', 'Evaluating technical indicators...')}`")

            if dir_str_j == "BUY":
                st.markdown('<span class="status-pill pill-active">RECOMMENDATION: BUY ALIGNED</span>', unsafe_allow_html=True)
            elif dir_str_j == "SELL":
                st.markdown('<span class="status-pill pill-critical">RECOMMENDATION: SELL ALIGNED</span>', unsafe_allow_html=True)
            else:
                st.markdown('<span class="status-pill pill-warning">RECOMMENDATION: STANDBY (NO ALIGNMENT)</span>', unsafe_allow_html=True)

    st.markdown("<hr style='margin-top: 24px; margin-bottom: 24px; border-color: #1E293B;'>", unsafe_allow_html=True)

    # 4. Open Position Book (Magic Isolated)
    st.markdown("#### ACTIVE ORDERS (ISOLATED TO MAGIC 100201 & 100202)")
    positions = query_api("positions") or []
    
    if positions:
        df_pos = pd.DataFrame(positions)
        cols_map = {
            "ticket": "TICKET",
            "symbol": "SYMBOL",
            "type": "SIDE",
            "volume": "VOLUME",
            "price_open": "OPEN PRICE",
            "sl": "SL",
            "tp": "TP",
            "profit": "UNREALIZED P&L ($)",
            "magic": "MAGIC ID",
        }
        show_cols = [c for c in cols_map.keys() if c in df_pos.columns]
        df_display = df_pos[show_cols].rename(columns=cols_map)
        
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        col_pos_sel, col_pos_act = st.columns([3, 1])
        with col_pos_sel:
            sel_ticket = st.selectbox("SELECT POSITION TICKET TO CLOSE:", [p["ticket"] for p in positions], key="pos_sel_box")
        with col_pos_act:
            st.write("")
            st.write("")
            if st.button("CLOSE SELECTED POSITION", use_container_width=True):
                ok, res = send_command("control/close-position", {"ticket": sel_ticket})
                if ok:
                    st.success(f"Position #{sel_ticket} closed.")
                    st.rerun()
                else:
                    st.error(f"Close failed: {res}")
    else:
        st.markdown("<div class='audit-terminal'>NO ACTIVE BOT POSITIONS RECORDED. ENGINE IS MONITORING CRITERIA FOR ENTRY.</div>", unsafe_allow_html=True)

    st.markdown("<hr style='margin-top: 24px; margin-bottom: 24px; border-color: #1E293B;'>", unsafe_allow_html=True)

    # 5. Audit Trail & Deal History
    tab_audit, tab_history = st.tabs(["SYSTEM AUDIT LOGS", "CLOSED DEAL HISTORY"])

    with tab_audit:
        events = query_api("events") or []
        if events:
            lines = []
            for ev in events[:50]:
                ts = ev.get("timestamp", "")[11:19]
                lvl = ev.get("log_level", "INFO")
                mod = ev.get("module", "System")
                msg = ev.get("message", "")
                lines.append(f"[{ts}] [{lvl:7s}] [{mod:12s}] {msg}")
            st.text_area("Audit Log Output", value="\n".join(lines), height=220, disabled=True, label_visibility="collapsed")
        else:
            st.markdown("<div class='audit-terminal'>NO AUDIT LOGS DETECTED.</div>", unsafe_allow_html=True)

    with tab_history:
        trades = query_api("trades") or []
        if trades:
            df_trades = pd.DataFrame(trades)
            col_order = ["ticket", "symbol", "action", "volume", "open_price", "close_price", "sl", "tp", "pnl", "timestamp", "status", "notes"]
            valid_cols = [c for c in col_order if c in df_trades.columns]
            st.dataframe(df_trades[valid_cols], use_container_width=True, hide_index=True)
        else:
            st.markdown("<div class='audit-terminal'>NO EXECUTED DEALS IN LOG.</div>", unsafe_allow_html=True)


display_portfolio()
