"""
Authentication and JWT token endpoints for the REST API.
"""

from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

try:
    from bot.config import (
        DEFAULT_ADMIN_USER,
        DEFAULT_ADMIN_PASSWORD,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        SECRET_KEY,
        ALGORITHM,
    )
except ImportError:
    from config import (
        DEFAULT_ADMIN_USER,
        DEFAULT_ADMIN_PASSWORD,
        ACCESS_TOKEN_EXPIRE_MINUTES,
        SECRET_KEY,
        ALGORITHM,
    )

from datetime import datetime, timezone
from jose import jwt

router = APIRouter(tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    username: str
    password: str


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


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
