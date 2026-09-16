"""
Trading and risk control action routes (Kill switch, resume, toggle, position close).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from bot.database import get_db, ConfigModel, log_system_event
    from bot.engine.core import bot_engine
    from bot.api.schemas import AssetToggleRequest, PositionCloseRequest
    from bot.api.auth import get_current_user
except ImportError:
    from database import get_db, ConfigModel, log_system_event
    from bot_engine import bot_engine
    from bot.api.schemas import AssetToggleRequest, PositionCloseRequest
    from bot.api.auth import get_current_user

logger = logging.getLogger("ControlRouter")
router = APIRouter(prefix="/api/v1/control", tags=["Control"])


@router.post("/toggle")
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


@router.post("/emergency-stop")
async def emergency_stop(current_user: str = Depends(get_current_user)):
    """
    Emergency Kill Switch:
    Immediately closes ALL positions with magic numbers 100201 and 100202,
    and sets system state to HALTED.
    """
    logger.warning(f"Emergency stop invoked by user: {current_user}")
    result = await bot_engine.trigger_emergency_stop()
    return result


@router.post("/resume")
async def resume_trading(current_user: str = Depends(get_current_user)):
    """Resumes trading if the bot was halted."""
    bot_engine.state = "RUNNING"
    bot_engine.circuit_breaker_until = None
    msg = f"Trading resumed by user: {current_user}"
    log_system_event("FastAPIServer", msg)
    await bot_engine.broadcast_event("SYSTEM_RESUMED", {"message": msg})
    return {"status": "RUNNING", "message": msg}


@router.post("/close-position")
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
