"""
Piploci Trading Engine Subpackage.
Exposes BotEngine and singleton bot_engine.
"""

from bot.engine.core import BotEngine, bot_engine

__all__ = ["BotEngine", "bot_engine"]
