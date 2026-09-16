"""
Data inspection routes (positions, trades, events, signals).
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

try:
    from bot.database import (
        get_db,
        TradeLogModel,
        SystemEventModel,
    )
    from bot.engine.core import bot_engine
    from bot.signals.news import news_filter
    from bot.signals.tradingview import tv_analyzer
except ImportError:
    from database import (
        get_db,
        TradeLogModel,
        SystemEventModel,
    )
    from bot_engine import bot_engine
    from news_filter import news_filter
    from tradingview_ta_module import tv_analyzer

logger = logging.getLogger("DataRouter")
router = APIRouter(prefix="/api/v1", tags=["Data"])


@router.get("/positions")
async def get_open_positions():
    """Returns open positions exclusively filtered by bot Magic Numbers."""
    raw_pos = bot_engine.get_bot_positions()
    res = []
    for p in raw_pos:
        res.append({
            "ticket": getattr(p, "ticket", 0),
            "symbol": getattr(p, "symbol", ""),
            "type": "BUY" if getattr(p, "type", 0) == 0 else "SELL",
            "volume": getattr(p, "volume", 0.01),
            "price_open": getattr(p, "price_open", 0.0),
            "sl": getattr(p, "sl", 0.0),
            "tp": getattr(p, "tp", 0.0),
            "profit": getattr(p, "profit", 0.0),
            "magic": getattr(p, "magic", 0),
            "time": getattr(p, "time", 0),
        })
    return res


@router.get("/trades")
async def get_trade_history(limit: int = 50, db: Session = Depends(get_db)):
    """Returns past trade logs."""
    logs = db.query(TradeLogModel).order_by(TradeLogModel.timestamp.desc()).limit(limit).all()
    return [l.to_dict() for l in logs]


@router.get("/events")
async def get_system_events(limit: int = 50, db: Session = Depends(get_db)):
    """Returns recent system logs and telemetry events."""
    events = db.query(SystemEventModel).order_by(SystemEventModel.timestamp.desc()).limit(limit).all()
    return [e.to_dict() for e in events]


@router.get("/signals")
async def get_market_signals():
    """Returns TradingView consensus and News blackout status for all symbols."""
    res = {}
    from bot.config import SYMBOL_CONFIGS
    for s in SYMBOL_CONFIGS.keys():
        sig = tv_analyzer.get_aligned_signal(s)
        is_blk, blk_msg = await news_filter.is_news_blackout(s)
        in_sess, sess_msg = bot_engine.is_within_trading_session(s)
        
        cfg = SYMBOL_CONFIGS.get(s, {})
        sl_mult = cfg.get("atr_sl_multiplier", 1.5)
        tp_mult = cfg.get("atr_tp_multiplier", 3.0)
        
        price = 0.0
        if bot_engine.mt5_client:
            tick = bot_engine.mt5_client.symbol_info_tick(s)
            if tick:
                price = getattr(tick, "bid", 0.0)
                
        if price <= 0:
            price = sig.get("m15", {}).get("close", 0.0)
            
        atr = bot_engine.calculate_atr(s, cfg.get("atr_period", 14))
        sl_dist = atr * sl_mult
        tp_dist = atr * tp_mult
        
        sig["potential_buy_sl"] = round(price - sl_dist, 3) if price else 0.0
        sig["potential_buy_tp"] = round(price + tp_dist, 3) if price else 0.0
        sig["potential_sell_sl"] = round(price + sl_dist, 3) if price else 0.0
        sig["potential_sell_tp"] = round(price - tp_dist, 3) if price else 0.0
        sig["current_price"] = round(price, 3) if price else 0.0

        res[s] = {
            "signal": sig,
            "news_blackout": is_blk,
            "news_message": blk_msg,
            "session_active": in_sess,
            "session_message": sess_msg,
        }
    return res
