"""
Dashboard UI Tabs.
"""

from bot.dashboard.tabs.positions import render_positions_tab
from bot.dashboard.tabs.performance import render_performance_tab
from bot.dashboard.tabs.history import render_history_tab
from bot.dashboard.tabs.logs import render_logs_tab
from bot.dashboard.tabs.signals import render_signals_tab

__all__ = [
    "render_positions_tab",
    "render_performance_tab",
    "render_history_tab",
    "render_logs_tab",
    "render_signals_tab",
]
