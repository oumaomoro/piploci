"""
System configuration and parameter definitions for Piploci.
Supports both Pydantic BaseSettings and standalone exported constants.
"""

import json
import logging
import os
import urllib.parse
from typing import Dict, Any, List, Tuple, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    from dotenv import load_dotenv
    load_dotenv(override=False)
except ImportError:
    pass

logger = logging.getLogger("Config")


def fetch_cloud_secrets() -> Dict[str, Any]:
    """
    Cloud Secrets Manager integration (e.g. AWS Secrets Manager).
    If AWS_SECRET_NAME is configured in the environment, retrieves
    sensitive MT5 and API credentials from AWS Secrets Manager.
    """
    secret_name = os.getenv("AWS_SECRET_NAME")
    if not secret_name:
        return {}

    region_name = os.getenv("AWS_REGION", "us-east-1")
    try:
        import boto3
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region_name)
        resp = client.get_secret_value(SecretId=secret_name)
        if "SecretString" in resp:
            secrets = json.loads(resp["SecretString"])
            logger.info(f"Loaded credentials securely from AWS Secrets Manager ({secret_name}).")
            return secrets
    except ImportError:
        logger.warning("AWS_SECRET_NAME is configured, but 'boto3' is not installed. Install boto3 to fetch cloud secrets.")
    except Exception as e:
        logger.error(f"Failed to fetch secrets from AWS Secrets Manager: {e}")

    return {}


# Pre-fetch cloud secrets if configured and inject into environment
_cloud_secrets = fetch_cloud_secrets()
for _k, _v in _cloud_secrets.items():
    if _k not in os.environ:
        os.environ[_k] = str(_v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "Piploci"
    SECRET_KEY: str = os.getenv("SECRET_KEY", "trading_bot_super_secret_key_2026_jwt_token_secure")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    # Supabase Infrastructure Configuration
    SUPABASE_PROJECT_ID: str = os.getenv("SUPABASE_PROJECT_ID", "npjsxpsqleckvhlevdyz")
    SUPABASE_DB_HOST: str = os.getenv("SUPABASE_DB_HOST", "db.npjsxpsqleckvhlevdyz.supabase.co")
    SUPABASE_DB_PASSWORD: str = os.getenv("SUPABASE_DB_PASSWORD", "piploci34@!")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://npjsxpsqleckvhlevdyz.supabase.co")
    SUPABASE_PUBLISHABLE_KEY: str = os.getenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_uw9ppL7mH5XalugyWb7ECw_AQglanlT")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv(
        "SUPABASE_SERVICE_ROLE_KEY",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5wanN4cHNxbGVja3ZobGV2ZHl6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4OTM3NzIyOSwiZXhwIjoyMTA0OTUzMjI5fQ.3XDMjL-BgtkScTqa4jej-kSiNATZW4lMNIgYTvSMMFM"
    )

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgresql+psycopg2://postgres:{urllib.parse.quote_plus(os.getenv('SUPABASE_DB_PASSWORD', 'piploci34@!'))}@{os.getenv('SUPABASE_DB_HOST', 'db.npjsxpsqleckvhlevdyz.supabase.co')}:5432/postgres"
    )
    
    # Global Risk Controls
    DAILY_DRAWDOWN_LIMIT_USD: float = 4.50
    CIRCUIT_BREAKER_HALT_HOURS: int = 24
    RISK_PERCENT_PER_TRADE: float = 1.0  # 1% per trade
    
    # News Blackout Window
    NEWS_BLACKOUT_MINUTES: int = 30
    NEWS_BUFFER_BEFORE_MINUTES: int = 30
    NEWS_BUFFER_AFTER_MINUTES: int = 30
    NEWS_REFRESH_INTERVAL_SECONDS: int = 300
    
    # Credentials & Admin
    DEFAULT_ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    DEFAULT_ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "AdminPass@2026")
    
    # MetaTrader 5 Terminal
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "")
    MT5_PATH: str = os.getenv("MT5_PATH", "")
    MT5_RECONNECT_INTERVAL_SECONDS: int = 5
    MT5_HEARTBEAT_INTERVAL_SECONDS: int = 1
    
    # News APIs
    PARSE_API_KEY: str = os.getenv("PARSE_API_KEY", "")
    PARSE_FOREXFACTORY_API_URL: str = os.getenv(
        "PARSE_FOREXFACTORY_API_URL",
        "https://parse.bot/marketplace/51d6a4a2-b821-47d6-a943-47015b35e73f/forexfactory-com-api"
    )
    PARSE_INVESTING_API_URL: str = os.getenv(
        "PARSE_INVESTING_API_URL",
        "https://napi.parse.bot/marketplace/99338e9c-967e-4a52-8f07-7e2cd9844d9b/investing-com-api"
    )

    # Assets Configuration
    XAUUSD_MAGIC: int = 100201
    XAUUSD_ATR_PERIOD: int = 14
    XAUUSD_SL_MULT: float = 1.5
    XAUUSD_TP_MULT: float = 3.5
    XAUUSD_WICK_RATIO: float = 0.55
    XAUUSD_SESSION_START: str = "15:30"
    XAUUSD_SESSION_END: str = "19:30"

    USDJPY_MAGIC: int = 100202
    USDJPY_ATR_PERIOD: int = 14
    USDJPY_SL_MULT: float = 1.2
    USDJPY_TP_MULT: float = 3.0
    USDJPY_WICK_RATIO: float = 0.45
    USDJPY_SESSIONS: List[Tuple[str, str]] = [
        ("03:00", "07:00"),
        ("15:30", "19:30")
    ]

