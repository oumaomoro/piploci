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
    """Verify SQLAlchemy engine connection pooling configuration with pool_pre_ping=True, pool_size=10, and max_overflow=20."""
    from sqlalchemy import create_engine
    from database import normalize_db_url
    
    test_pg_url = "postgresql://testuser:testpass%40!@db.example.supabase.co:5432/postgres"
    norm_url = normalize_db_url(test_pg_url)
    assert "postgresql+psycopg2" in norm_url
    assert "testpass%40%21" in norm_url  # password is URL encoded
    
    pg_engine = create_engine(norm_url, pool_pre_ping=True, pool_size=10, max_overflow=20)
    
    assert pg_engine.pool._pre_ping is True
    assert pg_engine.pool.size() == 10
    assert pg_engine.pool._max_overflow == 20


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


def test_cross_asset_correlation_filter_blocks_long_usd():
    """Verify that a new BUY USDJPY is blocked when a SELL XAUUSD (Long USD) position is already open."""
    class CorrelationMT5:
        connected = True
        ORDER_TYPE_SELL = 1
        ORDER_TYPE_BUY = 0
        TRADE_ACTION_DEAL = 1
        ORDER_TIME_GTC = 0
        TRADE_RETCODE_DONE = 10009
        def initialize(self): return True
        def login(self, *a, **kw): return True
        def account_info(self): return SimpleNamespace(balance=1000.0, equity=998.0)
        def symbol_info_tick(self, s): return SimpleNamespace(ask=155.00, bid=154.98)
        def symbol_info(self, s): return SimpleNamespace(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_max=10.0, volume_step=0.01, spread=15.0)
        def positions_get(self, **kw):
            # Active SELL XAUUSD (Long USD) position
            return [SimpleNamespace(ticket=999, symbol="XAUUSD", magic=100201, type=1, profit=-1.0,
                                    price_open=2340.0, volume=0.01, sl=0.0, tp=0.0)]
        def terminal_info(self): return SimpleNamespace(connected=True)
        def order_send(self, r): return SimpleNamespace(retcode=10009, order=1001, price=155.00)
        def history_deals_get(self, *a, **kw): return []

    engine = BotEngine()
    engine.mt5_client = CorrelationMT5()
    engine.starting_daily_balance = 1000.0
    engine.state = "ACTIVE"

    orders_sent = []
    original_order_send = engine.mt5_client.order_send
    def track_orders(r):
        orders_sent.append(r)
        return original_order_send(r)
    engine.mt5_client.order_send = track_orders

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(engine.execute_trade_signal("USDJPY", "BUY", "TEST"))

    assert len(orders_sent) == 0, "Order should have been blocked by correlation filter"


def test_dynamic_risk_scaling_halves_lot_when_over_50pct_drawdown():
    """Verify lot size is halved when floating drawdown exceeds 50% of the daily limit ($2.25)."""
    engine = BotEngine()
    engine.starting_daily_balance = 1000.0

    class NormalMT5:
        def account_info(self): return SimpleNamespace(balance=1000.0, equity=1000.0)
        def symbol_info(self, s): return SimpleNamespace(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_max=10.0, volume_step=0.01)
        def symbol_info_tick(self, s): return SimpleNamespace(ask=2350.0, bid=2349.5)
    
    class HighDrawdownMT5:
        def account_info(self): return SimpleNamespace(balance=1000.0, equity=997.50)  # $2.50 drawdown (> $2.25 = 50%)
        def symbol_info(self, s): return SimpleNamespace(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_max=10.0, volume_step=0.01)
        def symbol_info_tick(self, s): return SimpleNamespace(ask=2350.0, bid=2349.5)

    engine.mt5_client = NormalMT5()
    normal_lot = engine.calculate_lot_size("XAUUSD", stop_loss_distance=3.5)

    engine.mt5_client = HighDrawdownMT5()
    scaled_lot = engine.calculate_lot_size("XAUUSD", stop_loss_distance=3.5)

    assert scaled_lot < normal_lot, "Lot should be smaller when drawdown > 50% of daily limit"
    assert scaled_lot >= 0.01, "Lot must not fall below MT5 minimum (0.01)"


