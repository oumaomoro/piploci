"""
Piploci — Institutional Trading Desk
Principal-grade dark-mode dashboard with real-time telemetry,
risk controls, multi-timeframe signal cards, and Plotly analytics.
"""

import os
import time
import math
from datetime import datetime, timezone
import requests
import streamlit as st
import pandas as pd

# ── Page Config (must be first Streamlit call) ──────────────────────────────
st.set_page_config(
    page_title="Piploci Trading Desk",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── API Endpoint Resolution ─────────────────────────────────────────────────
_CLOUDFLARE_DEFAULT = "https://badge-voltage-mia-father.trycloudflare.com/api/v1"
_LOCAL_FALLBACK     = "http://127.0.0.1:8000/api/v1"

try:
    if hasattr(st, "secrets") and "API_BASE" in st.secrets:
        API_BASE = st.secrets["API_BASE"].rstrip("/")
    else:
        API_BASE = os.getenv("API_BASE", _CLOUDFLARE_DEFAULT).rstrip("/")
except Exception:
    API_BASE = _CLOUDFLARE_DEFAULT


# ── Global CSS / Design System ──────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

/* ── Reset & Base ── */
.stApp {
    background: #060B12;
    color: #C8D1DC;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
section[data-testid="stSidebar"] {
    background: #0A0F18;
    border-right: 1px solid #151F2E;
}
h1,h2,h3,h4,h5,h6 {
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    color: #E8EDF3;
    letter-spacing: -0.015em;
}
a { color: #38BDF8; }

/* ── Streamlit Component Overrides ── */
div[data-testid="stMetricValue"] {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 1.25rem !important;
    font-weight: 700 !important;
    color: #F0F6FF !important;
}
div[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.65rem !important;
    font-weight: 600 !important;
    color: #475569 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
}
div[data-testid="stMetricDelta"] > div {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.70rem !important;
}

/* ── Tab Bar ── */
div[data-testid="stTabs"] button[data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: #64748B !important;
    padding: 8px 16px !important;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
    color: #38BDF8 !important;
    border-bottom: 2px solid #38BDF8 !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 5px !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.69rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.04em !important;
    text-transform: uppercase !important;
    transition: all 0.15s ease !important;
    border: 1px solid #1E293B !important;
}

/* ── Dataframe ── */
div[data-testid="stDataFrame"] {
    border: 1px solid #151F2E;
    border-radius: 6px;
}

/* ── Status Bar ── */
.status-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    background: #0A0F18;
    border: 1px solid #151F2E;
    border-radius: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}
.status-divider {
    width: 1px;
    height: 14px;
    background: #1E293B;
    margin: 0 2px;
}
.status-field {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    color: #475569;
    white-space: nowrap;
}
.status-field strong {
    color: #94A3B8;
    font-weight: 600;
}

/* ── Pulse Badge ── */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 3px 9px;
    border-radius: 4px;
    font-family: 'Inter', sans-serif;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    white-space: nowrap;
}
.badge-dot {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
}
.b-green { background: rgba(16,185,129,0.08); color: #34D399; border: 1px solid rgba(16,185,129,0.20); }
.b-green .badge-dot { background: #10B981; box-shadow: 0 0 5px #10B981; }
.b-red   { background: rgba(239,68,68,0.08); color: #F87171; border: 1px solid rgba(239,68,68,0.20); }
.b-red .badge-dot { background: #EF4444; }
.b-amber { background: rgba(245,158,11,0.08); color: #FBBF24; border: 1px solid rgba(245,158,11,0.20); }
.b-amber .badge-dot { background: #F59E0B; }
.b-slate { background: rgba(100,116,139,0.08); color: #64748B; border: 1px solid rgba(100,116,139,0.15); }
.b-slate .badge-dot { background: #475569; }
.b-cyan  { background: rgba(56,189,248,0.08); color: #38BDF8; border: 1px solid rgba(56,189,248,0.20); }
.b-cyan .badge-dot { background: #0EA5E9; }
.b-blue  { background: rgba(99,102,241,0.08); color: #818CF8; border: 1px solid rgba(99,102,241,0.20); }
.b-blue .badge-dot { background: #6366F1; }

/* ── Metric Cards ── */
.metric-card {
    background: #0D1420;
    border: 1px solid #151F2E;
    border-radius: 8px;
    padding: 14px 18px 12px 18px;
    position: relative;
    overflow: hidden;
}
.metric-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, #1E3A5F, transparent);
}
.mc-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.60rem;
    font-weight: 600;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    margin-bottom: 6px;
}
.mc-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.3rem;
    font-weight: 700;
    color: #F0F6FF;
    line-height: 1.1;
}
.mc-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.62rem;
    color: #475569;
    margin-top: 4px;
}
.mc-positive { color: #34D399 !important; }
.mc-negative { color: #F87171 !important; }
.mc-neutral  { color: #94A3B8 !important; }

/* ── Risk Gauge ── */
.risk-panel {
    background: #0D1420;
    border: 1px solid #151F2E;
    border-radius: 8px;
    padding: 14px 18px;
}
.risk-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}
.risk-title {
    font-family: 'Inter', sans-serif;
    font-size: 0.62rem;
    font-weight: 600;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.risk-reading {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    font-weight: 600;
}
.risk-bar-bg {
    width: 100%;
    height: 5px;
    background: #0F1A27;
    border-radius: 3px;
    overflow: hidden;
}
.risk-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}
.risk-tiers {
    display: flex;
    justify-content: space-between;
    margin-top: 5px;
}
.risk-tier-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.56rem;
    color: #334155;
}

/* ── Section Label ── */
.section-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: #334155;
    padding-bottom: 8px;
    border-bottom: 1px solid #0F1A27;
    margin-bottom: 12px;
}

/* ── Instrument Card ── */
.inst-card {
    background: #0D1420;
    border: 1px solid #151F2E;
    border-radius: 8px;
    padding: 16px 18px;
    height: 100%;
}
.inst-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 10px;
}
.inst-symbol {
    font-family: 'Inter', sans-serif;
    font-size: 0.92rem;
    font-weight: 700;
    color: #E8EDF3;
}
.inst-sub {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.60rem;
    color: #334155;
    margin-top: 2px;
}
.inst-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-bottom: 10px;
}
.inst-reason {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.63rem;
    color: #475569;
    line-height: 1.5;
    border-top: 1px solid #0F1A27;
    padding-top: 8px;
    margin-top: 6px;
}
.tf-row {
    display: flex;
    gap: 6px;
    margin: 8px 0;
    flex-wrap: wrap;
}
.tf-pill {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.60rem;
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid #1E293B;
    background: #0A0F18;
    color: #475569;
}
.tf-buy    { border-color: rgba(16,185,129,0.25); color: #34D399; background: rgba(16,185,129,0.05); }
.tf-sell   { border-color: rgba(239,68,68,0.25);  color: #F87171; background: rgba(239,68,68,0.05); }
.tf-strong { font-weight: 700; }

/* ── Log Box ── */
.log-box {
    background: #060B12;
    border: 1px solid #0F1A27;
    border-radius: 6px;
    padding: 12px 14px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.63rem;
    color: #475569;
    line-height: 1.75;
    max-height: 320px;
    overflow-y: auto;
}
.log-info    { color: #64748B; }
.log-warning { color: #FBBF24; }
.log-error   { color: #F87171; }
.log-critical{ color: #F43F5E; }

/* ── Empty State ── */
.empty-state {
    text-align: center;
    padding: 36px 16px;
    color: #334155;
    font-family: 'Inter', sans-serif;
    font-size: 0.78rem;
}

/* ── Perf Stat Row ── */
.perf-stat-row {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 14px;
}
.perf-stat {
    background: #0D1420;
    border: 1px solid #151F2E;
    border-radius: 6px;
    padding: 10px 16px;
    flex: 1;
    min-width: 100px;
}
.perf-stat-label {
    font-family: 'Inter', sans-serif;
    font-size: 0.58rem;
    font-weight: 600;
    color: #334155;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    margin-bottom: 4px;
}
.perf-stat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.1rem;
    font-weight: 700;
    color: #E8EDF3;
}

/* ── Responsive ── */
@media (max-width: 768px) {
    .mc-value { font-size: 1.05rem; }
    .inst-symbol { font-size: 0.80rem; }
    .status-bar { gap: 5px; }
    .status-divider { display: none; }
    div[data-testid="stMetricValue"] { font-size: 0.95rem !important; }
}
</style>
""", unsafe_allow_html=True)


# ── Utilities ────────────────────────────────────────────────────────────────
def badge(text: str, variant: str = "slate") -> str:
    return f'<span class="badge b-{variant}"><span class="badge-dot"></span>{text}</span>'


DASHBOARD_AUTH_TOKEN = None

def _candidates():
    return list(dict.fromkeys(
        b for b in [API_BASE, _CLOUDFLARE_DEFAULT, _LOCAL_FALLBACK] if b
    ))

def query_api(endpoint: str):
    global API_BASE
    for base in _candidates():
        try:
            r = requests.get(f"{base}/{endpoint}", timeout=2.5)
            if r.status_code == 200:
                API_BASE = base
                return r.json()
        except Exception:
            continue
    return None

def _get_token(base: str) -> dict:
    global DASHBOARD_AUTH_TOKEN
    if DASHBOARD_AUTH_TOKEN:
        return {"Authorization": f"Bearer {DASHBOARD_AUTH_TOKEN}"}
    try:
        au = getattr(st.secrets, "get", lambda k, d: os.getenv(k, d))("ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
        ap = getattr(st.secrets, "get", lambda k, d: os.getenv(k, d))("ADMIN_PASSWORD", os.getenv("ADMIN_PASSWORD", "AdminPass@2026"))
    except Exception:
        au, ap = os.getenv("ADMIN_USER", "admin"), os.getenv("ADMIN_PASSWORD", "AdminPass@2026")
    try:
        lr = requests.post(f"{base}/login", json={"username": au, "password": ap}, timeout=3.0)
        if lr.status_code == 200:
            DASHBOARD_AUTH_TOKEN = lr.json().get("access_token")
            return {"Authorization": f"Bearer {DASHBOARD_AUTH_TOKEN}"}
    except Exception:
        pass
    return {}

def send_command(endpoint: str, payload: dict = None):
    global API_BASE, DASHBOARD_AUTH_TOKEN
    for base in _candidates():
        hdrs = _get_token(base)
        try:
            r = requests.post(f"{base}/{endpoint}", json=payload, headers=hdrs, timeout=3.0)
            if r.status_code == 200:
                API_BASE = base
                return True, r.json()
            if r.status_code == 401:
                DASHBOARD_AUTH_TOKEN = None
                hdrs = _get_token(base)
                r2 = requests.post(f"{base}/{endpoint}", json=payload, headers=hdrs, timeout=3.0)
                if r2.status_code == 200:
                    API_BASE = base
                    return True, r2.json()
        except Exception:
            continue
    return False, "Connection failed"


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("#### Piploci")
    st.caption("Quantitative Execution Engine — v2.1")
    st.divider()

    with st.expander("Gateway", expanded=False):
        gw = st.text_input(
            "API Endpoint", value=API_BASE or "", key="gw_input",
            label_visibility="collapsed", placeholder="https://..."
        )
        if gw and gw.strip().rstrip("/") != (API_BASE or ""):
            API_BASE = gw.strip().rstrip("/")
            st.rerun()

    st.divider()
    st.markdown("##### Engine Controls")

    _sidebar_status = query_api("status") or {}
    _is_halted = (
        _sidebar_status.get("circuit_breaker_active", False)
        or _sidebar_status.get("status") in ["HALTED", "CIRCUIT_BREAKER_HALTED"]
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Kill Switch", type="primary", use_container_width=True, disabled=_is_halted, key="sb_kill"):
            ok, _ = send_command("control/emergency-stop")
            if ok:
                st.toast("Kill switch activated.")
                time.sleep(0.4)
                st.rerun()
    with c2:
        if st.button("Resume", use_container_width=True, disabled=not _is_halted, key="sb_resume"):
            ok, _ = send_command("control/resume")
            if ok:
                st.toast("Trading resumed.")
                time.sleep(0.4)
                st.rerun()

    st.divider()
    with st.expander("Risk Parameters", expanded=False):
        st.markdown("""
| Parameter | Value |
|---|---|
| Daily DD Limit | $4.50 |
| Cooldown | 24 h |
| Risk / Trade | 1.0 % |
| Spread Guard Gold | $0.35 |
| Spread Guard JPY | 2.0 pips |
| Breakeven Trigger | 1.5x ATR |
| Gold Magic | 100201 |
| USDJPY Magic | 100202 |
""")

    st.divider()
    auto_refresh = st.toggle("Live Refresh (2s)", value=True)


# ── Main Fragment ─────────────────────────────────────────────────────────────
@st.fragment(run_every="2.0s" if auto_refresh else None)
def render_dashboard():
    t0 = time.perf_counter()
    status = query_api("status")
    latency_ms = round((time.perf_counter() - t0) * 1000)
    online = status is not None

    if not status:
        status = {
            "status": "OFFLINE", "terminal_connected": False,
            "balance": 0.0, "equity": 0.0, "floating_pnl": 0.0,
            "starting_daily_balance": 0.0, "current_drawdown": 0.0,
            "daily_drawdown_limit": 4.50, "circuit_breaker_active": False,
            "performance": {"total_trades": 0, "win_rate_pct": 0.0,
                            "profit_factor": 0.0, "sharpe_proxy": 0.0},
        }

    # ── Derive state values ──────────────────────────────────────────────
    engine_state  = status.get("status", "OFFLINE")
    term_conn     = status.get("terminal_connected", False)
    balance       = status.get("balance", 0.0)
    equity        = status.get("equity", 0.0)
    pnl           = status.get("floating_pnl", 0.0)
    dd            = status.get("current_drawdown", 0.0)
    dd_limit      = status.get("daily_drawdown_limit", 4.50)
    cb_active     = status.get("circuit_breaker_active", False)
    cb_until      = status.get("circuit_breaker_until")
    perf          = status.get("performance", {})

    now_eat = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")

    # Active session detection (EAT = UTC+3)
    eat_hour = (datetime.now(timezone.utc).hour + 3) % 24
    eat_min  = datetime.now(timezone.utc).minute
    eat_t    = eat_hour * 60 + eat_min
    if 570 <= eat_t <= 690:        # 09:30-11:30 EAT (London Open)
        session_label = "LONDON OPEN"
        session_var   = "cyan"
    elif 930 <= eat_t <= 1110:     # 15:30-18:30 EAT (London/NY Overlap)
        session_label = "LONDON / NY OVERLAP"
        session_var   = "green"
    elif 360 <= eat_t <= 420:      # 06:00-07:00 EAT (Tokyo/London)
        session_label = "TOKYO / LONDON"
        session_var   = "blue"
    else:
        session_label = "OFF-SESSION"
        session_var   = "slate"

    # ── Status Bar ──────────────────────────────────────────────────────
    term_b   = badge("Terminal Connected", "green") if term_conn else badge("Terminal Offline", "red")
    if cb_active:
        eng_b = badge("Circuit Breaker", "red")
    elif engine_state == "RUNNING":
        eng_b = badge("Engine Active", "green")
    elif engine_state in ["HALTED", "EMERGENCY_HALTED"]:
        eng_b = badge("Halted", "red")
    else:
        eng_b = badge("Offline", "slate")

    sess_b  = badge(session_label, session_var)
    lat_var = "green" if latency_ms < 300 else ("amber" if latency_ms < 800 else "red")
    lat_b   = badge(f"{latency_ms} ms", lat_var)

    st.markdown(f"""
    <div class="status-bar">
        {term_b}
        <div class="status-divider"></div>
        {eng_b}
        <div class="status-divider"></div>
        {sess_b}
        <div class="status-divider"></div>
        {lat_b}
        <div class="status-divider"></div>
        <span class="status-field"><strong>{now_eat}</strong></span>
    </div>
    """, unsafe_allow_html=True)

    # ── Page Header ─────────────────────────────────────────────────────
    st.markdown("## Trading Desk")

    # ── Metric Cards ────────────────────────────────────────────────────
    pnl_cls   = "mc-positive" if pnl > 0 else ("mc-negative" if pnl < 0 else "mc-neutral")
    dd_cls    = "mc-negative" if dd > 2.25 else ("mc-positive" if dd == 0 else "mc-neutral")
    eq_change = equity - balance

    def mc(label, value, sub=""):
        sub_html = f'<div class="mc-sub">{sub}</div>' if sub else ""
        return f"""
        <div class="metric-card">
            <div class="mc-label">{label}</div>
            <div class="mc-value">{value}</div>
            {sub_html}
        </div>"""

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(mc(
            "Equity",
            f"${equity:,.2f}" if online else "---",
            f'<span class="{"mc-positive" if eq_change>=0 else "mc-negative"}">'
            f'{"+" if eq_change>=0 else ""}{eq_change:,.2f} vs balance</span>' if online else ""
        ), unsafe_allow_html=True)
    with col2:
        st.markdown(mc(
            "Balance",
            f"${balance:,.2f}" if online else "---",
            "Account settled balance" if online else ""
        ), unsafe_allow_html=True)
    with col3:
        st.markdown(mc(
            "Floating P&L",
            f'<span class="{pnl_cls}">${pnl:+,.2f}</span>' if online else "---",
            "Open positions combined" if online else ""
        ), unsafe_allow_html=True)
    with col4:
        st.markdown(mc(
            "Daily Drawdown",
            f'<span class="{dd_cls}">${dd:.2f}</span>' if online else "---",
            f"Limit: ${dd_limit:.2f}  &nbsp;|&nbsp;  {(dd/dd_limit*100) if dd_limit else 0:.0f}% used" if online else ""
        ), unsafe_allow_html=True)

    st.markdown("")

    # ── Risk Gauge ──────────────────────────────────────────────────────
    ratio   = min(dd / dd_limit, 1.0) if dd_limit > 0 else 0.0
    pct     = ratio * 100
    if ratio >= 0.80:
        bar_color   = "#EF4444"
        risk_label  = "Critical"
        risk_color  = "#F87171"
    elif ratio >= 0.50:
        bar_color   = "#F59E0B"
        risk_label  = "Elevated"
        risk_color  = "#FBBF24"
    else:
        bar_color   = "#10B981"
        risk_label  = "Normal"
        risk_color  = "#34D399"

    st.markdown(f"""
    <div class="risk-panel">
        <div class="risk-header">
            <span class="risk-title">Daily Risk Budget</span>
            <span class="risk-reading" style="color:{risk_color};">
                {risk_label} &nbsp;|&nbsp; ${dd:.2f} / ${dd_limit:.2f} &nbsp;({pct:.0f}%)
            </span>
        </div>
        <div class="risk-bar-bg">
            <div class="risk-bar-fill" style="width:{pct:.2f}%; background:{bar_color};"></div>
        </div>
        <div class="risk-tiers">
            <span class="risk-tier-label">$0.00</span>
            <span class="risk-tier-label">$2.25 (50%)</span>
            <span class="risk-tier-label">$3.60 (80%)</span>
            <span class="risk-tier-label">${dd_limit:.2f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # CB alert banner
    if cb_active and cb_until:
        st.error(f"Circuit Breaker Active — trading halted until {cb_until[:16].replace('T', ' ')} UTC", icon=None)

    st.markdown("")

    # ── Instrument Cards ────────────────────────────────────────────────
    st.markdown('<div class="section-label">Market Instruments</div>', unsafe_allow_html=True)

    configs = query_api("configs") or []
    cfg_map = {c["symbol"]: c for c in configs}
    signals = query_api("signals") or {}

    def _tf_pill(tf_label: str, rec: str) -> str:
        rec_u = (rec or "NEUTRAL").upper()
        if "STRONG_BUY" in rec_u or "STRONG BUY" in rec_u:
            return f'<span class="tf-pill tf-buy tf-strong">{tf_label}: STRONG BUY</span>'
        if "BUY" in rec_u:
            return f'<span class="tf-pill tf-buy">{tf_label}: BUY</span>'
        if "STRONG_SELL" in rec_u or "STRONG SELL" in rec_u:
            return f'<span class="tf-pill tf-sell tf-strong">{tf_label}: STRONG SELL</span>'
        if "SELL" in rec_u:
            return f'<span class="tf-pill tf-sell">{tf_label}: SELL</span>'
        return f'<span class="tf-pill">{tf_label}: NEUTRAL</span>'

    def render_instrument(col, symbol: str, label: str, sessions: str, magic: int):
        sig_info   = signals.get(symbol, {})
        sig        = sig_info.get("signal", {})
        direction  = sig.get("direction", "NEUTRAL")
        in_session = sig_info.get("session_active", False)
        news_blk   = sig_info.get("news_blackout", False)
        reason     = sig.get("reason", "Awaiting signal alignment.")
        cfg        = cfg_map.get(symbol, {})
        is_active  = cfg.get("active", True)
        m15_rec    = sig_info.get("m15_recommendation", "")
        h1_rec     = sig_info.get("h1_recommendation", "")

        sess_b  = badge("In Session", "green") if in_session else badge("Off Session", "slate")
        news_b  = badge("News Blackout", "red") if news_blk else badge("News Clear", "green")
        act_b   = badge("Strategy On", "green") if is_active else badge("Strategy Off", "slate")
        if direction == "BUY":
            dir_b = badge("Signal: Buy", "green")
        elif direction == "SELL":
            dir_b = badge("Signal: Sell", "red")
        else:
            dir_b = badge("Signal: Neutral", "amber")

        tf_pills = _tf_pill("M15", m15_rec) + _tf_pill("H1", h1_rec)

        with col:
            st.markdown(f"""
            <div class="inst-card">
                <div class="inst-header">
                    <div>
                        <div class="inst-symbol">{label}</div>
                        <div class="inst-sub">Magic {magic} &nbsp;|&nbsp; {sessions}</div>
                    </div>
                    {dir_b}
                </div>
                <div class="inst-badges">{sess_b} {news_b} {act_b}</div>
                <div class="tf-row">{tf_pills}</div>
                <div class="inst-reason">{reason}</div>
            </div>
            """, unsafe_allow_html=True)

            # Quick-action buttons
            qa1, qa2, qa3 = st.columns(3)
            with qa1:
                if st.button("Force Scan", key=f"scan_{symbol}", use_container_width=True):
                    # Signals are re-evaluated on next engine tick — rerun refreshes
                    st.toast(f"{symbol}: scan requested.")
                    st.rerun()
            with qa2:
                lbl = "Disable" if is_active else "Enable"
                if st.button(lbl, key=f"toggle_{symbol}", use_container_width=True):
                    ok, _ = send_command("control/toggle", {"symbol": symbol, "active": not is_active})
                    if ok:
                        st.toast(f"{symbol} strategy {'disabled' if is_active else 'enabled'}.")
                        st.rerun()
            with qa3:
                if st.button("Close All", key=f"killasset_{symbol}", use_container_width=True):
                    ok, _ = send_command("control/emergency-stop")
                    if ok:
                        st.toast(f"{symbol}: all positions closed.")
                        st.rerun()

    col_a, col_b = st.columns(2)
    render_instrument(col_a, "XAUUSD", "XAUUSD — Gold",         "15:30 – 19:30 EAT",               100201)
    render_instrument(col_b, "USDJPY", "USDJPY — Dollar / Yen", "03:00 – 07:00 / 15:30 – 19:30 EAT", 100202)

    st.markdown("")

    # ── Tabbed Analytics Panel ──────────────────────────────────────────
    tab_pos, tab_perf, tab_hist, tab_logs = st.tabs([
        "Live Positions", "Performance", "Trade History", "Audit Logs"
    ])

    # ── TAB 1: Live Positions ────────────────────────────────────────────
    with tab_pos:
        positions = query_api("positions") or []
        if positions:
            df_pos = pd.DataFrame(positions)

            # Normalize side
            if "type" in df_pos.columns:
                df_pos["Side"] = df_pos["type"].apply(
                    lambda t: "BUY" if str(t) in ["0", "buy", "BUY"] else "SELL"
                )

            col_map = {
                "ticket": "Ticket", "symbol": "Symbol", "Side": "Side",
                "volume": "Lots", "price_open": "Entry", "sl": "SL",
                "tp": "TP", "profit": "P&L ($)", "magic": "Magic",
            }
            show_cols = [c for c in col_map if c in df_pos.columns]
            df_display = df_pos[show_cols].rename(columns=col_map).copy()

            # Highlight P&L
            def _style_pnl(val):
                try:
                    v = float(val)
                    return "color: #34D399" if v > 0 else ("color: #F87171" if v < 0 else "color: #64748B")
                except Exception:
                    return ""

            styled = df_display.style.applymap(_style_pnl, subset=["P&L ($)"] if "P&L ($)" in df_display.columns else [])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Close individual position
            st.markdown("")
            cp1, cp2, cp3 = st.columns([2, 1, 1])
            with cp1:
                tickets = [p["ticket"] for p in positions if "ticket" in p]
                if tickets:
                    sel = st.selectbox("Select ticket", tickets, key="close_sel", label_visibility="collapsed")
            with cp2:
                if st.button("Close Ticket", use_container_width=True, key="close_ticket_btn"):
                    ok, res = send_command("control/close-position", {"ticket": sel})
                    st.toast(f"#{sel} closed." if ok else f"Failed: {res}")
                    if ok:
                        st.rerun()
            with cp3:
                if st.button("Close All Positions", use_container_width=True, key="close_all_main"):
                    ok, _ = send_command("control/emergency-stop")
                    if ok:
                        st.toast("All bot positions closed.")
                        st.rerun()
        else:
            st.markdown('<div class="empty-state">No open bot positions. Engine is monitoring entry criteria.</div>',
                        unsafe_allow_html=True)

    # ── TAB 2: Performance Telemetry ─────────────────────────────────────
    with tab_perf:
        try:
            import plotly.graph_objects as go
            PLOTLY_OK = True
        except ImportError:
            PLOTLY_OK = False

        total_trades = perf.get("total_trades", 0)
        win_rate     = perf.get("win_rate_pct", 0.0)
        pf           = perf.get("profit_factor", 0.0)
        sharpe       = perf.get("sharpe_proxy", 0.0)

        # Stat row
        st.markdown(f"""
        <div class="perf-stat-row">
            <div class="perf-stat">
                <div class="perf-stat-label">Total Trades</div>
                <div class="perf-stat-value">{total_trades}</div>
            </div>
            <div class="perf-stat">
                <div class="perf-stat-label">Win Rate</div>
                <div class="perf-stat-value" style="color:{'#34D399' if win_rate>=50 else '#F87171'}">
                    {win_rate:.1f}%
                </div>
            </div>
            <div class="perf-stat">
                <div class="perf-stat-label">Profit Factor</div>
                <div class="perf-stat-value" style="color:{'#34D399' if pf>=1 else '#F87171'}">
                    {pf:.2f}
                </div>
            </div>
            <div class="perf-stat">
                <div class="perf-stat-label">Sharpe (proxy)</div>
                <div class="perf-stat-value" style="color:{'#34D399' if sharpe>=0 else '#F87171'}">
                    {sharpe:.2f}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Pull closed trades for charting
        trades = query_api("trades") or []
        closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]

        if closed and PLOTLY_OK:
            df_closed = pd.DataFrame(closed).sort_values("timestamp", na_position="last")
            pnls = df_closed["pnl"].astype(float).tolist()
            cumulative = []
            running = 0.0
            for p in pnls:
                running += p
                cumulative.append(round(running, 4))

            # Equity Curve
            eq_fig = go.Figure()
            eq_fig.add_trace(go.Scatter(
                y=cumulative,
                mode="lines",
                line=dict(color="#38BDF8", width=2),
                fill="tozeroy",
                fillcolor="rgba(56,189,248,0.06)",
                name="Cumulative P&L",
                hovertemplate="Trade #%{x}<br>Cum P&L: $%{y:.2f}<extra></extra>",
            ))
            eq_fig.update_layout(
                title=dict(text="Cumulative P&L Curve", font=dict(size=12, color="#64748B"), x=0),
                plot_bgcolor="#060B12",
                paper_bgcolor="#0D1420",
                font=dict(family="JetBrains Mono", size=10, color="#64748B"),
                margin=dict(l=12, r=12, t=36, b=12),
                xaxis=dict(showgrid=False, zeroline=False, color="#334155"),
                yaxis=dict(showgrid=True, gridcolor="#0F1A27", zeroline=True,
                           zerolinecolor="#1E293B", color="#334155"),
                height=220,
            )
            st.plotly_chart(eq_fig, use_container_width=True, config={"displayModeBar": False})

            # P&L Distribution
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Histogram(
                x=pnls,
                nbinsx=20,
                marker_color="#6366F1",
                opacity=0.8,
                name="P&L Distribution",
            ))
            hist_fig.update_layout(
                title=dict(text="Trade P&L Distribution", font=dict(size=12, color="#64748B"), x=0),
                plot_bgcolor="#060B12",
                paper_bgcolor="#0D1420",
                font=dict(family="JetBrains Mono", size=10, color="#64748B"),
                margin=dict(l=12, r=12, t=36, b=12),
                xaxis=dict(showgrid=False, zeroline=True, zerolinecolor="#1E293B",
                           color="#334155", title=dict(text="P&L ($)", font=dict(size=10))),
                yaxis=dict(showgrid=True, gridcolor="#0F1A27", color="#334155"),
                height=200,
            )
            st.plotly_chart(hist_fig, use_container_width=True, config={"displayModeBar": False})

        elif not PLOTLY_OK:
            st.info("Install plotly (`pip install plotly`) to enable charts.")
        else:
            st.markdown('<div class="empty-state">No closed trades yet. Charts render after first completed trade.</div>',
                        unsafe_allow_html=True)

    # ── TAB 3: Trade History ─────────────────────────────────────────────
    with tab_hist:
        trades = query_api("trades") or []
        if trades:
            df_t = pd.DataFrame(trades)
            col_order = ["ticket", "symbol", "action", "volume", "open_price",
                         "close_price", "pnl", "status", "timestamp"]
            valid = [c for c in col_order if c in df_t.columns]
            df_t_show = df_t[valid].copy()

            def _style_row(row):
                styles = [""] * len(row)
                if "pnl" in row.index:
                    try:
                        v = float(row["pnl"])
                        color = "#34D399" if v > 0 else ("#F87171" if v < 0 else "#64748B")
                        styles[row.index.get_loc("pnl")] = f"color:{color}"
                    except Exception:
                        pass
                return styles

            st.dataframe(
                df_t_show.style.apply(_style_row, axis=1),
                use_container_width=True, hide_index=True
            )
        else:
            st.markdown('<div class="empty-state">No trade history recorded.</div>', unsafe_allow_html=True)

    # ── TAB 4: Audit Logs ────────────────────────────────────────────────
    with tab_logs:
        events = query_api("events") or []
        if events:
            lines = []
            for ev in events[:60]:
                ts  = (ev.get("timestamp") or "")[:19].replace("T", " ")
                lvl = (ev.get("log_level") or "INFO").upper()
                mod = (ev.get("module") or "System")[:14]
                msg = ev.get("message", "")

                if lvl in ["ERROR", "CRITICAL"]:
                    css = "log-error"
                elif lvl == "WARNING":
                    css = "log-warning"
                else:
                    css = "log-info"

                lines.append(
                    f'<span class="{css}">'
                    f'[{ts}] {lvl:8s}  {mod:14s}  {msg}'
                    f'</span>'
                )

            log_html = "\n".join(lines)
            st.markdown(
                f'<div class="log-box"><pre>{log_html}</pre></div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown('<div class="empty-state">No audit events recorded.</div>', unsafe_allow_html=True)


render_dashboard()
