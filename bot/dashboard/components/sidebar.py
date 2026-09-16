"""
Sidebar Component for Piploci Monitoring Dashboard.
Renders master emergency controls, connection endpoints, and symbol risk configurator.
"""

import streamlit as st
from typing import Dict, Any, List
from bot.dashboard.api_client import get_api_base, send_command


def render_sidebar(configs: List[Dict[str, Any]], status_data: Dict[str, Any]):
    """Renders the left navigation sidebar with risk controls and configuration forms."""
    with st.sidebar:
        st.markdown("""
        <div style="padding: 6px 0 16px 0;">
            <div style="font-family: 'Inter', sans-serif; font-size: 1.15rem; font-weight: 700; color: #F8FAFC; letter-spacing: -0.02em;">
                ◆ Piploci Trading Desk
            </div>
            <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; color: #06B6D4; margin-top: 2px;">
                QUANTITATIVE EXECUTION GATEWAY
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── Master Controls ───────────────────────────────────────────────────
        st.markdown("### Emergency Controls")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🚨 KILL", help="Closes ALL bot positions and halts trading", use_container_width=True):
                res = send_command("/control/emergency-stop")
                if res:
                    st.error("Emergency Stop Activated!")
                    st.rerun()

        with col2:
            if st.button("▶ RESUME", help="Resumes normal trading execution", use_container_width=True):
                res = send_command("/control/resume")
                if res:
                    st.success("Trading Resumed!")
                    st.rerun()

        st.divider()

        # ── Gateway Settings ──────────────────────────────────────────────────
        with st.expander("🌐 Gateway Connection", expanded=False):
            curr_base = get_api_base()
            st.caption(f"Current Base: `{curr_base}`")
            new_base = st.text_input("API Base URL", value=curr_base, key="input_api_base")
            if st.button("Apply URL", key="btn_apply_url"):
                st.session_state["api_base_override"] = new_base
                st.session_state["jwt_token"] = None
                st.success("Updated API Base.")
                st.rerun()

        st.divider()

        # ── Symbol Parameter Configurator ─────────────────────────────────────
        valid_configs = []
        if isinstance(configs, list):
            valid_configs = [c for c in configs if isinstance(c, dict) and "symbol" in c]
            
        with st.expander("⚙️ Risk Configurator", expanded=False):
            if valid_configs:
                sym_list = [c["symbol"] for c in valid_configs]
                selected_sym = st.selectbox("Select Asset", options=sym_list, key="cfg_sym_select")
                curr_cfg = next((c for c in valid_configs if c["symbol"] == selected_sym), valid_configs[0])

                with st.form(key=f"form_cfg_{selected_sym}"):
                    c_active = st.checkbox("Active Scanning", value=curr_cfg.get("active", True))
                    c_risk = st.number_input("Per-Trade Risk (%)", min_value=0.1, max_value=5.0, value=float(curr_cfg.get("risk_percent", 1.0)), step=0.1)
                    c_spread = st.number_input("Max Spread Points", min_value=1.0, max_value=200.0, value=float(curr_cfg.get("max_spread", 35.0)), step=1.0)
                    c_session = st.text_input("Session Window", value=str(curr_cfg.get("session_window", "")))
                    
                    submitted = st.form_submit_button("Save Changes", use_container_width=True)
                    if submitted:
                        payload = {
                            "symbol": selected_sym,
                            "active": c_active,
                            "risk_percent": c_risk,
                            "max_spread": c_spread,
                            "session_window": c_session,
                        }
                        res = send_command("/configs/update", payload)
                        if res:
                            st.toast(f"Configuration saved for {selected_sym}!")
                            st.rerun()
                        else:
                            st.error("Failed to update config. Check API connection.")

        st.divider()
        st.caption("Piploci Modular Architecture v2.0 • 2026")
