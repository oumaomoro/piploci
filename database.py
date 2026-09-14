"""
SQLite Database ORM models and database session management using SQLAlchemy.
Includes auto-seeding for default symbol configurations.
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
    settings,
)

logger = logging.getLogger("Database")

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ConfigModel(Base):
    """Configuration table for asset trading parameters."""
    __tablename__ = "configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, unique=True, index=True, nullable=False)
    active = Column(Boolean, default=True)
    lot_type = Column(String, default="dynamic_atr")
    risk_percent = Column(Float, default=1.0)
    max_spread = Column(Float, default=35.0)
    magic_number = Column(Integer, unique=True, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "active": self.active,
            "lot_type": self.lot_type,
            "risk_percent": self.risk_percent,
            "max_spread": self.max_spread,
            "magic_number": self.magic_number,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class TradeLogModel(Base):
    """Historical and active trade execution record."""
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(Integer, nullable=False)
    symbol = Column(String, nullable=False)
    action = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=True)
    sl = Column(Float, default=0.0)
    tp = Column(Float, default=0.0)
    pnl = Column(Float, default=0.0)
    magic = Column(Integer, nullable=False)
    status = Column(String, default="OPEN")  # OPEN, CLOSED
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(String, nullable=True)

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
    """System-wide audit and telemetry event logger."""
    __tablename__ = "system_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    log_level = Column(String, default="INFO")
    module = Column(String, nullable=False)
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
            ("XAUUSD", MAGIC_XAUUSD, 35.0),
            ("USDJPY", MAGIC_USDJPY, 20.0),
        ]

        for symbol_name, magic, max_spread in default_symbols:
            existing = session.query(ConfigModel).filter_by(symbol=symbol_name).first()
            if not existing:
                cfg_item = ConfigModel(
                    symbol=symbol_name,
                    active=True,
                    lot_type="dynamic_atr",
                    risk_percent=1.0,
                    max_spread=max_spread,
                    magic_number=magic,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(cfg_item)
                seeded = True
                logger.info(f"Auto-seeded default configuration for {symbol_name} (Magic: {magic})")

        if seeded:
            session.commit()
            log_system_event("Database", "Database initialized and seeded with default symbol configurations.")
        else:
            logger.info("Symbol configurations already exist.")


init_db = init_database
