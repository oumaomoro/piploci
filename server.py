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
                    }
                }
                await ws_manager.broadcast(payload)
        except Exception as e:
            logger.error(f"Telemetry broadcaster error: {e}")

        await asyncio.sleep(1.5)


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
    log_system_event("FastAPIServer", f"{APP_NAME} server and WebSocket bridge started.")
    yield
    # Shutdown
    telemetry_task.cancel()
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


def verify_token(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


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


@app.get("/api/v1/status")
async def get_status():
    """Returns current balance, equity, active drawdown, circuit breaker state, and MT5 health."""
    acct = bot_engine.mt5_client.account_info() if bot_engine.mt5_client else None
    balance = getattr(acct, "balance", 1000.0) if acct else 1000.0

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
    }


@app.get("/api/v1/configs")
async def get_configs(db: Session = Depends(get_db)):
    """Returns all asset configurations."""
    configs = db.query(ConfigModel).all()
    return [c.to_dict() for c in configs]


@app.post("/api/v1/control/toggle")
async def toggle_asset_scan(payload: AssetToggleRequest, db: Session = Depends(get_db)):
    """Enables or disables automated strategy scanning for a symbol."""
    cfg = db.query(ConfigModel).filter_by(symbol=payload.symbol.upper()).first()
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Symbol {payload.symbol} not found in database.")

    cfg.active = payload.active
    db.commit()

    action_str = "ENABLED" if payload.active else "PAUSED"
    msg = f"Asset scanning {action_str} for {cfg.symbol}"
    log_system_event("FastAPIServer", msg)

    await bot_engine.broadcast_event("CONFIG_UPDATED", {
        "symbol": cfg.symbol,
        "active": cfg.active,
        "message": msg,
    })

    return {"symbol": cfg.symbol, "active": cfg.active, "message": msg}


@app.post("/api/v1/control/emergency-stop")
async def emergency_stop():
    """
    Emergency Kill Switch:
    Immediately closes ALL positions with magic numbers 100201 and 100202,
    and sets system state to HALTED.
    """
    result = await bot_engine.trigger_emergency_stop()
    return result


@app.post("/api/v1/control/resume")
async def resume_trading():
    """Resumes trading if the bot was halted."""
    bot_engine.state = "RUNNING"
    bot_engine.circuit_breaker_until = None
    msg = "Trading resumed by user manual command."
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
async def close_position(payload: PositionCloseRequest):
    """Closes a specific bot position by ticket number while enforcing Magic isolation."""
    success = await bot_engine.close_position_by_ticket(payload.ticket, reason="Manual Close via Dashboard")
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
