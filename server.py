"""
FastAPI Server and WebSocket Bridge.
Provides RESTful APIs for authentication, control toggles, emergency kill switch,
telemetry, and real-time WebSocket feeds for the Streamlit monitoring dashboard.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Dict, List, Any, Optional

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import (
    APP_NAME,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DEFAULT_ADMIN_USER,
    DEFAULT_ADMIN_PASSWORD,
    DAILY_DRAWDOWN_LIMIT_USD,
    MAGIC_XAUUSD,
    MAGIC_USDJPY,
    ALLOWED_MAGIC_NUMBERS,
)
from database import (
    init_database,
    get_db,
    ConfigModel,
    TradeLogModel,
    SystemEventModel,
    SignalAuditModel,
    log_system_event,
)
from bot_engine import bot_engine
from news_filter import news_filter
from tradingview_ta_module import tv_analyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FastAPIServer")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ==============================================================================
# PYDANTIC SCHEMAS
# ==============================================================================
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    username: str
    password: str


class AssetToggleRequest(BaseModel):
    symbol: str
    active: bool


class PositionCloseRequest(BaseModel):
    ticket: int


class ConfigUpdateRequest(BaseModel):
    symbol: str
    active: Optional[bool] = None
    risk_percent: Optional[float] = None
    max_spread: Optional[float] = None
    session_window: Optional[str] = None
    scaling_tier_active: Optional[bool] = None
    tier1_threshold: Optional[float] = None
    tier2_threshold: Optional[float] = None


# ==============================================================================
# WEBSOCKET CONNECTION MANAGER
# ==============================================================================
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


# Register engine events to broadcast to WebSockets
def on_engine_event(event: Dict[str, Any]):
    asyncio.create_task(ws_manager.broadcast(event))


bot_engine.register_broadcast_callback(on_engine_event)


# ==============================================================================
# BACKGROUND TELEMETRY BROADCASTER
# ==============================================================================
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


async def send_eod_daily_digest(db_session_factory=None):
    """
    Computes today's closed trade stats and sends institutional EOD Telegram digest.
    """
    from database import SessionLocal
    import pytz
    from notifier import send_telegram_alert, format_daily_digest

    eat = pytz.timezone("Africa/Nairobi")
    now_eat = datetime.now(eat)
    today_start = now_eat.replace(hour=0, minute=0, second=0, microsecond=0)

    db = db_session_factory() if db_session_factory else SessionLocal()
    try:
        # Filter closed trades from today (or fallback to all closed if none today)
        closed_trades = db.query(TradeLogModel).filter(
            TradeLogModel.status == "CLOSED",
            TradeLogModel.timestamp >= today_start.astimezone(timezone.utc).replace(tzinfo=None)
        ).all()

        total_trades = len(closed_trades)
        wins = sum(1 for t in closed_trades if (t.pnl or 0.0) > 0)
        net_pnl = sum((t.pnl or 0.0) for t in closed_trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        
        # Max drawdown exposure reached
        max_dd = getattr(bot_engine, "max_drawdown_exposure", 0.0)
        
        # Slippage average
        slippages = [getattr(t, "slippage", 0.0) for t in closed_trades if getattr(t, "slippage", 0.0) != 0.0]
        avg_slippage = (sum(slippages) / len(slippages)) if slippages else 0.0

        digest_text = format_daily_digest(
            total_trades=total_trades,
            net_realized_pnl=net_pnl,
            win_rate=win_rate,
            max_drawdown_exposure=max_dd,
            avg_slippage_pts=avg_slippage,
            date_str=now_eat.strftime("%Y-%m-%d")
        )
        await send_telegram_alert(digest_text)
        return {
            "total_trades": total_trades,
            "net_pnl": net_pnl,
            "win_rate": win_rate,
            "digest_text": digest_text
        }
    finally:
        db.close()


async def eod_digest_scheduler():
    """
    Background worker that triggers send_eod_daily_digest daily at 23:59 EAT.
    """
    import pytz
    eat = pytz.timezone("Africa/Nairobi")
    last_dispatched_date = None

    while True:
        try:
            now_eat = datetime.now(eat)
            if now_eat.hour == 23 and now_eat.minute >= 59 and last_dispatched_date != now_eat.date():
                logger.info("Executing scheduled EOD Daily Telegram Digest...")
                await send_eod_daily_digest()
                last_dispatched_date = now_eat.date()
        except Exception as e:
            logger.error(f"EOD digest scheduler error: {e}")
        await asyncio.sleep(45)


# ==============================================================================
# FASTAPI LIFECYCLE
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Initializing {APP_NAME}...")
    init_database()
    await bot_engine.start()
    telemetry_task = asyncio.create_task(telemetry_broadcaster())
    eod_task = asyncio.create_task(eod_digest_scheduler())
    log_system_event("FastAPIServer", f"{APP_NAME} server, WebSocket bridge, and EOD scheduler started.")
    yield
    # Shutdown
    telemetry_task.cancel()
    eod_task.cancel()
    await bot_engine.stop()
    logger.info("FastAPI server shut down successfully.")


app = FastAPI(
    title=f"{APP_NAME} API",
    version="1.0.0",
    description="Algorithmic Trading & MT5 Monitoring Gateway",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# AUTHENTICATION HELPERS
# ==============================================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    """FastAPI authentication dependency validating Bearer JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


