"""
Piploci — Institutional Trading Dashboard.
Clean, responsive, dark-theme monitoring interface with
real-time telemetry, risk controls, and position management.
"""

import os
import time
from datetime import datetime, timezone
import requests
import streamlit as st
import pandas as pd

# ── API Endpoint Resolution ──────────────────────────────────────────────────
_API_BASE_DEFAULT = "https://badge-voltage-mia-father.trycloudflare.com/api/v1"

try:
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        API_BASE = st.secrets["API_BASE"].rstrip("/")
    else:
        API_BASE = os.getenv("API_BASE", _API_BASE_DEFAULT)
        if API_BASE:
            API_BASE = API_BASE.rstrip("/")
except Exception:
    API_BASE = os.getenv("API_BASE", _API_BASE_DEFAULT)

st.set_page_config(
    page_title="Piploci",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Design System ────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    /* ── Global ── */
    .stApp {
        background: #0A0E17;
        color: #C8D1DC;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }
    section[data-testid="stSidebar"] {
        background: #0D1117;
        border-right: 1px solid #1C2333;
    }
    h1, h2, h3, h4, h5, h6 {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        color: #E8EDF3;
        letter-spacing: -0.01em;
    }

    /* ── Metrics ── */
    div[data-testid="stMetricValue"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 1.3rem !important;
        font-weight: 600 !important;
        color: #F0F4F8 !important;
    }
    div[data-testid="stMetricLabel"] {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.68rem !important;
        color: #6B7A8D !important;
        font-weight: 500 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
    }
    div[data-testid="stMetricDelta"] {
        font-family: 'JetBrains Mono', monospace !important;
        font-size: 0.72rem !important;
    }

    /* ── Cards ── */
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 8px;
        padding: 20px;
    }

    /* ── Tabs ── */
    button[data-baseweb="tab"] {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }

    /* ── Badges ── */
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 10px;
        border-radius: 6px;
        font-family: 'Inter', sans-serif;
        font-size: 0.65rem;
        font-weight: 600;
        letter-spacing: 0.03em;
        text-transform: uppercase;
        line-height: 1;
    }
    .badge-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
    }
    .b-green  { background: rgba(16,185,129,0.10); color: #34D399; border: 1px solid rgba(16,185,129,0.25); }
    .b-green .badge-dot { background: #10B981; }
    .b-red    { background: rgba(239,68,68,0.10); color: #F87171; border: 1px solid rgba(239,68,68,0.25); }
    .b-red .badge-dot { background: #EF4444; }
    .b-amber  { background: rgba(245,158,11,0.10); color: #FBBF24; border: 1px solid rgba(245,158,11,0.25); }
    .b-amber .badge-dot { background: #F59E0B; }
    .b-slate  { background: rgba(100,116,139,0.10); color: #94A3B8; border: 1px solid rgba(100,116,139,0.20); }
    .b-slate .badge-dot { background: #64748B; }
    .b-cyan   { background: rgba(6,182,212,0.10); color: #22D3EE; border: 1px solid rgba(6,182,212,0.25); }
    .b-cyan .badge-dot { background: #06B6D4; }

    /* ── Section Header ── */
    .section-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.68rem;
        font-weight: 600;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #4B5563;
        margin-bottom: 12px;
        padding-bottom: 6px;
        border-bottom: 1px solid #1F2937;
    }

    /* ── Asset Card ── */
    .asset-card {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 8px;
        padding: 18px 20px;
    }
    .asset-name {
        font-family: 'Inter', sans-serif;
        font-size: 0.9rem;
        font-weight: 700;
        color: #F0F4F8;
        margin-bottom: 2px;
    }
    .asset-sub {
        font-family: 'Inter', sans-serif;
        font-size: 0.65rem;
        color: #6B7A8D;
        letter-spacing: 0.03em;
    }
    .asset-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
        flex-wrap: wrap;
    }
    .asset-field {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        color: #94A3B8;
    }
    .asset-field strong {
        color: #C8D1DC;
    }

    /* ── Risk Meter ── */
    .risk-meter {
        background: #111827;
        border: 1px solid #1F2937;
        border-radius: 8px;
        padding: 14px 18px;
    }
    .risk-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.68rem;
        font-weight: 600;
        color: #6B7A8D;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .risk-bar-bg {
        width: 100%;
        height: 6px;
        background: #1F2937;
        border-radius: 3px;
        margin: 8px 0 6px 0;
        overflow: hidden;
    }
    .risk-bar-fill {
        height: 100%;
        border-radius: 3px;
        transition: width 0.4s ease;
    }
    .risk-status {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
    }

    /* ── Empty State ── */
    .empty-state {
        text-align: center;
        padding: 32px 16px;
        color: #4B5563;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
    }

    /* ── Log Box ── */
    .log-box {
        background: #0D1117;
        border: 1px solid #1C2333;
        border-radius: 6px;
        padding: 12px 14px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        color: #9CA3AF;
        line-height: 1.7;
        max-height: 260px;
        overflow-y: auto;
    }

    /* ── Buttons ── */
    .stButton > button {
        border-radius: 6px !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 600 !important;
        font-size: 0.72rem !important;
        letter-spacing: 0.03em !important;
        text-transform: uppercase !important;
        transition: all 0.15s ease !important;
    }

    /* ── Responsive ── */
    @media (max-width: 768px) {
        div[data-testid="stMetricValue"] { font-size: 1.0rem !important; }
        div[data-testid="stMetricLabel"] { font-size: 0.60rem !important; }
        .asset-name { font-size: 0.82rem; }
        .badge { font-size: 0.58rem; padding: 3px 7px; }
    }
</style>
""", unsafe_allow_html=True)


# ── Helper: Build Badge HTML ─────────────────────────────────────────────────
def badge(text: str, variant: str = "slate") -> str:
    return f'<span class="badge b-{variant}"><span class="badge-dot"></span>{text}</span>'


# ── Data Layer ───────────────────────────────────────────────────────────────
def query_api(endpoint: str):
    global API_BASE
    candidates = [c for c in [API_BASE, _API_BASE_DEFAULT, "http://127.0.0.1:8000/api/v1"] if c]
    seen = set()
    for base in candidates:
        if not base or base in seen:
            continue
        seen.add(base)
        try:
            res = requests.get(f"{base}/{endpoint}", timeout=2.5)
            if res.status_code == 200:
                API_BASE = base
                return res.json()
        except Exception:
            continue
    return None


DASHBOARD_AUTH_TOKEN = None

def get_auth_headers(base_url: str) -> dict:
    global DASHBOARD_AUTH_TOKEN
    if DASHBOARD_AUTH_TOKEN:
        return {"Authorization": f"Bearer {DASHBOARD_AUTH_TOKEN}"}

    try:
        admin_user = st.secrets.get("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
    except Exception:
        admin_user = os.getenv("ADMIN_USER", "admin")
    try:
        admin_pass = st.secrets.get("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "AdminPass@2026"))
    except Exception:
        admin_pass = os.getenv("ADMIN_PASSWORD", "AdminPass@2026")

    try:
        login_res = requests.post(
            f"{base_url}/login",
            json={"username": admin_user, "password": admin_pass},
            timeout=3.0,
        )
        if login_res.status_code == 200:
            DASHBOARD_AUTH_TOKEN = login_res.json().get("access_token")
            return {"Authorization": f"Bearer {DASHBOARD_AUTH_TOKEN}"}
    except Exception:
        pass
    return {}


def send_command(endpoint: str, payload: dict = None):
    global API_BASE, DASHBOARD_AUTH_TOKEN
    candidates = [c for c in [API_BASE, _API_BASE_DEFAULT, "http://127.0.0.1:8000/api/v1"] if c]
    seen = set()
    for base in candidates:
        if not base or base in seen:
            continue
        seen.add(base)
        headers = get_auth_headers(base)
        try:
            res = requests.post(f"{base}/{endpoint}", json=payload, headers=headers, timeout=3.0)
            if res.status_code == 200:
                API_BASE = base
                return True, res.json()
            elif res.status_code == 401:
                DASHBOARD_AUTH_TOKEN = None
                new_headers = get_auth_headers(base)
                retry = requests.post(f"{base}/{endpoint}", json=payload, headers=new_headers, timeout=3.0)
                if retry.status_code == 200:
                    API_BASE = base
                    return True, retry.json()
        except Exception:
            continue
    return False, "Connection failed"


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("#### ◆ Piploci")
    st.caption("Quantitative Execution Engine")
    st.divider()

    with st.expander("Gateway", expanded=False):
        gw = st.text_input("API Endpoint", value=API_BASE or "", key="gw_input", label_visibility="collapsed")
        if gw and gw.strip().rstrip("/") != (API_BASE or ""):
            API_BASE = gw.strip().rstrip("/")
            st.rerun()

    st.divider()
    st.markdown("##### Controls")

    status_data = query_api("status") or {}
    is_halted = status_data.get("circuit_breaker_active", False) or status_data.get("status") in ["HALTED", "CIRCUIT_BREAKER_HALTED"]

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Kill Switch", type="primary", use_container_width=True, disabled=is_halted):
            ok, msg = send_command("control/emergency-stop")
            if ok:
                st.toast("Kill switch activated — all bot positions closed.", icon="🔴")
                time.sleep(0.4)
                st.rerun()
    with c2:
        if st.button("Resume", use_container_width=True, disabled=not is_halted):
            ok, msg = send_command("control/resume")
            if ok:
                st.toast("Trading resumed.", icon="🟢")
                time.sleep(0.4)
                st.rerun()

    st.divider()

    with st.expander("Risk Parameters", expanded=False):
        st.markdown("""
| Parameter | Value |
|---|---|
| Daily Drawdown Limit | $4.50 |
| Cooldown Period | 24h |
| Risk Per Trade | 1.0% |
| Gold Magic ID | 100201 |
| USDJPY Magic ID | 100202 |
""")

    st.divider()
    auto_refresh = st.toggle("Live Refresh", value=True)


# ── Main Dashboard ───────────────────────────────────────────────────────────
@st.fragment(run_every="2.0s" if auto_refresh else None)
def render_dashboard():
    status = query_api("status")
    online = status is not None

    if not status:
        status = {
            "status": "OFFLINE", "terminal_connected": False,
            "balance": 0.0, "equity": 0.0, "floating_pnl": 0.0,
            "starting_daily_balance": 0.0, "current_drawdown": 0.0,
            "daily_drawdown_limit": 4.50, "circuit_breaker_active": False,
        }

    # ── Header Row ───────────────────────────────────────────────────────
    hdr_left, hdr_right = st.columns([3, 2])
    with hdr_left:
        st.markdown("## Trading Desk")
    with hdr_right:
        # Status badges — right-aligned
        term_b = badge("Terminal Connected", "green") if status.get("terminal_connected") else badge("Terminal Offline", "red")

        state_val = status.get("status", "OFFLINE")
        if state_val in ["HALTED", "CIRCUIT_BREAKER_HALTED"]:
            state_b = badge("Halted", "red")
        elif state_val == "RUNNING":
            state_b = badge("Active", "green")
        else:
            state_b = badge("Offline", "slate")

        st.markdown(
            f"<div style='text-align:right;padding-top:12px;display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap;'>{term_b} {state_b}</div>",
            unsafe_allow_html=True,
        )

    # ── KPI Row ──────────────────────────────────────────────────────────
    balance = status.get("balance", 0.0)
    equity = status.get("equity", 0.0)
    pnl = status.get("floating_pnl", 0.0)
    dd = status.get("current_drawdown", 0.0)
    dd_limit = status.get("daily_drawdown_limit", 4.50)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Equity", f"${equity:,.2f}" if online else "—")
    with k2:
        st.metric("Balance", f"${balance:,.2f}" if online else "—")
    with k3:
        st.metric("Floating P&L", f"${pnl:+,.2f}" if online else "—",
                   delta=f"{pnl:+.2f}" if online and pnl != 0 else None)
    with k4:
        st.metric("Drawdown", f"${dd:.2f} / ${dd_limit:.2f}" if online else "—",
                   delta=f"-{dd:.2f}" if dd > 0 else None, delta_color="inverse")

    # ── Risk Gauge ───────────────────────────────────────────────────────
    ratio = min(max(dd / dd_limit, 0.0), 1.0) if dd_limit > 0 else 0.0
    pct = ratio * 100

    if ratio >= 0.8:
        bar_color = "#EF4444"
        risk_text = f'<span class="risk-status" style="color:#F87171;">Critical — ${dd:.2f} of ${dd_limit:.2f} used ({pct:.0f}%)</span>'
    elif ratio >= 0.5:
        bar_color = "#F59E0B"
        risk_text = f'<span class="risk-status" style="color:#FBBF24;">Elevated — ${dd:.2f} of ${dd_limit:.2f} used ({pct:.0f}%)</span>'
    else:
        bar_color = "#10B981"
        risk_text = f'<span class="risk-status" style="color:#34D399;">Normal — ${dd:.2f} of ${dd_limit:.2f} used ({pct:.0f}%)</span>'

    st.markdown(f"""
    <div class="risk-meter">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <span class="risk-label">Daily Risk Budget</span>
            {risk_text}
        </div>
        <div class="risk-bar-bg">
            <div class="risk-bar-fill" style="width:{pct:.1f}%;background:{bar_color};"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("")

    # ── Asset Cards ──────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Market Instruments</div>', unsafe_allow_html=True)

    configs = query_api("configs") or []
    cfg_map = {c["symbol"]: c.get("active", True) for c in configs}
    signals = query_api("signals") or {}

    def render_asset_card(symbol: str, label: str, sessions: str, magic: int, btn_key: str):
        """Renders a clean, compact asset monitoring card."""
        sig_info = signals.get(symbol, {})
        sig = sig_info.get("signal", {})
        direction = sig.get("direction", "NEUTRAL")
        in_session = sig_info.get("session_active", False)
        news_blk = sig_info.get("news_blackout", False)
        reason = sig.get("reason", "Awaiting signal alignment…")
        is_active = cfg_map.get(symbol, True)

        # Badges
        sess_b = badge("In Session", "green") if in_session else badge("Closed", "slate")
        news_b = badge("Blackout", "red") if news_blk else badge("Clear", "green")

        if direction == "BUY":
            sig_b = badge("Buy Aligned", "green")
        elif direction == "SELL":
            sig_b = badge("Sell Aligned", "red")
        else:
            sig_b = badge("Standby", "amber")

        st.markdown(f"""
        <div class="asset-card">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                <div>
                    <div class="asset-name">{label}</div>
                    <div class="asset-sub">Magic {magic} · {sessions}</div>
                </div>
            </div>
            <div class="asset-row">{sess_b} {news_b} {sig_b}</div>
            <div class="asset-field" style="margin-top:10px;">{reason}</div>
        </div>
        """, unsafe_allow_html=True)

        if st.button("Disable" if is_active else "Enable", key=btn_key, use_container_width=True):
            send_command("control/toggle", {"symbol": symbol, "active": not is_active})
            st.rerun()

    col_a, col_b = st.columns(2)
    with col_a:
        render_asset_card("XAUUSD", "XAUUSD — Gold", "15:30–19:30 EAT", 100201, "btn_xau")
    with col_b:
        render_asset_card("USDJPY", "USDJPY — Dollar/Yen", "03:00–07:00 / 15:30–19:30 EAT", 100202, "btn_jpy")

    st.markdown("")

    # ── Positions ────────────────────────────────────────────────────────
    st.markdown('<div class="section-label">Open Positions</div>', unsafe_allow_html=True)

    positions = query_api("positions") or []
    if positions:
        df = pd.DataFrame(positions)
        col_map = {
            "ticket": "Ticket", "symbol": "Symbol", "type": "Side",
            "volume": "Lots", "price_open": "Entry",
            "sl": "SL", "tp": "TP", "profit": "P&L ($)", "magic": "Magic",
        }
        show = [c for c in col_map if c in df.columns]
        st.dataframe(df[show].rename(columns=col_map), use_container_width=True, hide_index=True)

        cp1, cp2 = st.columns([3, 1])
        with cp1:
            sel = st.selectbox("Select position to close", [p["ticket"] for p in positions], key="close_sel", label_visibility="collapsed")
        with cp2:
            if st.button("Close Position", use_container_width=True):
                ok, res = send_command("control/close-position", {"ticket": sel})
                if ok:
                    st.toast(f"Position #{sel} closed.", icon="✓")
                    st.rerun()
                else:
                    st.error(f"Failed: {res}")
    else:
        st.markdown('<div class="empty-state">No open bot positions. Engine is monitoring entry criteria.</div>', unsafe_allow_html=True)

    st.markdown("")

    # ── Logs & History ───────────────────────────────────────────────────
    tab_logs, tab_history = st.tabs(["Audit Log", "Trade History"])

    with tab_logs:
        events = query_api("events") or []
        if events:
            lines = []
            for ev in events[:40]:
                ts = ev.get("timestamp", "")[11:19]
                lvl = ev.get("log_level", "INFO")
                mod = ev.get("module", "System")
                msg = ev.get("message", "")
                lines.append(f"[{ts}] {lvl:7s}  {mod:12s}  {msg}")
            log_text = "\n".join(lines)
            st.markdown(f'<div class="log-box"><pre>{log_text}</pre></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty-state">No audit events recorded.</div>', unsafe_allow_html=True)

    with tab_history:
        trades = query_api("trades") or []
        if trades:
            df_t = pd.DataFrame(trades)
            col_order = ["ticket", "symbol", "action", "volume", "open_price", "close_price", "pnl", "status", "timestamp"]
            valid = [c for c in col_order if c in df_t.columns]
            st.dataframe(df_t[valid], use_container_width=True, hide_index=True)
        else:
            st.markdown('<div class="empty-state">No trade history recorded.</div>', unsafe_allow_html=True)


render_dashboard()
