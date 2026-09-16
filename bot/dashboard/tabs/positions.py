"""
Live Positions Tab for Piploci Monitoring Dashboard.
Lists open bot trades with strict Magic Number isolation, floating profits,
trailing-stop distance and dynamic ATR breakeven progress bars.
"""

import streamlit as st
from typing import List, Dict, Any
from bot.dashboard.api_client import send_command

# Pip value map per symbol (price per 1 point move, 0.01 lot)
_PIP_POINT_MAP = {
    "XAUUSD": 0.01,   # Gold: 1 point = $0.01 per 0.01 lot
    "USDJPY": 0.001,  # USDJPY: 1 pip ≈ 0.001 per 0.01 lot
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
}

# ATR SL multipliers from config (default fallback)
_ATR_SL_MULT = {"XAUUSD": 1.5, "USDJPY": 1.2}
_ATR_TP_MULT = {"XAUUSD": 3.5, "USDJPY": 3.0}
_WICK_RATIO  = {"XAUUSD": 0.55, "USDJPY": 0.45}


def _progress_color(pct: float) -> str:
    """Return a CSS color based on progress percentage."""
    if pct >= 75:
        return "#34D399"   # green — close to TP
    elif pct >= 40:
        return "#FBBF24"   # amber — in profit zone
    else:
        return "#60A5FA"   # blue — early stage


def _sl_distance_pct(price_open: float, current_sl: float, p_type: str) -> float:
    """
    Returns what fraction (0-100%) of the original SL-to-TP range
    has been recovered by the current trailing-stop placement.
    """
    if price_open <= 0 or current_sl <= 0:
        return 0.0
    if p_type == "BUY":
        # SL starts below open; as it rises toward open the % recovered grows
        dist = price_open - current_sl
    else:
        dist = current_sl - price_open
    if dist <= 0:
        return 100.0  # SL is above/at open — fully protected
    return 0.0  # Still below entry, no breakeven reached


def _tp_progress_pct(price_open: float, current_price: float, tp: float, p_type: str) -> float:
    """Returns what % of the way from entry to TP the current price is (0-100)."""
    if tp <= 0 or price_open <= 0:
        return 0.0
    if p_type == "BUY":
        total = tp - price_open
        moved = current_price - price_open
    else:
        total = price_open - tp
        moved = price_open - current_price
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (moved / total) * 100.0))


