"""
FastAPI Application Factory and Server Lifecycle for Piploci.
Orchestrates REST endpoints, WebSocket feeds, and EOD reporting.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

try:
    from bot.config import APP_NAME
    from bot.database import init_database, SessionLocal, TradeLogModel, log_system_event
    from bot.engine.core import bot_engine
    from bot.notifications.telegram import send_telegram_alert, format_daily_digest
    from bot.api.websocket import ws_manager, telemetry_broadcaster
    from bot.api.routes.status import router as status_router
    from bot.api.routes.control import router as control_router
    from bot.api.routes.data import router as data_router
    from bot.api.routes.config import router as config_router
    from bot.api.routes.auth import router as auth_router
except ImportError:
    from config import APP_NAME
    from database import init_database, SessionLocal, TradeLogModel, log_system_event
    from bot_engine import bot_engine
    from notifier import send_telegram_alert, format_daily_digest
    from bot.api.websocket import ws_manager, telemetry_broadcaster
    from bot.api.routes.status import router as status_router
    from bot.api.routes.control import router as control_router
    from bot.api.routes.data import router as data_router
    from bot.api.routes.config import router as config_router
    from bot.api.routes.auth import router as auth_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("FastAPIServer")


async def send_eod_daily_digest(db_session_factory=None):
    """
    Computes today's closed trade stats and sends institutional EOD Telegram digest.
    """
    import pytz
    eat = pytz.timezone("Africa/Nairobi")
    now_eat = datetime.now(eat)
    today_start = now_eat.replace(hour=0, minute=0, second=0, microsecond=0)

    db = db_session_factory() if db_session_factory else SessionLocal()
    try:
        closed_trades = db.query(TradeLogModel).filter(
            TradeLogModel.status == "CLOSED",
            TradeLogModel.timestamp >= today_start.astimezone(timezone.utc).replace(tzinfo=None)
        ).all()

        total_trades = len(closed_trades)
        wins = sum(1 for t in closed_trades if (t.pnl or 0.0) > 0)
        net_pnl = sum((t.pnl or 0.0) for t in closed_trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        
        max_dd = getattr(bot_engine, "max_drawdown_exposure", 0.0)
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


def create_app() -> FastAPI:
    fastapi_app = FastAPI(
        title=f"{APP_NAME} API",
        version="1.0.0",
        description="Algorithmic Trading & MT5 Monitoring Gateway",
        lifespan=lifespan,
    )

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register modular routers
    fastapi_app.include_router(auth_router)
    fastapi_app.include_router(status_router)
    fastapi_app.include_router(control_router)
    fastapi_app.include_router(data_router)
    fastapi_app.include_router(config_router)

    @fastapi_app.get("/health")
    @fastapi_app.get("/api/v1/health")
    async def health_check():
        """Lightweight server health probe."""
        return {"status": "ok", "service": APP_NAME, "time": datetime.now(timezone.utc).isoformat()}

    # Real-time WebSocket endpoint
    @fastapi_app.websocket("/api/v1/ws/live-feed")
    async def websocket_live_feed(websocket: WebSocket):
        await ws_manager.connect(websocket)
        try:
            await websocket.send_text(json.dumps({
                "type": "INITIAL_HANDSHAKE",
                "message": f"Connected to {APP_NAME} Live Stream",
                "server_time": datetime.now(timezone.utc).isoformat(),
            }))

            while True:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as e:
            logger.error(f"WebSocket client error: {e}")
            ws_manager.disconnect(websocket)

    return fastapi_app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("bot.api.app:app", host="0.0.0.0", port=8000, reload=True)
