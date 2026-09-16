"""
Status, authentication, and configuration inspection routes.
"""

import time
from datetime import datetime, timezone
import math
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

try:
    from bot.config import (
        DEFAULT_ADMIN_USER,
        DEFAULT_ADMIN_PASSWORD,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        DAILY_DRAWDOWN_LIMIT_USD,
        ALLOWED_MAGIC_NUMBERS,
    )
    from bot.database import get_db, ConfigModel, TradeLogModel, SystemEventModel, SignalAuditModel
    from bot.engine.core import bot_engine
    from bot.signals.news import news_filter
    from bot.signals.tradingview import tv_analyzer
    from bot.api.schemas import TokenResponse, LoginRequest
    from bot.api.auth import create_access_token
except ImportError:
    from config import (
        DEFAULT_ADMIN_USER,
        DEFAULT_ADMIN_PASSWORD,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        DAILY_DRAWDOWN_LIMIT_USD,
        ALLOWED_MAGIC_NUMBERS,
    )
    from database import get_db, ConfigModel, TradeLogModel, SystemEventModel, SignalAuditModel
    from bot_engine import bot_engine
    from news_filter import news_filter
    from tradingview_ta_module import tv_analyzer
    from bot.api.schemas import TokenResponse, LoginRequest
    from bot.api.auth import create_access_token

logger = logging.getLogger("StatusRouter")
router = APIRouter(tags=["Status & Auth"])

_PERF_CACHE = {"timestamp": 0.0, "data": {}}


@router.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """OAuth2 compatible token login."""
    if form_data.username == DEFAULT_ADMIN_USER and form_data.password == DEFAULT_ADMIN_PASSWORD:
        token = create_access_token(data={"sub": form_data.username})
        return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/api/v1/auth/login-json", response_model=TokenResponse)
async def login_json(payload: LoginRequest):
    """JSON login for mobile and REST clients."""
    if payload.username == DEFAULT_ADMIN_USER and payload.password == DEFAULT_ADMIN_PASSWORD:
        token = create_access_token(data={"sub": payload.username})
        return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
    )


@router.post("/api/v1/login", response_model=TokenResponse)
async def login_alias(payload: LoginRequest):
    """Direct JWT authentication flow route."""
    return await login_json(payload)


def get_cached_performance(db: Session) -> dict:
    """Caches rolling performance statistics in-memory with a 10s TTL to prevent heavy DB recalculations."""
    now = time.time()
    if now - _PERF_CACHE["timestamp"] < 10.0 and _PERF_CACHE["data"]:
        return _PERF_CACHE["data"]

    closed_trades = db.query(TradeLogModel).filter(TradeLogModel.status == "CLOSED").all()
    total_trades = len(closed_trades)
    wins = 0
    gross_profit = 0.0
    gross_loss = 0.0
    pnls = []

    for t in closed_trades:
        pnl = t.pnl or 0.0
        pnls.append(pnl)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            gross_loss += abs(pnl)

    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)

    # Sharpe Proxy (Trade-based Information Ratio)
    sharpe_proxy = 0.0
    if total_trades > 0:
        mean_pnl = sum(pnls) / total_trades
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / total_trades
        std_dev = math.sqrt(variance)
        safe_std_dev = std_dev if std_dev > 0 else 1.0
        sharpe_proxy = round(mean_pnl / safe_std_dev, 2)

    data = {
        "total_trades": total_trades,
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2),
        "sharpe_proxy": round(sharpe_proxy, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(gross_profit - gross_loss, 2),
    }
    _PERF_CACHE["timestamp"] = now
    _PERF_CACHE["data"] = data
    return data


@router.get("/api/v1/status")
async def get_status(db: Session = Depends(get_db)):
    """Returns current balance, equity, active drawdown, circuit breaker state, MT5 health, and performance telemetry."""
    acct = bot_engine.mt5_client.account_info() if bot_engine.mt5_client else None
    balance = getattr(acct, "balance", 1000.0) if acct else 1000.0

    perf_stats = get_cached_performance(db)

    # Exclude manual trades (magic = 0) - isolate bot floating PnL and drawdown
    bot_positions = bot_engine.get_bot_positions()
    bot_floating_pnl = sum(getattr(p, "profit", 0.0) for p in bot_positions)
    drawdown = max(0.0, -bot_floating_pnl)
    equity = balance + bot_floating_pnl

    terminal_conn = False
    if bot_engine.mt5_client:
        term = bot_engine.mt5_client.terminal_info()
        terminal_conn = getattr(term, "connected", False) if term else False

    return {
        "status": bot_engine.state,
        "terminal_connected": terminal_conn,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "floating_pnl": round(bot_floating_pnl, 2),
        "starting_daily_balance": round(bot_engine.starting_daily_balance, 2),
        "current_drawdown": round(drawdown, 2),
        "daily_drawdown_limit": DAILY_DRAWDOWN_LIMIT_USD,
        "circuit_breaker_active": bot_engine.state == "CIRCUIT_BREAKER_HALTED",
        "circuit_breaker_until": bot_engine.circuit_breaker_until.isoformat() if bot_engine.circuit_breaker_until else None,
        "allowed_magic_numbers": ALLOWED_MAGIC_NUMBERS,
        "server_time": datetime.now(timezone.utc).isoformat(),
        "compounding_tier": bot_engine.evaluate_compounding_tier(
            balance=balance,
            equity=equity,
            floating_drawdown=drawdown
        ),
        "performance": perf_stats,
    }


@router.get("/api/v1/configs")
async def get_configs(db: Session = Depends(get_db)):
    """Returns all asset configurations."""
    configs = db.query(ConfigModel).all()
    return [c.to_dict() for c in configs]


@router.get("/api/v1/telemetry")
async def get_telemetry(db: Session = Depends(get_db)):
    """
    Principal Consolidated Telemetry Endpoint.
    Delivers complete system telemetry, live signals, open positions, recent trade history,
    and signal evaluation recall audits in a single round-trip (< 25ms).
    """
    t0 = time.time()
    status_data = await get_status(db=db)
    configs = [c.to_dict() for c in db.query(ConfigModel).all()]

    symbols = [c["symbol"] for c in configs] or ["XAUUSD", "USDJPY"]
    signals_data = {}
    for s in symbols:
        sig = tv_analyzer.get_aligned_signal(s)
        is_blk, blk_msg = await news_filter.is_news_blackout(s)
        in_sess, sess_msg = bot_engine.is_within_trading_session(s)
        signals_data[s] = {
            "signal": sig,
            "news_blackout": is_blk,
            "news_message": blk_msg,
            "session_active": in_sess,
            "session_message": sess_msg,
        }

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
            "time": getattr(p, "time", 0),
        })

    recent_trades = [t.to_dict() for t in db.query(TradeLogModel).order_by(TradeLogModel.timestamp.desc()).limit(30).all()]
    recent_events = [e.to_dict() for e in db.query(SystemEventModel).order_by(SystemEventModel.timestamp.desc()).limit(30).all()]
    recent_audits = [a.to_dict() for a in db.query(SignalAuditModel).order_by(SignalAuditModel.timestamp.desc()).limit(50).all()]

    latency_ms = (time.time() - t0) * 1000.0

    return {
        "status": status_data,
        "configs": configs,
        "signals": signals_data,
        "positions": positions,
        "open_positions": positions,
        "trades": recent_trades,
        "recent_trades": recent_trades,
        "events": recent_events,
        "system_events": recent_events,
        "signal_audits": recent_audits,
        "latency_ms": round(latency_ms, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

