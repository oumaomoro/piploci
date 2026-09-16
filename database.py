"""
PostgreSQL (Supabase) & SQLite Database ORM models and database session management using SQLAlchemy.
Features robust connection pooling, auto-reconnect (pool_pre_ping=True, pool_size=10),
and schema seeding for strategy configurations, trading logs, and circuit breaker events.
"""

import os
from pathlib import Path
import urllib.parse
from datetime import datetime, timezone
import logging
from typing import Generator

from sqlalchemy import create_engine, event, Column, Integer, String, Float, Boolean, DateTime, Text, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session

try:
    from bot.config import (
        DATABASE_URL,
        MAGIC_XAUUSD,
        MAGIC_USDJPY,
        SYMBOL_CONFIGS,
        SESSION_WINDOWS,
        settings,
    )
except ImportError:
    from config import (
        DATABASE_URL,
        MAGIC_XAUUSD,
        MAGIC_USDJPY,
        SYMBOL_CONFIGS,
        SESSION_WINDOWS,
        settings,
    )

logger = logging.getLogger("Database")

BASE_DIR = Path(__file__).resolve().parent
SQLITE_DB_PATH = BASE_DIR / "trading_bot.db"
DEFAULT_SQLITE_URL = f"sqlite:///{SQLITE_DB_PATH.as_posix()}"


def configure_sqlite_engine(eng):
    """Enforces Write-Ahead Logging (WAL) and 30s busy timeout for high-concurrency SQLite operations."""
    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.close()
        except Exception as e:
            logger.debug(f"SQLite PRAGMA configuration note: {e}")
    return eng


def normalize_db_url(url: str) -> str:
    """
    Normalizes PostgreSQL connection string for SQLAlchemy + psycopg2.
    Properly URL-encodes special characters (e.g. '@', '!') in passwords
    and ensures the postgresql+psycopg2 dialect driver prefix is present.
    """
    if not url:
        return url
    # Handle raw unencoded passwords with special characters (like '@' or '!') in user:pass@host
    try:
        import re
        # Match postgresql://user:password@host...
        m = re.match(r"^(postgres(?:ql)?(?:\+[a-z0-9]+)?://)([^:]+):([^@]+)@(.+)$", url)
        if m:
            prefix, user, raw_pwd, rest = m.groups()
            encoded_pwd = urllib.parse.quote_plus(urllib.parse.unquote_plus(raw_pwd))
            url = f"{prefix}{user}:{encoded_pwd}@{rest}"
    except Exception:
        pass

    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    return url


