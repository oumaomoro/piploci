"""
Trade History Tab for Piploci Monitoring Dashboard.
Renders tabular historical trades with execution fill details, exit prices, and PnL.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict, Any


def render_history_tab(trades: List[Dict[str, Any]]):
    """Renders the Trade History tab."""
    if not trades:
        st.info("No recorded trades in database history.")
        return

    df = pd.DataFrame(trades)
    
    # Reorder and format columns
    cols_to_show = ["ticket", "symbol", "action", "volume", "open_price", "close_price", "pnl", "status", "timestamp", "notes"]
    available_cols = [c for c in cols_to_show if c in df.columns]
    df_display = df[available_cols].copy()

    if "pnl" in df_display.columns:
        df_display["pnl"] = df_display["pnl"].apply(lambda v: f"${v:,.2f}" if pd.notnull(v) else "$0.00")

    st.dataframe(df_display, use_container_width=True, hide_index=True)