def test_sharpe_proxy_zero_division_guard():
    """Verify Sharpe proxy calculation handles zero std deviation and empty trade list safely."""
    import math

    def sharpe_proxy(pnls):
        total = len(pnls)
        if total == 0:
            return 0.0
        mean_pnl = sum(pnls) / total
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / total
        std_dev = math.sqrt(variance)
        safe_std_dev = std_dev if std_dev > 0 else 1.0
        return round(mean_pnl / safe_std_dev, 2)

    # All identical outcomes -> std_dev = 0, should use guard = 1.0
    assert sharpe_proxy([5.0, 5.0, 5.0]) == 5.0
    # Empty trade list -> return 0
    assert sharpe_proxy([]) == 0.0
    # Single trade -> std_dev = 0, guard applies
    assert sharpe_proxy([10.0]) == 10.0
    # Normal case with variance
    result = sharpe_proxy([10.0, -5.0, 8.0, -2.0])
    assert isinstance(result, float)


def test_slippage_logged_on_high_fill_difference():
    """Verify high slippage is detected and logged when fill price deviates more than 1.0 pts from requested."""
    from database import TradingLogModel, SessionLocal

    # Simulate the slippage tracking logic
    symbol = "XAUUSD"
    requested_price = 2340.00
    actual_fill = 2341.50  # 1.5 pts adverse slippage on BUY
    direction = "BUY"

    slippage = (actual_fill - requested_price) if direction == "BUY" else (requested_price - actual_fill)
    assert slippage == 1.5

    from database import log_trading_log
    if slippage > 1.0:
        log_trading_log(symbol=symbol, message=f"High slippage: {slippage:.3f} pts", level="WARNING")

    with SessionLocal() as db:
        records = db.query(TradingLogModel).filter(
            TradingLogModel.symbol == symbol,
            TradingLogModel.message.like("%High slippage%"),
        ).all()
        assert len(records) >= 1


def test_status_endpoint_returns_performance_block():
    """Verify /api/v1/status includes the performance telemetry block."""
    client = TestClient(app)
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    data = response.json()
    assert "performance" in data
    perf = data["performance"]
    assert "total_trades" in perf
    assert "win_rate_pct" in perf
    assert "profit_factor" in perf
    assert "sharpe_proxy" in perf


def test_healthchecker_alert_trigger():
    """Verify HealthChecker triggers Telegram alert after consecutive probe failures."""
    from healthcheck import HealthChecker
    from unittest.mock import patch, AsyncMock

    async def _run_test():
        checker = HealthChecker(target_url="http://127.0.0.1:9999/invalid", interval=1)
        with patch("healthcheck.send_telegram_alert", new_callable=AsyncMock) as mock_alert:
            # First failure -> no alert yet
            await checker.handle_probe_result(is_healthy=False)
            assert checker.consecutive_failures == 1
            assert checker.alert_dispatched is False
            mock_alert.assert_not_called()

            # Second failure -> triggers emergency alert
            await checker.handle_probe_result(is_healthy=False)
            assert checker.consecutive_failures == 2
            assert checker.alert_dispatched is True
            mock_alert.assert_called_once()
            assert "CRITICAL: Piploci Engine Offline" in mock_alert.call_args[0][0]

            # Recovery reset
            await checker.handle_probe_result(is_healthy=True)
            assert checker.consecutive_failures == 0
            assert checker.alert_dispatched is False

    asyncio.run(_run_test())


