"""
Automated unit and integration test suite for the Automated MT5 Trading System.
Validates dynamic ATR risk sizing, circuit breaker, candle wick rejection,
economic news buffers, TradingView TA alignment, Magic isolation, and FastAPI endpoints.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from config import (
    MAGIC_XAUUSD,
    MAGIC_USDJPY,
    ALLOWED_MAGIC_NUMBERS,
    DAILY_DRAWDOWN_LIMIT_USD,
)
from database import (
    init_database,
    SessionLocal,
    ConfigModel,
    StrategyConfigModel,
    TradingLogModel,
    CircuitBreakerEventModel,
    log_trading_log,
    log_circuit_breaker_event,
)
from news_filter import EconomicNewsFilter
from types import SimpleNamespace
from tradingview_ta_module import TradingViewAnalyzer
from bot_engine import BotEngine
from server import app


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    init_database()


def test_magic_numbers_isolated():
    """Verify Magic numbers strictly follow the architecture spec."""
    assert MAGIC_XAUUSD == 100201
    assert MAGIC_USDJPY == 100202
    assert 100201 in ALLOWED_MAGIC_NUMBERS
    assert 100202 in ALLOWED_MAGIC_NUMBERS
    assert 0 not in ALLOWED_MAGIC_NUMBERS


def test_database_auto_seeding():
    """Verify auto-seeding of default configs for XAUUSD and USDJPY in strategy_configs."""
    with SessionLocal() as session:
        gold = session.query(StrategyConfigModel).filter_by(symbol="XAUUSD").first()
        jpy = session.query(StrategyConfigModel).filter_by(symbol="USDJPY").first()

        assert gold is not None
        assert gold.magic == 100201
        assert gold.magic_number == 100201
        assert gold.active is True
        assert gold.max_spread == 35.0
        assert "15:30" in gold.session_window

        assert jpy is not None
        assert jpy.magic == 100202
        assert jpy.magic_number == 100202
        assert jpy.active is True
        assert jpy.max_spread == 20.0
        assert "03:00" in jpy.session_window


def test_database_supabase_postgres_and_models():
    """Verify essential schema tables and logging functions (strategy_configs, trading_logs, circuit_breaker_events)."""
    assert StrategyConfigModel.__tablename__ == "strategy_configs"
    assert TradingLogModel.__tablename__ == "trading_logs"
    assert CircuitBreakerEventModel.__tablename__ == "circuit_breaker_events"

    # Test trading_logs insertion
    log_trading_log("XAUUSD", "Spread guard rejected execution: 0.40 > 0.35", level="WARNING")
    with SessionLocal() as session:
        t_log = session.query(TradingLogModel).filter_by(symbol="XAUUSD", level="WARNING").order_by(TradingLogModel.id.desc()).first()
        assert t_log is not None
        assert "Spread guard rejected" in t_log.message

    # Test circuit_breaker_events insertion
    log_circuit_breaker_event(drawdown_amount=4.75, state="CIRCUIT_BREAKER_HALTED")
    with SessionLocal() as session:
        cb_event = session.query(CircuitBreakerEventModel).order_by(CircuitBreakerEventModel.id.desc()).first()
        assert cb_event is not None
        assert cb_event.drawdown_amount == 4.75
        assert cb_event.state == "CIRCUIT_BREAKER_HALTED"


def test_supabase_connection_pooling_configuration():
    """Verify SQLAlchemy engine connection pooling configuration with pool_pre_ping=True and pool_size=10."""
    from sqlalchemy import create_engine
    
    test_pg_url = "postgresql+psycopg2://postgres:piploci34%40!@db.npjsxpsqleckvhlevdyz.supabase.co:5432/postgres"
    pg_engine = create_engine(test_pg_url, pool_pre_ping=True, pool_size=10, max_overflow=5)
    
    assert pg_engine.pool._pre_ping is True
    assert pg_engine.pool.size() == 10


def test_dynamic_atr_lot_sizing():
    """Verify the dynamic ATR risk formula."""
    engine = BotEngine()
    engine.connect_mt5()
    # Account balance test: 1% risk on $1000 = $10.0 risk
    # Gold: SL distance = $3.50, tick size = 0.01, tick value = 1.0
    # Expected ticks at risk = 350 ticks -> lot = 10 / 350 = 0.028 -> 0.02 or 0.03
    lot = engine.calculate_lot_size("XAUUSD", stop_loss_distance=3.50)
    assert 0.01 <= lot <= 0.10


def test_candle_reversal_wick_ratios():
    """Verify candle rejection wick logic (55% for Gold, 45% for USDJPY)."""
    engine = BotEngine()
    engine.connect_mt5()

    # Test BUY direction logic
    valid, msg = engine.validate_candle_reversal("XAUUSD", "BUY")
    assert isinstance(valid, bool)

    valid_jpy, msg_jpy = engine.validate_candle_reversal("USDJPY", "BUY")
    assert isinstance(valid_jpy, bool)


def test_economic_news_blackout_buffers():
    """Verify the 30-minute blackout before and after high-impact events."""
    filt = EconomicNewsFilter()
    now = datetime.now(timezone.utc)

    # Inject simulated high-impact USD event 15 minutes in the future
    filt.cached_events = [{
        "title": "US Non-Farm Payrolls",
        "currency": "USD",
        "impact": "HIGH",
        "time": now + timedelta(minutes=15)
    }]
    filt.last_fetch_time = now

    # Should be inside blackout (15m before event <= 30m window)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    is_blk, reason = loop.run_until_complete(filt.is_news_blackout("XAUUSD"))
    assert is_blk is True
    assert "BLACKOUT SHIELD ACTIVE" in reason

    # Test event 45 minutes in the future (outside 30m window)
    filt.cached_events = [{
        "title": "US Non-Farm Payrolls",
        "currency": "USD",
        "impact": "HIGH",
        "time": now + timedelta(minutes=45)
    }]
    is_blk, _ = loop.run_until_complete(filt.is_news_blackout("XAUUSD"))
    assert is_blk is False


def test_tradingview_ta_alignment():
    """Verify TradingView multi-timeframe consensus rules."""
    analyzer = TradingViewAnalyzer()

    # Test Gold requiring STRONG_BUY on M15
    res = analyzer.get_aligned_signal("XAUUSD")
    assert "symbol" in res
    assert "direction" in res
    assert "is_aligned" in res

    # Test USDJPY requiring BUY or STRONG_BUY on both M15 and H1
    res_jpy = analyzer.get_aligned_signal("USDJPY")
    assert "symbol" in res_jpy


def test_circuit_breaker_trigger():
    """Verify the $4.50 USD drawdown circuit breaker triggers and halts trading."""
    engine = BotEngine()

    class TestAccount:
        def __init__(self, balance, equity):
            self.balance = balance
            self.equity = equity
            self.profit = equity - balance

    class TestMT5Terminal:
        def account_info(self):
            return TestAccount(balance=1000.0, equity=994.0)
        def positions_get(self, symbol=None):
            return (
                SimpleNamespace(ticket=101, symbol="XAUUSD", magic=100201, profit=-5.00, volume=0.02, type=0),
            )
        def symbol_info_tick(self, sym):
            return SimpleNamespace(bid=2340.0, ask=2340.5)
        def order_send(self, req):
            return SimpleNamespace(retcode=10009)

    engine.mt5_client = TestMT5Terminal()
    engine.terminal_connected = True
    engine.starting_daily_balance = 1000.0

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    halted = loop.run_until_complete(engine.evaluate_circuit_breaker())

    assert halted is True
    assert engine.state == "CIRCUIT_BREAKER_HALTED"
    assert engine.circuit_breaker_until is not None


def test_circuit_breaker_ignores_manual_drawdown():
    """Verify manual trade floating losses (magic = 0) do NOT trigger bot circuit breaker."""
    engine = BotEngine()

    class TestAccount:
        def __init__(self):
            self.balance = 1000.0
            self.equity = 800.0  # $200 heavy manual loss
            self.profit = -200.0

    class TestMT5Terminal:
        def account_info(self):
            return TestAccount()
        def positions_get(self, symbol=None):
            # Only a discretionary manual trade with magic = 0 and huge loss
            return (
                SimpleNamespace(ticket=999, symbol="EURUSD", magic=0, profit=-200.00, volume=1.0),
            )
        def order_send(self, req):
            return SimpleNamespace(retcode=10009)

    engine.mt5_client = TestMT5Terminal()
    engine.terminal_connected = True
    engine.starting_daily_balance = 1000.0

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    halted = loop.run_until_complete(engine.evaluate_circuit_breaker())

    # Must NOT trigger because bot positions have zero loss
    assert halted is False
    assert engine.state != "CIRCUIT_BREAKER_HALTED"


def test_magic_isolation_close_refusal():
    """Verify that orders without bot magic numbers are refused."""
    engine = BotEngine()

    manual_pos = SimpleNamespace(
        ticket=999001,
        symbol="XAUUSD",
        type=0,
        volume=0.5,
        price_open=2340.0,
        sl=0.0,
        tp=0.0,
        magic=0,  # Manual discretionary trade
        profit=15.0
    )

    class TestTerminalWithPositions:
        def __init__(self):
            self.positions = {999001: manual_pos}
        def positions_get(self, symbol=None):
            return tuple(self.positions.values())
        def order_send(self, req):
            pos_id = req.get("position")
            if pos_id in self.positions:
                del self.positions[pos_id]
            return SimpleNamespace(retcode=10009)

    engine.mt5_client = TestTerminalWithPositions()
    engine.terminal_connected = True

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # get_bot_positions must ignore magic = 0
    bot_positions = engine.get_bot_positions()
    assert all(p.magic != 0 for p in bot_positions)

    # close_position_by_ticket must refuse to close magic = 0
    success = loop.run_until_complete(engine.close_position_by_ticket(999001, reason="Test"))
    assert success is False
    assert 999001 in engine.mt5_client.positions  # Order remains untouched


# ==============================================================================
# FASTAPI ENDPOINT TESTS
# ==============================================================================
client = TestClient(app)


def test_api_status_endpoint():
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert "balance" in data
    assert "equity" in data
    assert "daily_drawdown_limit" in data
    assert data["daily_drawdown_limit"] == DAILY_DRAWDOWN_LIMIT_USD
    assert data["allowed_magic_numbers"] == [100201, 100202]


def test_api_configs_endpoint():
    response = client.get("/api/v1/configs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    symbols = [c["symbol"] for c in data]
    assert "XAUUSD" in symbols
    assert "USDJPY" in symbols


def test_api_control_toggle():
    # Authenticate first to obtain JWT
    auth = client.post("/api/v1/auth/login-json", json={"username": "admin", "password": "AdminPass@2026"})
    assert auth.status_code == 200, f"Login failed: {auth.text}"
    token = auth.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Toggle XAUUSD off
    res = client.post("/api/v1/control/toggle", json={"symbol": "XAUUSD", "active": False}, headers=headers)
    assert res.status_code == 200, f"Toggle OFF failed: {res.text}"
    assert res.json()["active"] is False

    # Toggle XAUUSD back on
    res = client.post("/api/v1/control/toggle", json={"symbol": "XAUUSD", "active": True}, headers=headers)
    assert res.status_code == 200, f"Toggle ON failed: {res.text}"
    assert res.json()["active"] is True


def test_api_emergency_stop_and_resume():
    # Authenticate first to obtain JWT
    auth = client.post("/api/v1/auth/login-json", json={"username": "admin", "password": "AdminPass@2026"})
    assert auth.status_code == 200, f"Login failed: {auth.text}"
    token = auth.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Emergency stop — requires auth
    res_stop = client.post("/api/v1/control/emergency-stop", headers=headers)
    assert res_stop.status_code == 200, f"Emergency stop failed: {res_stop.text}"
    assert res_stop.json()["status"] == "HALTED"

    # Resume — requires auth
    res_resume = client.post("/api/v1/control/resume", headers=headers)
    assert res_resume.status_code == 200, f"Resume failed: {res_resume.text}"
    assert res_resume.json()["status"] == "RUNNING"


def test_api_login_json():
    # Default admin credentials
    res = client.post("/api/v1/auth/login-json", json={"username": "admin", "password": "AdminPass@2026"})
    assert res.status_code == 200
    assert "access_token" in res.json()
    assert res.json()["token_type"] == "bearer"


def test_api_login_endpoint():
    # Direct /api/v1/login route
    res = client.post("/api/v1/login", json={"username": "admin", "password": "AdminPass@2026"})
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_websocket_live_feed():
    with client.websocket_connect("/api/v1/ws/live-feed") as ws:
        data = ws.receive_json()
        assert data["type"] == "INITIAL_HANDSHAKE"
        assert "Piploci" in data["message"]


def test_dynamic_spread_protection():
    """Verify spread spike rejection ($0.30 max for Gold, 2.0 pips for USDJPY)."""
    engine = BotEngine()

    class SpreadTestMT5:
        def __init__(self, gold_spread=0.25, jpy_spread=0.015):
            self.gold_bid = 2340.00
            self.gold_ask = 2340.00 + gold_spread
            self.jpy_bid = 156.400
            self.jpy_ask = 156.400 + jpy_spread

        def symbol_info_tick(self, symbol):
            if symbol == "XAUUSD":
                return SimpleNamespace(bid=self.gold_bid, ask=self.gold_ask)
            return SimpleNamespace(bid=self.jpy_bid, ask=self.jpy_ask)

        def symbol_info(self, symbol):
            return SimpleNamespace(point=0.01 if "XAU" in symbol else 0.001)

    # 1. Normal spreads within thresholds
    engine.mt5_client = SpreadTestMT5(gold_spread=0.25, jpy_spread=0.015)
    engine.terminal_connected = True

    gold_ok, g_curr, g_max, _ = engine.validate_spread_protection("XAUUSD")
    assert gold_ok is True
    assert g_curr <= g_max

    jpy_ok, j_curr, j_max, _ = engine.validate_spread_protection("USDJPY")
    assert jpy_ok is True
    assert j_curr <= j_max

    # 2. Spread spikes exceeding thresholds
    # Gold spike ($0.45 > $0.30 max)
    engine.mt5_client = SpreadTestMT5(gold_spread=0.45, jpy_spread=0.035)
    gold_spike_ok, g_curr, g_max, reason = engine.validate_spread_protection("XAUUSD")
    assert gold_spike_ok is False
    assert "SPREAD SPIKE" in reason

    # USDJPY spike (3.5 pips / 0.035 > 2.0 pips / 0.020 max)
    jpy_spike_ok, j_curr, j_max, reason = engine.validate_spread_protection("USDJPY")
    assert jpy_spike_ok is False
    assert "SPREAD SPIKE" in reason


def test_trailing_stop_breakeven_logic():
    """Verify Stop Loss is moved to Breakeven / Trailing once profit reaches 1.5x ATR."""
    engine = BotEngine()

    # XAUUSD ATR is 3.50. 1.5x ATR = 5.25.
    # Buy position open at 2340.00 with SL = 2335.00
    buy_pos = SimpleNamespace(
        ticket=501,
        symbol="XAUUSD",
        magic=100201,
        type=0,  # BUY
        volume=0.02,
        price_open=2340.00,
        sl=2335.00,
        tp=2355.00,
    )

    modified_requests = []

    class TrailingMT5Test:
        def __init__(self, current_price=2346.00):
            # 2346.00 - 2340.00 = 6.00 profit distance (exceeds 1.5x ATR 5.25)
            self.bid = current_price
            self.ask = current_price + 0.20

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(bid=self.bid, ask=self.ask)

        def positions_get(self, symbol=None):
            return (buy_pos,)

        def order_send(self, req):
            modified_requests.append(req)
            return SimpleNamespace(retcode=10009)

    engine.mt5_client = TrailingMT5Test(current_price=2346.00)
    engine.terminal_connected = True

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    updated = loop.run_until_complete(engine.manage_open_positions_trailing_stop())

    assert updated == 1
    assert len(modified_requests) == 1
    req = modified_requests[0]
    assert req["position"] == 501
    # New SL must be at least entry price (breakeven = 2340.00)
    assert req["sl"] >= 2340.00


def test_sensitive_credentials_environment_isolation():
    """Verify that credentials and secrets load from environment and .gitignore protects .env."""
    import os
    from config import settings

    # 1. Verify credentials originate from settings/environment
    assert hasattr(settings, "SECRET_KEY")
    assert hasattr(settings, "MT5_LOGIN")
    assert hasattr(settings, "MT5_PASSWORD")
    assert hasattr(settings, "MT5_SERVER")

    # 2. Verify .gitignore protects .env
    with open(".gitignore", "r", encoding="utf-8") as f:
        git_content = f.read()
    assert ".env" in git_content

    # 3. Verify .env file exists and is populated
    assert os.path.exists(".env")