verify_token = get_current_user


# ==============================================================================
# API ENDPOINTS
# ==============================================================================
@app.post("/api/v1/auth/login", response_model=TokenResponse)
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


@app.post("/api/v1/auth/login-json", response_model=TokenResponse)
async def login_json(payload: LoginRequest):
    """JSON login for mobile and REST clients."""
    if payload.username == DEFAULT_ADMIN_USER and payload.password == DEFAULT_ADMIN_PASSWORD:
        token = create_access_token(data={"sub": payload.username})
        return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
    )


@app.post("/api/v1/login", response_model=TokenResponse)
async def login_alias(payload: LoginRequest):
    """Direct JWT authentication flow route."""
    return await login_json(payload)


_SERVER_PERF_CACHE = {"timestamp": 0.0, "data": {}}


def get_cached_performance(db: Session) -> dict:
    """Caches rolling performance statistics in-memory with a 10s TTL to prevent heavy DB recalculations."""
    import time
    now = time.time()
    if now - _SERVER_PERF_CACHE["timestamp"] < 10.0 and _SERVER_PERF_CACHE["data"]:
        return _SERVER_PERF_CACHE["data"]

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
    _SERVER_PERF_CACHE["timestamp"] = now
    _SERVER_PERF_CACHE["data"] = data
    return data


@app.get("/api/v1/status")
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


@app.get("/api/v1/configs")
async def get_configs(db: Session = Depends(get_db)):
    """Returns all asset configurations."""
    configs = db.query(ConfigModel).all()
    return [c.to_dict() for c in configs]


@app.get("/api/v1/telemetry")
async def get_telemetry(db: Session = Depends(get_db)):
    """
    Consolidated high-speed telemetry endpoint providing complete state synchronization in a single round-trip.
    """
    import time
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