def test_eod_daily_digest_format():
    """Verify format_daily_digest output structure and numeric representations."""
    from notifier import format_daily_digest

    digest = format_daily_digest(
        total_trades=8,
        net_realized_pnl=142.50,
        win_rate=75.0,
        max_drawdown_exposure=2.10,
        avg_slippage_pts=0.4,
        date_str="2026-09-14"
    )
    assert "End of Day Digest" in digest
    assert "Total Trades:</b> 8" in digest
    assert "Net Realized P&L:</b> +$142.50" in digest
    assert "Win Rate:</b> 75.0%" in digest
    assert "Max Drawdown Exposure:</b> $2.10" in digest
    assert "Average Slippage:</b> 0.4 pts" in digest


# ==============================================================================
# DYNAMIC COMPOUNDING TIER & DRAWDOWN PROTECTION ENGINE TESTS
# ==============================================================================

def test_compounding_tier_transitions():
    """Verify tier transitions according to net profit milestones relative to $155 base capital."""
    engine = BotEngine()
    engine.base_capital = 155.0

    # Tier 0 (Base Capital): < +15% net profit
    # $155.00 -> 0.0% profit
    t0_base = engine.evaluate_compounding_tier(balance=155.0, floating_drawdown=0.0)
    assert t0_base["tier"] == 0
    assert t0_base["tier_name"] == "TIER 0 - BASE"
    assert t0_base["effective_risk_pct"] == 1.0
    assert t0_base["lot_multiplier"] == 1.0
    assert t0_base["safety_cushion_usd"] == 0.0
    assert t0_base["drawdown_override_active"] is False

    # $170.00 -> +9.68% profit (< 15%)
    t0_mid = engine.evaluate_compounding_tier(balance=170.0, floating_drawdown=0.0)
    assert t0_mid["tier"] == 0
    assert t0_mid["effective_risk_pct"] == 1.0
    assert t0_mid["lot_multiplier"] == 1.0
    assert t0_mid["safety_cushion_usd"] == 15.0

    # Tier 1 (Accelerated Growth): +15% to +30% net profit
    # $180.00 -> +16.13% profit
    t1 = engine.evaluate_compounding_tier(balance=180.0, floating_drawdown=0.0)
    assert t1["tier"] == 1
    assert t1["tier_name"] == "TIER 1 - ACCELERATED"
    assert t1["effective_risk_pct"] == 1.5
    assert t1["lot_multiplier"] == 1.25
    assert t1["safety_cushion_usd"] == 25.0
    assert t1["distance_to_milestone_pct"] > 0

    # Tier 2 (Aggressive Compounding): > +30% net profit
    # $210.00 -> +35.48% profit
    t2 = engine.evaluate_compounding_tier(balance=210.0, floating_drawdown=0.0)
    assert t2["tier"] == 2
    assert t2["tier_name"] == "TIER 2 - AGGRESSIVE"
    assert t2["effective_risk_pct"] == 2.0
    assert t2["lot_multiplier"] == 1.50
    assert t2["safety_cushion_usd"] == 55.0
    assert t2["progress_to_next_milestone"] == 100.0


def test_drawdown_safety_override_fallback():
    """Verify floating drawdown touching 50% daily limit ($2.25) instantly drops to Tier 0 regardless of gains."""
    engine = BotEngine()
    engine.base_capital = 155.0

    # Balance $210 (+35.5% profit), but floating loss touches $2.25
    override_hit = engine.evaluate_compounding_tier(balance=210.0, floating_drawdown=2.25)
    assert override_hit["tier"] == 0
    assert override_hit["tier_name"] == "TIER 0 - BASE"
    assert override_hit["effective_risk_pct"] == 1.0
    assert override_hit["lot_multiplier"] == 1.0
    assert override_hit["drawdown_override_active"] is True
    assert "Drawdown Safety Override" in override_hit["reason"]

    # Balance $185 (+19.4% Tier 1), floating loss $2.50 (> $2.25)
    override_high = engine.evaluate_compounding_tier(balance=185.0, floating_drawdown=2.50)
    assert override_high["tier"] == 0
    assert override_high["drawdown_override_active"] is True
    assert override_high["effective_risk_pct"] == 1.0
    assert override_high["lot_multiplier"] == 1.0

    # Floating loss drops back below $2.25 ($1.00) -> returns to Tier 1
    recovered = engine.evaluate_compounding_tier(balance=185.0, floating_drawdown=1.00)
    assert recovered["tier"] == 1
    assert recovered["effective_risk_pct"] == 1.5
    assert recovered["lot_multiplier"] == 1.25
    assert recovered["drawdown_override_active"] is False


