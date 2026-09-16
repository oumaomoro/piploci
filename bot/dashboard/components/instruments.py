"""
Instrument Cards Component for Piploci Monitoring Dashboard.
Renders Gold (XAUUSD) and USDJPY technical analysis consensus, news blackout, and session health.
"""

import streamlit as st
from typing import Dict, Any, List, Optional
from bot.dashboard.api_client import send_command


def render_instruments(configs: List[Dict[str, Any]], signals_data: Optional[Dict[str, Any]]):
    """Renders the side-by-side asset monitor cards."""
    st.markdown('<div style="font-family: \'Inter\', sans-serif; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; color: #94A3B8; letter-spacing: 0.08em; margin: 16px 0 10px 0;">Asset Strategy Monitors</div>', unsafe_allow_html=True)
    symbol_configs = {}
    if isinstance(configs, list):
        for c in configs:
            if isinstance(c, dict) and "symbol" in c:
                symbol_configs[c["symbol"]] = c
    
    symbols = list(symbol_configs.keys()) if symbol_configs else ["XAUUSD", "USDJPY", "EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]
    
    # Process symbols in rows of 4
    for i in range(0, len(symbols), 4):
        row_symbols = symbols[i:i+4]
        cols = st.columns(4)
        
        for idx, sym in enumerate(row_symbols):
            with cols[idx]:
                cfg = symbol_configs.get(sym, {})
                is_active = cfg.get("active", True)
                
                sym_sig = signals_data.get(sym, {}) if signals_data else {}
                sig_info = sym_sig.get("signal", {})
                direction = sig_info.get("direction", "NEUTRAL")
                is_aligned = sig_info.get("is_aligned", False)
                reason = sig_info.get("reason", "Waiting for consensus")
                
                in_session = sym_sig.get("session_active", False)
                is_blackout = sym_sig.get("news_blackout", False)

                # Compact Direction Badge
                if direction == "BUY":
                    dir_badge = '<span style="color:#4ADE80; font-weight:bold; font-size: 0.7rem;">BUY</span>'
                elif direction == "SELL":
                    dir_badge = '<span style="color:#F87171; font-weight:bold; font-size: 0.7rem;">SELL</span>'
                else:
                    dir_badge = '<span style="color:#94A3B8; font-weight:bold; font-size: 0.7rem;">NEUTRAL</span>'

                # Compact Status Indicator
                if not is_active:
                    status_indicator = '<div style="width:8px; height:8px; border-radius:50%; background:#F59E0B;" title="Paused"></div>'
                elif is_blackout:
                    status_indicator = '<div style="width:8px; height:8px; border-radius:50%; background:#EF4444;" title="News Blackout"></div>'
                elif not in_session:
                    status_indicator = '<div style="width:8px; height:8px; border-radius:50%; background:#64748B;" title="Off-Session"></div>'
                elif is_aligned:
                    status_indicator = '<div style="width:8px; height:8px; border-radius:50%; background:#10B981;" title="Active Scan"></div>'
                else:
                    status_indicator = '<div style="width:8px; height:8px; border-radius:50%; background:#06B6D4;" title="Monitoring"></div>'

                m15_rec = sig_info.get("m15_recommendation", "—")
                h1_rec  = sig_info.get("h1_recommendation",  "—")
                rsi_val = sig_info.get("rsi", None)
                atr_val = sig_info.get("atr_14", None)

                # Format RSI with color coding
                if rsi_val is not None:
                    if rsi_val >= 70:
                        rsi_html = f'<span style="color:#F87171;">{rsi_val:.1f}</span>'
                    elif rsi_val <= 30:
                        rsi_html = f'<span style="color:#4ADE80;">{rsi_val:.1f}</span>'
                    else:
                        rsi_html = f'<span style="color:#94A3B8;">{rsi_val:.1f}</span>'
                else:
                    rsi_html = '<span style="color:#64748B;">—</span>'

                atr_display = f"{atr_val:.4f}" if atr_val and atr_val > 0 else "—"

                # Confluence bar (M15 + H1 + RSI + ATR)
                def _rec_color(r):
                    r = str(r).upper()
                    if "STRONG_BUY" in r: return "#4ADE80"
                    if "BUY" in r: return "#86EFAC"
                    if "STRONG_SELL" in r: return "#F87171"
                    if "SELL" in r: return "#FCA5A5"
                    return "#64748B"

                confluence_html = (
                    f'<div style="font-family:\'Inter\',sans-serif; font-size:0.55rem; margin-top:5px;'
                    f'display:flex; gap:4px; flex-wrap:wrap;">'
                    f'<span style="background:rgba(0,0,0,0.2);padding:1px 4px;border-radius:3px;'
                    f'color:{_rec_color(m15_rec)};">M15:{m15_rec.replace("_"," ")}</span>'
                    f'<span style="background:rgba(0,0,0,0.2);padding:1px 4px;border-radius:3px;'
                    f'color:{_rec_color(h1_rec)};">H1:{h1_rec.replace("_"," ")}</span>'
                    f'<span style="background:rgba(0,0,0,0.2);padding:1px 4px;border-radius:3px;'
                    f'color:#94A3B8;">RSI:{rsi_html}</span>'
                    f'<span style="background:rgba(0,0,0,0.2);padding:1px 4px;border-radius:3px;'
                    f'color:#06B6D4;">ATR:{atr_display}</span>'
                    f'</div>'
                )

                header_html = f"""
                <div style="background: rgba(30, 41, 59, 0.4); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 6px; padding: 10px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div style="display: flex; align-items: center; gap: 6px;">
                            {status_indicator}
                            <span style="font-family: 'Inter', sans-serif; font-weight: 700; font-size: 0.85rem; color: #F8FAFC;">{sym}</span>
                        </div>
                        {dir_badge}
                    </div>
                    <div style="font-family: 'Inter', sans-serif; font-size: 0.6rem; color: #CBD5E1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="{reason}">
                        {reason}
                    </div>
                    {confluence_html}
                """
                st.markdown(header_html, unsafe_allow_html=True)

                # Tiny toggle button
                toggle_label = "⏸ Pause" if is_active else "▶ Resume"
                if st.button(toggle_label, key=f"toggle_{sym}", use_container_width=True):
                    res = send_command("/control/toggle", {"symbol": sym, "active": not is_active})
                    if res:
                        st.toast(f"{sym} {'enabled' if not is_active else 'paused'}")
                        st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)