settings = Settings()

# ==============================================================================
# STANDALONE EXPORTS FOR ARCHITECTURE COMPLIANCE
# ==============================================================================
APP_NAME = settings.APP_NAME
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES
DATABASE_URL = settings.DATABASE_URL

# Supabase Infrastructure Exports
SUPABASE_PROJECT_ID = settings.SUPABASE_PROJECT_ID
SUPABASE_DB_HOST = settings.SUPABASE_DB_HOST
SUPABASE_DB_PASSWORD = settings.SUPABASE_DB_PASSWORD
SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY = settings.SUPABASE_PUBLISHABLE_KEY
SUPABASE_SERVICE_ROLE_KEY = settings.SUPABASE_SERVICE_ROLE_KEY

DEFAULT_ADMIN_USER = settings.DEFAULT_ADMIN_USER
DEFAULT_ADMIN_PASSWORD = settings.DEFAULT_ADMIN_PASSWORD

DAILY_DRAWDOWN_LIMIT_USD = settings.DAILY_DRAWDOWN_LIMIT_USD
CIRCUIT_BREAKER_HALT_HOURS = settings.CIRCUIT_BREAKER_HALT_HOURS
RISK_PERCENT_PER_TRADE = settings.RISK_PERCENT_PER_TRADE

MAGIC_XAUUSD = settings.XAUUSD_MAGIC
MAGIC_USDJPY = settings.USDJPY_MAGIC
ALLOWED_MAGIC_NUMBERS = [MAGIC_XAUUSD, MAGIC_USDJPY]

TIMEZONE_EAT = "Africa/Nairobi"

NEWS_BUFFER_BEFORE_MINUTES = settings.NEWS_BUFFER_BEFORE_MINUTES
NEWS_BUFFER_AFTER_MINUTES = settings.NEWS_BUFFER_AFTER_MINUTES
NEWS_SHIELD_CURRENCIES = ["USD", "JPY"]
NEWS_REFRESH_INTERVAL_SECONDS = settings.NEWS_REFRESH_INTERVAL_SECONDS
PARSE_API_KEY = settings.PARSE_API_KEY
PARSE_FOREXFACTORY_API_URL = settings.PARSE_FOREXFACTORY_API_URL
PARSE_INVESTING_API_URL = settings.PARSE_INVESTING_API_URL

MT5_LOGIN = settings.MT5_LOGIN
MT5_PASSWORD = settings.MT5_PASSWORD
MT5_SERVER = settings.MT5_SERVER
MT5_PATH = settings.MT5_PATH
MT5_RECONNECT_INTERVAL_SECONDS = settings.MT5_RECONNECT_INTERVAL_SECONDS
MT5_HEARTBEAT_INTERVAL_SECONDS = settings.MT5_HEARTBEAT_INTERVAL_SECONDS

SESSION_WINDOWS = {
    "XAUUSD": [("15:30", "19:30")],
    "USDJPY": [("03:00", "07:00"), ("15:30", "19:30")]
}

SYMBOL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "XAUUSD": {
        "magic_number": MAGIC_XAUUSD,
        "lot_type": "dynamic_atr",
        "risk_percent": 1.0,
        "max_spread_price": 0.35,       # $0.35 max spread for Gold (35 points)
        "max_spread_points": 35.0,
        "min_reversal_wick_ratio": 0.55,
        "atr_period": 14,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.5,
        "trailing_atr_multiplier": 1.5, # 1.5x ATR Breakeven / Trailing profit trigger
        "tradingview_screener": "forex",
        "tradingview_exchange": "OANDA",
        "tradingview_symbol": "XAUUSD",
    },
    "USDJPY": {
        "magic_number": MAGIC_USDJPY,
        "lot_type": "dynamic_atr",
        "risk_percent": 1.0,
        "max_spread_price": 0.020,      # 2.0 pips max spread for USDJPY
        "max_spread_points": 20.0,
        "min_reversal_wick_ratio": 0.45,
        "atr_period": 14,
        "atr_sl_multiplier": 1.2,
        "atr_tp_multiplier": 3.0,
        "trailing_atr_multiplier": 1.5, # 1.5x ATR Breakeven / Trailing profit trigger
        "tradingview_screener": "forex",
        "tradingview_exchange": "FX_IDC",
        "tradingview_symbol": "USDJPY",
    }
}