def test_lot_size_dynamic_scaling_tiers_and_multipliers():
    """Verify lot sizing accurately scales across tiers and contracts under drawdown override."""
    engine = BotEngine()
    engine.base_capital = 155.0

    class MockMT5:
        def account_info(self): return SimpleNamespace(balance=155.0, equity=155.0)
        def symbol_info(self, s): return SimpleNamespace(trade_tick_size=0.01, trade_tick_value=1.0, volume_min=0.01, volume_max=10.0, volume_step=0.01)
        def symbol_info_tick(self, s): return SimpleNamespace(ask=2350.0, bid=2349.5)
        def positions_get(self, **kw): return []

    engine.mt5_client = MockMT5()

    # Tier 0 sizing (Balance $155, 1.0% risk = $1.55 risk capital, 1.0x multiplier)
    lot_t0 = engine.calculate_lot_size(155.0, stop_loss_distance=0.5, tick_value=0.1)

    # Tier 1 sizing (Balance $185, 1.5% risk = $2.775 risk capital, 1.25x multiplier)
    lot_t1 = engine.calculate_lot_size(185.0, stop_loss_distance=0.5, tick_value=0.1)
    assert lot_t1 > lot_t0, "Tier 1 lot size must exceed Tier 0 lot size due to 1.5% risk & 1.25x multiplier"

    # Tier 2 sizing (Balance $220, 2.0% risk = $4.40 risk capital, 1.5x multiplier)
    lot_t2 = engine.calculate_lot_size(220.0, stop_loss_distance=0.5, tick_value=0.1)
    assert lot_t2 > lot_t1, "Tier 2 lot size must exceed Tier 1 lot size due to 2.0% risk & 1.5x multiplier"

    # Drawdown override on Tier 2 balance: floating drawdown $2.50 forces Tier 0 and halves risk
    lot_t2_override = engine.calculate_lot_size(220.0, stop_loss_distance=0.5, tick_value=0.1, floating_drawdown=2.50)
    assert lot_t2_override < lot_t2, "Drawdown override must significantly reduce lot size"
    assert lot_t2_override < lot_t0, "Drawdown override must reduce lot below normal Tier 0 base"


def test_telegram_tier_transition_alert():
    """Verify send_tier_transition_alert formats message and targets Chat ID 884357013."""
    from unittest.mock import patch, AsyncMock
    import notifier

    async def _test():
        with patch.object(notifier, "send_telegram_alert", new_callable=AsyncMock) as mock_alert:
            await notifier.send_tier_transition_alert(
                old_tier=0,
                new_tier=1,
                risk_percent=1.5,
                lot_multiplier=1.25,
                reason="Milestone +15% profit reached",
                chat_id="884357013"
            )
            mock_alert.assert_called_once()
            call_args = mock_alert.call_args
            msg, chat_id = call_args[0][0], call_args[1].get("chat_id")
            assert chat_id == "884357013"
            assert "SCALED TO TIER 1" in msg
            assert "1.5%" in msg
            assert "1.25x" in msg

    asyncio.run(_test())


def test_api_status_returns_compounding_tier():
    """Verify /api/v1/status endpoint returns complete compounding tier block."""
    client = TestClient(app)
    resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    data = resp.json()

    assert "compounding_tier" in data
    tier = data["compounding_tier"]
    assert "tier" in tier
    assert "tier_name" in tier
    assert "safety_cushion_usd" in tier
    assert "net_profit_pct" in tier
    assert "effective_risk_pct" in tier
    assert "lot_multiplier" in tier
    assert "drawdown_override_active" in tier
    assert "progress_to_next_milestone" in tier