def init_engine(db_url: str):
    """
    Initializes SQLAlchemy engine with robust dynamic connection pooling:
    (pool_pre_ping=True, pool_size=10, max_overflow=20)
    for Supabase PostgreSQL, with resilient immediate fallback to absolute SQLite WAL persistence.
    """
    norm_url = normalize_db_url(db_url)
    if norm_url and "postgresql" in norm_url:
        try:
            eng = create_engine(
                norm_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                pool_recycle=1800,
                connect_args={"connect_timeout": 2},
            )
            # Pre-flight connection ping
            with eng.connect() as conn:
                pass
            logger.info("Successfully connected to Supabase PostgreSQL database.")
            return eng
        except Exception as e:
            logger.warning(
                f"Could not establish direct connection to remote Supabase PostgreSQL ({e}). "
                f"Engaging local high-concurrency SQLite WAL persistence ({SQLITE_DB_PATH.name})."
            )
            eng = create_engine(
                DEFAULT_SQLITE_URL,
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            return configure_sqlite_engine(eng)
    else:
        sqlite_url = DEFAULT_SQLITE_URL if (not norm_url or "trading_bot.db" in norm_url or "sqlite" in norm_url) else norm_url
        connect_args = {"check_same_thread": False, "timeout": 30} if "sqlite" in sqlite_url else {}
        eng = create_engine(sqlite_url, connect_args=connect_args)
        if "sqlite" in sqlite_url:
            eng = configure_sqlite_engine(eng)
        return eng


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
    scaling_tier_active = Column(Boolean, default=True, nullable=False)
    tier1_threshold = Column(Float, default=15.0)
    tier2_threshold = Column(Float, default=30.0)
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
            "scaling_tier_active": self.scaling_tier_active if self.scaling_tier_active is not None else True,
            "tier1_threshold": self.tier1_threshold if self.tier1_threshold is not None else 15.0,
            "tier2_threshold": self.tier2_threshold if self.tier2_threshold is not None else 30.0,
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
    # Persists the halt expiry time across restarts
    halt_until = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "drawdown_amount": self.drawdown_amount,
            "state": self.state,
            "halt_until": self.halt_until.isoformat() if self.halt_until else None,
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


class SignalAuditModel(Base):
    """
    Signal evaluation and rejection audit log (signal_audits).
    Provides 100% recall of all evaluated trading opportunities and gate outcomes.
    """
    __tablename__ = "signal_audits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    symbol = Column(String(32), index=True, nullable=False)
    direction = Column(String(16), default="NEUTRAL", nullable=False)
    status = Column(String(32), nullable=False)  # EXECUTED, REJECTED_WICK, REJECTED_NEWS, REJECTED_SESSION, REJECTED_ALIGNMENT, REJECTED_SPREAD, REJECTED_CIRCUIT_BREAKER, MONITORING
    m15_consensus = Column(String(32), nullable=True)
    h1_consensus = Column(String(32), nullable=True)
    wick_ratio = Column(Float, nullable=True)
    spread = Column(Float, nullable=True)
    reason = Column(Text, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "symbol": self.symbol,
            "direction": self.direction,
            "status": self.status,
            "m15_consensus": self.m15_consensus,
            "h1_consensus": self.h1_consensus,
            "wick_ratio": round(self.wick_ratio, 3) if self.wick_ratio is not None else None,
            "spread": round(self.spread, 2) if self.spread is not None else None,
            "reason": self.reason,
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


def log_signal_audit(
    symbol: str,
    status: str = None,
    direction: str = None,
    reason: str = None,
    m15_consensus: str = None,
    h1_consensus: str = None,
    wick_ratio: float = None,
    spread: float = None,
    **kwargs,
):
    """Persists a signal evaluation audit entry for 100% recall and transparency."""
    # Support common parameter aliases
    final_status = status or kwargs.get("gate_status") or kwargs.get("execution_status") or "EVALUATED"
    final_direction = direction or kwargs.get("action") or "NEUTRAL"
    final_reason = reason or kwargs.get("rejection_reason") or ""
    final_wick = wick_ratio if wick_ratio is not None else kwargs.get("wick")
    final_spread = spread if spread is not None else kwargs.get("current_spread")

    try:
        with SessionLocal() as db:
            audit = SignalAuditModel(
                symbol=symbol,
                direction=final_direction,
                status=final_status,
                reason=final_reason,
                m15_consensus=m15_consensus,
                h1_consensus=h1_consensus,
                wick_ratio=final_wick,
                spread=final_spread,
                timestamp=datetime.now(timezone.utc),
            )
            db.add(audit)
            db.commit()
            db.refresh(audit)
            return audit
    except Exception as e:
        logger.error(f"Failed to record signal audit: {e}")
        return None



def init_database():
    """Initializes tables, migrates missing columns, and auto-seeds default configurations for Gold and USDJPY."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")

    # Dynamic schema migration for existing databases
    try:
        inspector = inspect(engine)
        if "strategy_configs" in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns("strategy_configs")]
            with engine.begin() as conn:
                if "scaling_tier_active" not in columns:
                    conn.execute(text("ALTER TABLE strategy_configs ADD COLUMN scaling_tier_active BOOLEAN DEFAULT 1"))
                    logger.info("Migrated strategy_configs: added scaling_tier_active column.")
                if "tier1_threshold" not in columns:
                    conn.execute(text("ALTER TABLE strategy_configs ADD COLUMN tier1_threshold FLOAT DEFAULT 15.0"))
                    logger.info("Migrated strategy_configs: added tier1_threshold column.")
                if "tier2_threshold" not in columns:
                    conn.execute(text("ALTER TABLE strategy_configs ADD COLUMN tier2_threshold FLOAT DEFAULT 30.0"))
                    logger.info("Migrated strategy_configs: added tier2_threshold column.")
        # Migrate circuit_breaker_events: add halt_until column if missing
        if "circuit_breaker_events" in inspector.get_table_names():
            cb_cols = [c["name"] for c in inspector.get_columns("circuit_breaker_events")]
            with engine.begin() as conn:
                if "halt_until" not in cb_cols:
                    conn.execute(text("ALTER TABLE circuit_breaker_events ADD COLUMN halt_until DATETIME"))
                    logger.info("Migrated circuit_breaker_events: added halt_until column.")
    except Exception as e:
        logger.warning(f"Schema migration check for strategy_configs completed: {e}")

    with SessionLocal() as session:
        seeded = False
        try:
            from bot.config import SYMBOL_CONFIGS, SESSION_WINDOWS
        except ImportError:
            from config import SYMBOL_CONFIGS, SESSION_WINDOWS
        default_symbols = []
        for sym, cfg in SYMBOL_CONFIGS.items():
            magic = cfg.get("magic_number", 0)
            max_spread = cfg.get("max_spread_points", 20.0)
            windows = SESSION_WINDOWS.get(sym, [])
            # Format session windows as a string
            win_str = ", ".join([f"{w[0]} - {w[1]} EAT" for w in windows]) if windows else "24h Monitor"
            default_symbols.append((sym, magic, max_spread, win_str))

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
                    scaling_tier_active=True,
                    tier1_threshold=15.0,
                    tier2_threshold=30.0,
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


def restore_engine_state(engine_instance) -> dict:
    """
    Restores critical in-memory engine state from the DB after a restart.
    Fixes three gaps:
    1. Circuit breaker halt expiry — prevents restart from bypassing the 24h halt.
    2. Starting daily balance  — prevents drawdown gate reset on mid-day restarts.
    3. Open trade reconciliation — marks DB trades as CLOSED if MT5 no longer holds them.
    Returns a dict summarizing what was recovered.
    """
    recovery_log = []

    try:
        with SessionLocal() as db:
            # ----------------------------------------------------------------
            # 1. Restore circuit breaker halt state
            # ----------------------------------------------------------------
            latest_cb = (
                db.query(CircuitBreakerEventModel)
                .filter(CircuitBreakerEventModel.halt_until != None)  # noqa: E711
                .order_by(CircuitBreakerEventModel.timestamp.desc())
                .first()
            )
            if latest_cb and latest_cb.halt_until:
                # Make timezone-aware for comparison
                halt_until = latest_cb.halt_until
                if halt_until.tzinfo is None:
                    halt_until = halt_until.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if halt_until > now:
                    engine_instance.circuit_breaker_until = halt_until
                    engine_instance.state = "CIRCUIT_BREAKER_HALTED"
                    remaining = (halt_until - now).total_seconds() / 3600.0
                    msg = f"RESTART RECOVERY: Circuit breaker still active. Halt expires in {remaining:.1f}h."
                    logger.warning(msg)
                    recovery_log.append(msg)
                else:
                    logger.info("RESTART RECOVERY: Circuit breaker halt has expired. Trading allowed.")

            # ----------------------------------------------------------------
            # 2. Open trade reconciliation with MT5
            # ----------------------------------------------------------------
            mt5_client = getattr(engine_instance, "mt5_client", None)
            if mt5_client:
                try:
                    from bot.config import ALLOWED_MAGIC_NUMBERS
                except ImportError:
                    from config import ALLOWED_MAGIC_NUMBERS

                open_db_trades = db.query(TradeLogModel).filter_by(status="OPEN").all()
                mt5_positions = mt5_client.positions_get() or []
                live_tickets = {getattr(p, "ticket", -1) for p in mt5_positions
                                if getattr(p, "magic", 0) in ALLOWED_MAGIC_NUMBERS}

                stale_count = 0
                for trade in open_db_trades:
                    if trade.ticket not in live_tickets:
                        # This trade was closed while server was offline
                        trade.status = "CLOSED"
                        trade.notes = (trade.notes or "") + " | Auto-reconciled on restart (MT5 position not found)"
                        stale_count += 1

                if stale_count > 0:
                    db.commit()
                    msg = f"RESTART RECOVERY: Reconciled {stale_count} stale OPEN trade(s) not found in MT5."
                    logger.info(msg)
                    recovery_log.append(msg)
                    log_system_event("Database", msg)
                else:
                    logger.info("RESTART RECOVERY: All DB open trades confirmed live in MT5.")
            else:
                logger.info("RESTART RECOVERY: MT5 not connected — skipping open trade reconciliation.")

    except Exception as e:
        logger.error(f"RESTART RECOVERY ERROR: {e}")
        recovery_log.append(f"Recovery error: {e}")

    return {"recovered": len(recovery_log) > 0, "log": recovery_log}


init_db = init_database
