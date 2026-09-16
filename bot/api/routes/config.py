"""
Configuration modification routes (risk parameters, thresholds, and sessions).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

try:
    from bot.database import get_db, ConfigModel, log_system_event
    from bot.engine.core import bot_engine
    from bot.api.schemas import ConfigUpdateRequest
    from bot.api.auth import get_current_user
except ImportError:
    from database import get_db, ConfigModel, log_system_event
    from bot_engine import bot_engine
    from bot.api.schemas import ConfigUpdateRequest
    from bot.api.auth import get_current_user

logger = logging.getLogger("ConfigRouter")
router = APIRouter(prefix="/api/v1/configs", tags=["Config"])


@router.post("/update")
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