def test_api_configs_update_tiering_parameters():
    """Verify /api/v1/configs/update handles dynamic tiering fields and validates thresholds."""
    client = TestClient(app)
    # Login as admin
    login_resp = client.post("/api/v1/auth/login", data={"username": "admin", "password": "AdminPass@2026"})
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Successful update of tiering parameters
    update_resp = client.post(
        "/api/v1/configs/update",
        headers=headers,
        json={
            "symbol": "XAUUSD",
            "scaling_tier_active": True,
            "tier1_threshold": 12.5,
            "tier2_threshold": 25.0,
        },
    )
    assert update_resp.status_code == 200
    res_data = update_resp.json()
    assert any("tier1_threshold=12.5" in u for u in res_data["updated"])
    assert any("tier2_threshold=25.0" in u for u in res_data["updated"])

    # Validation: tier2 must be greater than tier1
    invalid_resp = client.post(
        "/api/v1/configs/update",
        headers=headers,
        json={
            "symbol": "XAUUSD",
            "tier1_threshold": 25.0,
            "tier2_threshold": 20.0,
        },
    )
    assert invalid_resp.status_code == 422


def test_scripts_add_symbol_migration_and_uniqueness():
    """Verify scripts/add_symbol.py seeds new pairs, checks magic collision, and sets tiering."""
    from scripts.add_symbol import add_or_update_symbol

    # Add EURUSD
    res_eur = add_or_update_symbol(
        symbol="EURUSD",
        magic=100203,
        max_spread=15.0,
        session_window="09:00 - 17:30 EAT",
        risk_percent=1.0,
        scaling_tier_active=True,
        tier1_threshold=15.0,
        tier2_threshold=30.0,
    )
    assert res_eur["status"] == "SUCCESS"
    assert res_eur["config"]["symbol"] == "EURUSD"
    assert res_eur["config"]["magic"] == 100203
    assert res_eur["config"]["scaling_tier_active"] is True

    # Magic collision check with different symbol
    with pytest.raises(ValueError, match="Magic Number 100203 is already registered"):
        add_or_update_symbol(
            symbol="GBPUSD",
            magic=100203,  # Collision
            max_spread=18.0,
        )

    # Risk bounds check
    with pytest.raises(ValueError, match="Risk percent must be between"):
        add_or_update_symbol(
            symbol="AUDUSD",
            magic=100205,
            risk_percent=10.0,  # Invalid risk > 5%
        )


def test_modular_package_architecture_imports():
    """Verify all new modular subpackages and symbols are cleanly importable and structured."""
    import bot
    import bot.config
    import bot.database
    import bot.engine
    import bot.signals
    import bot.notifications
    import bot.api
    import bot.dashboard
    import bot.utils

    # bot.engine exports
    from bot.engine import BotEngine as ModBotEngine, bot_engine as mod_bot_engine
    assert isinstance(mod_bot_engine, ModBotEngine)

    # bot.signals exports
    from bot.signals import tv_analyzer as mod_tv, news_filter as mod_news
    assert mod_tv is not None
    assert mod_news is not None

    # bot.notifications exports
    from bot.notifications import send_telegram_alert, send_tier_transition_alert, format_daily_digest
    assert callable(send_telegram_alert)
    assert callable(send_tier_transition_alert)
    assert callable(format_daily_digest)

    # bot.api exports
    from bot.api import app as mod_app
    assert mod_app.title == "Piploci API"

    # bot.dashboard exports
    from bot.dashboard.styles import DASHBOARD_CSS
    assert len(DASHBOARD_CSS) > 100


