"""
Audit and System Logs Tab for Piploci Monitoring Dashboard.
Renders audit logs, circuit breaker triggers, and risk protection alerts.
"""

import streamlit as st
import pandas as pd
from typing import List, Dict, Any


def render_logs_tab(events: List[Dict[str, Any]]):
    """Renders the System Logs tab."""
    if not events:
        st.info("No system events recorded yet.")
        return

    df = pd.DataFrame(events)
    cols_to_show = ["timestamp", "log_level", "module", "message"]
    available_cols = [c for c in cols_to_show if c in df.columns]
    
    st.dataframe(df[available_cols], use_container_width=True, hide_index=True)
