"""
WebSocket Connection Manager and Telemetry Broadcaster for Piploci.
Streams real-time market data, equity metrics, and order alerts to connected UI clients.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Dict, List, Any

from fastapi import WebSocket

try:
    from bot.config import DAILY_DRAWDOWN_LIMIT_USD
    from bot.engine.core import bot_engine
    from bot.signals.news import news_filter
    from bot.signals.tradingview import tv_analyzer
except ImportError:
    from config import DAILY_DRAWDOWN_LIMIT_USD
    from bot_engine import bot_engine
    from news_filter import news_filter
    from tradingview_ta_module import tv_analyzer

logger = logging.getLogger("WebSocketManager")


class WebSocketManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"New WebSocket client connected. Active clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active clients: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        json_str = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(json_str)
            except Exception:
                self.disconnect(connection)


ws_manager = WebSocketManager()


def on_engine_event(event: Dict[str, Any]):
    """Bridge engine events to WebSocket broadcast."""
    asyncio.create_task(ws_manager.broadcast(event))


# Register callback with bot engine
bot_engine.register_broadcast_callback(on_engine_event)


async def telemetry_broadcaster():
    """Periodically pushes live account equity, prices, and status every 1.5s via WebSocket."""
    while True:
        try:
            if ws_manager.active_connections and bot_engine.mt5_client:
                acct = bot_engine.mt5_client.account_info()
                balance = getattr(acct, "balance", 1000.0) if acct else 1000.0
                equity = getattr(acct, "equity", balance) if acct else balance
                profit = getattr(acct, "profit", 0.0) if acct else 0.0
                drawdown = max(0.0, bot_engine.starting_daily_balance - equity)

                tick_gold = bot_engine.mt5_client.symbol_info_tick("XAUUSD")
                tick_jpy = bot_engine.mt5_client.symbol_info_tick("USDJPY")

                # Get open bot positions
                raw_pos = bot_engine.get_bot_positions()
                positions = []
                for p in raw_pos:
                    positions.append({
                        "ticket": getattr(p, "ticket", 0),
                        "symbol": getattr(p, "symbol", ""),
                        "type": "BUY" if getattr(p, "type", 0) == 0 else "SELL",
                        "volume": getattr(p, "volume", 0.01),
                        "price_open": getattr(p, "price_open", 0.0),
                        "sl": getattr(p, "sl", 0.0),
                        "tp": getattr(p, "tp", 0.0),
                        "profit": getattr(p, "profit", 0.0),
                        "magic": getattr(p, "magic", 0),
                    })

                # Quick consensus & news shield flags
                sig_gold = tv_analyzer.cached_signals.get("XAUUSD", {})
                sig_jpy = tv_analyzer.cached_signals.get("USDJPY", {})

                is_blackout_gold, _ = await news_filter.is_news_blackout("XAUUSD")
                is_blackout_jpy, _ = await news_filter.is_news_blackout("USDJPY")

                payload = {
                    "type": "TELEMETRY",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": {
                        "balance": round(balance, 2),
                        "equity": round(equity, 2),
                        "floating_pnl": round(profit, 2),
                        "starting_daily_balance": round(bot_engine.starting_daily_balance, 2),
                        "daily_drawdown": round(drawdown, 2),
                        "drawdown_limit": DAILY_DRAWDOWN_LIMIT_USD,
                        "state": bot_engine.state,
                        "terminal_connected": getattr(bot_engine, "terminal_connected", False),
                        "ticks": {
                            "XAUUSD": {"bid": getattr(tick_gold, "bid", 0.0), "ask": getattr(tick_gold, "ask", 0.0)} if tick_gold else {},
                            "USDJPY": {"bid": getattr(tick_jpy, "bid", 0.0), "ask": getattr(tick_jpy, "ask", 0.0)} if tick_jpy else {},
                        },
                        "signals": {
                            "XAUUSD": sig_gold.get("overall_status", "PENDING"),
                            "USDJPY": sig_jpy.get("overall_status", "PENDING"),
                        },
                        "news_blackout": {
                            "XAUUSD": is_blackout_gold,
                            "USDJPY": is_blackout_jpy,
                        },
                        "positions": positions,
                        "compounding_tier": bot_engine.evaluate_compounding_tier(
                            balance=balance,
                            equity=equity,
                            floating_drawdown=drawdown
                        ),
                    }
                }
                await ws_manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Telemetry broadcaster error: {e}")

        await asyncio.sleep(1.5)