def render_positions_tab(positions: List[Dict[str, Any]]):
    """Renders the Live Positions tab with enhanced trailing-stop & ATR progress visuals."""
    st.markdown(
        '<div style="font-family: \'Inter\', sans-serif; font-size: 0.85rem; font-weight: 700; '
        'color: #F1F5F9; margin-bottom: 8px;">Open Positions</div>',
        unsafe_allow_html=True
    )

    if not positions:
        st.info("No active bot positions currently open.")
        return

    # ── Aggregate summary bar ─────────────────────────────────────────────────
    total_pnl   = sum(p.get("profit", 0.0) for p in positions)
    total_vol   = sum(p.get("volume", 0.0) for p in positions)
    pnl_color   = "#34D399" if total_pnl >= 0 else "#F87171"
    pnl_sign    = "+" if total_pnl >= 0 else ""

    sm1, sm2, sm3 = st.columns(3)
    sm1.metric("Open Positions",  len(positions))
    sm2.metric("Total Lots",      f"{total_vol:.2f}")
    sm3.metric("Floating P&L",    f"{pnl_sign}${total_pnl:,.2f}",
               delta=f"{pnl_sign}${total_pnl:,.2f}")

    st.markdown("<hr style='border-color: #1E293B; margin: 6px 0 14px 0;'>", unsafe_allow_html=True)

    # ── Per-position cards ────────────────────────────────────────────────────
    for p in positions:
        ticket      = p.get("ticket", 0)
        symbol      = p.get("symbol", "")
        p_type      = p.get("type", "BUY")
        volume      = p.get("volume", 0.01)
        price_open  = p.get("price_open", 0.0)
        current_px  = p.get("current_price", price_open)   # server may omit; fall back to open
        sl          = p.get("sl", 0.0)
        tp          = p.get("tp", 0.0)
        profit      = p.get("profit", 0.0)
        magic       = p.get("magic", 0)

        pnl_col = "#34D399" if profit >= 0 else "#F87171"
        pnl_sign_p = "+" if profit >= 0 else ""

        # Trailing-stop distance from current price (in points)
        if sl > 0 and current_px > 0:
            sl_dist_pts = abs(current_px - sl)
        else:
            sl_dist_pts = 0.0

        # % progress toward TP based on current price vs open
        tp_pct = _tp_progress_pct(price_open, current_px, tp, p_type)
        bar_color = _progress_color(tp_pct)

        # Breakeven indicator: has SL been moved above/to entry?
        if p_type == "BUY":
            is_breakeven = sl >= price_open
        else:
            is_breakeven = sl <= price_open and sl > 0

        breakeven_badge = (
            '<span style="background:#10B981;color:#fff;font-size:0.62rem;'
            'padding:1px 5px;border-radius:3px;margin-left:6px;">✓ BE</span>'
            if is_breakeven else ""
        )
        trailing_badge = (
            '<span style="background:#3B82F6;color:#fff;font-size:0.62rem;'
            'padding:1px 5px;border-radius:3px;margin-left:4px;">↗ TSL</span>'
            if sl > 0 else ""
        )

        # Card container
        st.markdown(
            f"""<div style="
                background: linear-gradient(135deg, rgba(30,41,59,0.9) 0%, rgba(15,23,42,0.9) 100%);
                border: 1px solid #1E293B; border-radius: 10px;
                padding: 14px 18px 10px 18px; margin-bottom: 12px;
                box-shadow: 0 2px 12px rgba(0,0,0,0.3);">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <div>
                        <span style="font-size:0.9rem;font-weight:700;color:#F1F5F9;">
                            #{ticket} &nbsp;
                        </span>
                        <span style="font-size:0.85rem;font-weight:600;color:#06B6D4;">{symbol}</span>
                        <span style="font-size:0.78rem;color:#94A3B8;margin-left:6px;">{p_type} · {volume:.2f} lots</span>
                        {breakeven_badge}
                        {trailing_badge}
                    </div>
                    <div style="font-size:1.0rem;font-weight:700;color:{pnl_col};">
                        {pnl_sign_p}${profit:,.2f}
                    </div>
                </div>

                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;
                            font-size:0.73rem;color:#94A3B8;margin-bottom:10px;">
                    <div><div style="color:#64748B;font-size:0.65rem;">OPEN</div>
                         <div style="color:#E2E8F0;font-weight:600;">{price_open:.3f}</div></div>
                    <div><div style="color:#64748B;font-size:0.65rem;">STOP-LOSS</div>
                         <div style="color:#F87171;font-weight:600;">{sl:.3f if sl else '—'}</div></div>
                    <div><div style="color:#64748B;font-size:0.65rem;">TAKE-PROFIT</div>
                         <div style="color:#34D399;font-weight:600;">{tp:.3f if tp else '—'}</div></div>
                    <div><div style="color:#64748B;font-size:0.65rem;">SL DISTANCE</div>
                         <div style="color:#FBBF24;font-weight:600;">{sl_dist_pts:.2f} pts</div></div>
                </div>

                <div style="margin-bottom:6px;">
                    <div style="display:flex;justify-content:space-between;
                                font-size:0.65rem;color:#64748B;margin-bottom:3px;">
                        <span>TP Progress</span>
                        <span style="color:{bar_color};font-weight:700;">{tp_pct:.1f}%</span>
                    </div>
                    <div style="background:#0F172A;border-radius:4px;height:6px;overflow:hidden;">
                        <div style="background:{bar_color};width:{tp_pct:.1f}%;height:100%;
                                    border-radius:4px;transition:width 0.5s ease;"></div>
                    </div>
                </div>

                <div style="font-size:0.62rem;color:#475569;margin-top:4px;">Magic: {magic}</div>
            </div>""",
            unsafe_allow_html=True
        )

        # Manual close button
        if st.button(f"🔴 Close #{ticket}", key=f"close_pos_{ticket}", use_container_width=False):
            res = send_command("/control/close-position", {"ticket": ticket})
            if res:
                st.success(f"Position #{ticket} closed.")
                st.rerun()
            else:
                st.error(f"Failed to close position #{ticket}. Check server logs.")
