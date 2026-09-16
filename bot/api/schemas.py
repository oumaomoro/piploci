"""
Pydantic schemas for FastAPI request and response payloads.
"""

from typing import Optional
from pydantic import BaseModel


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