@app.post("/api/v1/control/toggle")
async def toggle_asset_scan(
    payload: AssetToggleRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Enables or disables automated strategy scanning for a symbol."""
    cfg = db.query(ConfigModel).filter_by(symbol=payload.symbol.upper()).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Symbol {payload.symbol} not found in database.")

    cfg.active = payload.active
    db.commit()

    action_str = "ENABLED" if payload.active else "PAUSED"
    msg = f"Asset scanning {action_str} for {cfg.symbol} by {current_user}"
    log_system_event("FastAPIServer", msg)

    await bot_engine.broadcast_event("CONFIG_UPDATED", {
        "symbol": cfg.symbol,
        "active": cfg.active,
        "message": msg,
    })

    return {"symbol": cfg.symbol, "active": cfg.active, "message": msg}


@app.post("/api/v1/configs/update")
async def update_symbol_config(
    payload: ConfigUpdateRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    """Updates risk parameters for a symbol config (risk_percent, max_spread, session_window, active)."""
    cfg = db.query(ConfigModel).filter_by(symbol=payload.symbol.upper()).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Symbol {payload.symbol} not found in database.")

    changes = []
    if payload.active is not None:
        cfg.active = payload.active
        changes.append(f"active={payload.active}")
    if payload.risk_percent is not None:
        if not (0.1 <= payload.risk_percent <= 5.0):
            raise HTTPException(status_code=422, detail="risk_percent must be between 0.1 and 5.0")
        cfg.risk_percent = payload.risk_percent
        changes.append(f"risk_percent={payload.risk_percent}")
    if payload.max_spread is not None:
        if payload.max_spread <= 0:
            raise HTTPException(status_code=422, detail="max_spread must be positive")
        cfg.max_spread = payload.max_spread
        changes.append(f"max_spread={payload.max_spread}")
    if payload.session_window is not None:
        cfg.session_window = payload.session_window.strip()
        changes.append(f"session_window='{payload.session_window.strip()}'")
    if payload.scaling_tier_active is not None:
        cfg.scaling_tier_active = payload.scaling_tier_active
        changes.append(f"scaling_tier_active={payload.scaling_tier_active}")
    if payload.tier1_threshold is not None:
        if payload.tier1_threshold <= 0:
            raise HTTPException(status_code=422, detail="tier1_threshold must be positive")
        cfg.tier1_threshold = payload.tier1_threshold
        changes.append(f"tier1_threshold={payload.tier1_threshold}")
    if payload.tier2_threshold is not None:
        current_t1 = payload.tier1_threshold if payload.tier1_threshold is not None else (cfg.tier1_threshold or 15.0)
        if payload.tier2_threshold <= current_t1:
            raise HTTPException(status_code=422, detail="tier2_threshold must be greater than tier1_threshold")
        cfg.tier2_threshold = payload.tier2_threshold
        changes.append(f"tier2_threshold={payload.tier2_threshold}")

    if not changes:
        return {"symbol": cfg.symbol, "message": "No changes submitted.", "updated": []}

    db.commit()
    msg = f"Config updated for {cfg.symbol} by {current_user}: {', '.join(changes)}"
    log_system_event("FastAPIServer", msg)
    await bot_engine.broadcast_event("CONFIG_UPDATED", {"symbol": cfg.symbol, "changes": changes, "message": msg})
    return {"symbol": cfg.symbol, "message": msg, "updated": changes}


@app.post("/api/v1/control/emergency-stop")
async def emergency_stop(current_user: str = Depends(get_current_user)):
    """
    Emergency Kill Switch:
    Immediately closes ALL positions with magic numbers 100201 and 100202,
    and sets system state to HALTED.
    """
    logger.warning(f"Emergency stop invoked by user: {current_user}")
    result = await bot_engine.trigger_emergency_stop()
    return result


@app.post("/api/v1/control/resume")
async def resume_trading(current_user: str = Depends(get_current_user)):
    """Resumes trading if the bot was halted."""
    bot_engine.state = "RUNNING"
    bot_engine.circuit_breaker_until = None
    msg = f"Trading resumed by user: {current_user}"
    log_system_event("FastAPIServer", msg)
    await bot_engine.broadcast_event("SYSTEM_RESUMED", {"message": msg})
    return {"status": "RUNNING", "message": msg}


@app.get("/api/v1/positions")
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


@app.post("/api/v1/control/close-position")
async def close_position(
    payload: PositionCloseRequest,
    current_user: str = Depends(get_current_user),
):
    """Closes a specific bot position by ticket number while enforcing Magic isolation."""
    success = await bot_engine.close_position_by_ticket(payload.ticket, reason=f"Manual Close via Dashboard by {current_user}")
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Could not close position #{payload.ticket}. Verify it exists and belongs to bot magic numbers."
        )
    return {"ticket": payload.ticket, "status": "CLOSED"}


@app.get("/api/v1/trades")
async def get_trade_history(limit: int = 50, db: Session = Depends(get_db)):
    """Returns past trade logs."""
    logs = db.query(TradeLogModel).order_by(TradeLogModel.timestamp.desc()).limit(limit).all()
    return [l.to_dict() for l in logs]


@app.get("/api/v1/events")
async def get_system_events(limit: int = 50, db: Session = Depends(get_db)):
    """Returns recent system logs and telemetry events."""
    events = db.query(SystemEventModel).order_by(SystemEventModel.timestamp.desc()).limit(limit).all()
    return [e.to_dict() for e in events]


@app.get("/api/v1/signals")
async def get_market_signals():
    """Returns TradingView consensus and News blackout status for all symbols."""
    res = {}
    for s in ["XAUUSD", "USDJPY"]:
        sig = tv_analyzer.get_aligned_signal(s)
        is_blk, blk_msg = await news_filter.is_news_blackout(s)
        in_sess, sess_msg = bot_engine.is_within_trading_session(s)
        res[s] = {
            "signal": sig,
            "news_blackout": is_blk,
            "news_message": blk_msg,
            "session_active": in_sess,
            "session_message": sess_msg,
        }
    return res


# ==============================================================================
# WEBSOCKET STREAM
# ==============================================================================
@app.websocket("/api/v1/ws/live-feed")
async def websocket_live_feed(websocket: WebSocket):
    """Real-time WebSocket endpoint streaming ticks, trade logs, and risk alerts."""
    await ws_manager.connect(websocket)
    try:
        # Initial greeting and state snapshot
        await websocket.send_text(json.dumps({
            "type": "INITIAL_HANDSHAKE",
            "message": f"Connected to {APP_NAME} Live Stream",
            "server_time": datetime.now(timezone.utc).isoformat(),
        }))

        while True:
            # Keep-alive receive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket client error: {e}")
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