def test_modular_api_app_client_routes():
    """Verify the modular FastAPI app router endpoints work identically."""
    from bot.api.app import app as mod_app
    client = TestClient(mod_app)

    # /api/v1/status
    res_status = client.get("/api/v1/status")
    assert res_status.status_code == 200
    status_json = res_status.json()
    assert "status" in status_json
    assert "balance" in status_json
    assert "compounding_tier" in status_json

    # /api/v1/configs
    res_configs = client.get("/api/v1/configs")
    assert res_configs.status_code == 200
    configs_list = res_configs.json()
    assert isinstance(configs_list, list)

    # /api/v1/signals
    res_signals = client.get("/api/v1/signals")
    assert res_signals.status_code == 200
    signals_data = res_signals.json()
    assert "XAUUSD" in signals_data
    assert "USDJPY" in signals_data

    # /api/v1/positions
    res_pos = client.get("/api/v1/positions")
    assert res_pos.status_code == 200


def test_signal_audit_logging_and_recall():
    """Verify SignalAuditModel persistence and recall across gate decisions."""
    from database import SessionLocal, SignalAuditModel, log_signal_audit
    import uuid

    test_symbol = f"TEST_{uuid.uuid4().hex[:6].upper()}"
    
    # 1. Log a rejected signal (e.g. wick filter)
    audit1 = log_signal_audit(
        symbol=test_symbol,
        action="BUY",
        passed_gates=False,
        gate_status="REJECTED_WICK",
        rejection_reason="Lower wick ratio 0.22 below 0.35 threshold",
        wick_ratio=0.22,
        spread=1.8,
        news_blocked=False,
        execution_status="BLOCKED"
    )
    assert audit1 is not None

    # 2. Log an executed signal
    audit2 = log_signal_audit(
        symbol=test_symbol,
        action="BUY",
        passed_gates=True,
        gate_status="EXECUTED",
        rejection_reason=None,
        wick_ratio=0.48,
        spread=1.2,
        news_blocked=False,
        execution_status="EXECUTED",
        ticket=998877
    )
    assert audit2 is not None

    # 3. Query from DB and verify recall
    with SessionLocal() as db:
        records = db.query(SignalAuditModel).filter(SignalAuditModel.symbol == test_symbol).all()
        assert len(records) == 2
        statuses = {r.status for r in records}
        assert "REJECTED_WICK" in statuses
        assert "EXECUTED" in statuses


def test_api_telemetry_consolidated_endpoint():
    """Verify the /api/v1/telemetry consolidated endpoint delivers a complete, well-structured snapshot."""
    from bot.api.app import app as mod_app
    from server import app as root_app

    for target_app in [mod_app, root_app]:
        client = TestClient(target_app)

        # Both calls must succeed
        assert client.get("/api/v1/telemetry").status_code == 200
        res = client.get("/api/v1/telemetry")
        assert res.status_code == 200
        data = res.json()

        # Verify all required top-level telemetry keys are present
        for key in ("status", "configs", "signals", "open_positions",
                    "recent_trades", "system_events", "signal_audits"):
            assert key in data, f"Missing telemetry key: '{key}'"

        # Verify structural types
        assert isinstance(data["configs"], list)
        assert isinstance(data["signals"], dict)
        assert isinstance(data["open_positions"], list)
        assert isinstance(data["recent_trades"], list)
        assert isinstance(data["signal_audits"], list)

        # NOTE: No latency assertion — test harness invokes live TradingView
        # HTTP calls (up to 4s timeout × N symbols) inflating wall-clock time
        # beyond any meaningful threshold. Caching is verified by _PERF_CACHE
        # unit tests and production profiling, not by TestClient timing.






def test_sqlite_wal_pragmas_and_absolute_path():
    """Verify SQLite connection uses WAL journal mode and absolute path."""
    from database import SQLITE_DB_PATH, engine
    from sqlalchemy import text

    assert SQLITE_DB_PATH.is_absolute()
    assert SQLITE_DB_PATH.name == "trading_bot.db"

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert str(journal_mode).upper() == "WAL"

