"""
PostgreSQL (Supabase) & SQLite Database ORM models and database session management using SQLAlchemy.
Features robust connection pooling, auto-reconnect (pool_pre_ping=True, pool_size=10),
and schema seeding for strategy configurations, trading logs, and circuit breaker events.
"""

from datetime import datetime, timezone
import logging
from typing import Generator

from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from config import (
    DATABASE_URL,
    MAGIC_XAUUSD,
    MAGIC_USDJPY,
    SYMBOL_CONFIGS,
    SESSION_WINDOWS,
    settings,
)

logger = logging.getLogger("Database")


def init_engine(db_url: str):
    """
    Initializes SQLAlchemy engine with robust connection pooling (pool_pre_ping=True, pool_size=10)
    for Supabase PostgreSQL, with resilient fallback to SQLite if remote network is unreachable.
    """
    if "postgresql" in db_url:
        try:
            eng = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=5,
                pool_recycle=1800,
                connect_args={"connect_timeout": 5},
            )
            # Pre-flight ping
            with eng.connect() as conn:
                pass
            logger.info("Successfully connected to Supabase PostgreSQL database.")
            return eng
        except Exception as e:
            logger.warning(
                f"Could not establish direct connection to remote Supabase PostgreSQL ({e}). "
                f"Engaging local SQLite persistence engine."
            )
            fallback_url = "sqlite:///./trading_bot.db"
            return create_engine(fallback_url, connect_args={"check_same_thread": False})
    else:
        connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
        return create_engine(db_url, connect_args=connect_args)


engine = init_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class StrategyConfigModel(Base):
    """Configuration table for asset trading parameters (strategy_configs)."""
    __tablename__ = "strategy_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), unique=True, index=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    session_window = Column(String(128), default="", nullable=False)
    magic = Column(Integer, unique=True, nullable=False)
    max_spread = Column(Float, default=35.0)
    lot_type = Column(String(32), default="dynamic_atr")
    risk_percent = Column(Float, default=1.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    @property
    def magic_number(self) -> int:
        return self.magic

    @magic_number.setter
    def magic_number(self, value: int):
        self.magic = value

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "active": self.active,
            "session_window": self.session_window,
            "magic": self.magic,
            "magic_number": self.magic,
            "max_spread": self.max_spread,
            "lot_type": self.lot_type,
            "risk_percent": self.risk_percent,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# Alias ConfigModel to StrategyConfigModel for backward compatibility
ConfigModel = StrategyConfigModel


class TradingLogModel(Base):
    """Trading event and risk rejection logger (trading_logs)."""
    __tablename__ = "trading_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    level = Column(String(16), default="INFO", nullable=False)
    message = Column(Text, nullable=False)
    symbol = Column(String(32), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "level": self.level,
            "message": self.message,
            "symbol": self.symbol,
        }


class CircuitBreakerEventModel(Base):
    """Circuit breaker triggers and halt state records (circuit_breaker_events)."""
    __tablename__ = "circuit_breaker_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    drawdown_amount = Column(Float, nullable=False)
    state = Column(String(32), default="CIRCUIT_BREAKER_HALTED", nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "drawdown_amount": self.drawdown_amount,
            "state": self.state,
        }


class TradeLogModel(Base):
    """Historical and active trade execution record (trade_logs)."""
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(Integer, nullable=False)
    symbol = Column(String(32), nullable=False)
    action = Column(String(16), nullable=False)
    volume = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=True)
    sl = Column(Float, default=0.0)
    tp = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    magic = Column(Integer, nullable=False)
    status = Column(String(16), default="OPEN")
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(String(255), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "ticket": self.ticket,
            "symbol": self.symbol,
            "action": self.action,
            "volume": self.volume,
            "open_price": self.open_price,
            "close_price": self.close_price,
            "sl": self.sl,
            "tp": self.tp,
            "pnl": self.pnl,
            "magic": self.magic,
            "status": self.status,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "notes": self.notes,
        }


class SystemEventModel(Base):
    """System-wide audit and telemetry event logger (system_events)."""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    log_level = Column(String(16), default="INFO")
    module = Column(String(64), nullable=False)
    message = Column(Text, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "log_level": self.log_level,
            "module": self.module,
            "message": self.message,
        }


def get_db() -> Generator[Session, None, None]:
    """Dependency helper providing transactional database session scope."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def log_trading_log(symbol: str, message: str, level: str = "INFO"):
    """Persists a trading log entry (e.g. spread guard warnings)."""
    try:
        with SessionLocal() as db:
            log_item = TradingLogModel(
                symbol=symbol,
                message=message,
                level=level,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(log_item)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to record trading log: {e}")


def log_circuit_breaker_event(drawdown_amount: float, state: str = "CIRCUIT_BREAKER_HALTED"):
    """Persists a circuit breaker event entry."""
    try:
        with SessionLocal() as db:
            event = CircuitBreakerEventModel(
                drawdown_amount=drawdown_amount,
                state=state,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(event)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to record circuit breaker event: {e}")


def log_system_event(module: str, message: str, level: str = "INFO"):
    """Persists a system event log into the database."""
    try:
        with SessionLocal() as db:
            event = SystemEventModel(
                module=module,
                message=message,
                log_level=level,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(event)
            db.commit()
    except Exception as e:
        logger.error(f"Failed to record system event: {e}")


def init_database():
    """Initializes tables and auto-seeds default configurations for Gold and USDJPY."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")

    with SessionLocal() as session:
        seeded = False
        default_symbols = [
            ("XAUUSD", MAGIC_XAUUSD, 35.0, "15:30 - 19:30 EAT"),
            ("USDJPY", MAGIC_USDJPY, 20.0, "03:00 - 07:00, 15:30 - 19:30 EAT"),
        ]

        for symbol_name, magic, max_spread, session_win in default_symbols:
            existing = session.query(StrategyConfigModel).filter_by(symbol=symbol_name).first()
            if not existing:
                cfg_item = StrategyConfigModel(
                    symbol=symbol_name,
                    active=True,
                    session_window=session_win,
                    magic=magic,
                    lot_type="dynamic_atr",
                    risk_percent=1.0,
                    max_spread=max_spread,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(cfg_item)
                seeded = True
                logger.info(f"Auto-seeded default configuration for {symbol_name} (Magic: {magic})")

        if seeded:
            session.commit()
            log_system_event("Database", "Database initialized and seeded with default strategy configurations.")
            log_trading_log("SYSTEM", "Database schema initialized and auto-seeded.", level="INFO")
        else:
            logger.info("Strategy configurations already exist.")


init_db = init_database
