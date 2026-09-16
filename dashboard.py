"""
Piploci Trading Desk — Main Streamlit Entry Wrapper.
Imports and delegates execution to the modular dashboard orchestrator in bot/dashboard/app.py.
"""

import os
import sys

# Ensure root directory is in sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from bot.dashboard.app import run_dashboard

run_dashboard()
