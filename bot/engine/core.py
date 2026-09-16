"""
Bot Execution Engine and MT5 Trade Controller.
Coordinates MT5 terminal connection, session schedules, candle wick validation,
risk protection, and autonomous cycle execution.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple, Any, Callable

import pytz

try:
    import MetaTrader5 as mt5  # type: ignore[import-untyped]
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

try:
    from bot.config import (
        BASE_CAPITAL_USD,
        TIMEZONE_EAT,
        SESSION_WINDOWS,
        SYMBOL_CONFIGS,
        MT5_LOGIN,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_PATH,
        MT5_HEARTBEAT_INTERVAL_SECONDS,
    )
    from bot.database import (
        SessionLocal,
        ConfigModel,
        log_system_event,
        log_signal_audit,
    )
    from bot.signals.news import news_filter
    from bot.signals.tradingview import tv_analyzer
    from bot.engine.risk import RiskEngineMixin
    from bot.engine.execution import ExecutionEngineMixin
except ImportError:
    from config import (
        BASE_CAPITAL_USD,
        TIMEZONE_EAT,
        SESSION_WINDOWS,
        SYMBOL_CONFIGS,
        MT5_LOGIN,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_PATH,
        MT5_HEARTBEAT_INTERVAL_SECONDS,
    )
    from database import (
        SessionLocal,
        ConfigModel,
        log_system_event,
        log_signal_audit,
    )
    from news_filter import news_filter
    from tradingview_ta_module import tv_analyzer
    from bot.engine.risk import RiskEngineMixin
    from bot.engine.execution import ExecutionEngineMixin

logger = logging.getLogger("BotEngine")


class BotEngine(RiskEngineMixin, ExecutionEngineMixin):
    """Core autonomous trading execution engine."""

    def __init__(self):
        self.state: str = "INITIALIZING"  # INITIALIZING, RUNNING, CIRCUIT_BREAKER_HALTED, HALTED
        self.terminal_connected: bool = False
        self.starting_daily_balance: float = 1000.0
        self.last_balance_reset_date = datetime.now(timezone.utc).date()
        self.circuit_breaker_until: Optional[datetime] = None
        self.broadcast_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self.mt5_client: Any = None
        self._loop_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self.is_halted: bool = False
        self.halt_expiration: Optional[datetime] = None
        self.base_capital: float = BASE_CAPITAL_USD
        self.current_tier: int = 0
        self.last_tier_transition: Optional[datetime] = None

    def register_broadcast_callback(self, cb: Callable[[Dict[str, Any]], None]):
        """Registers a callback function to receive live telemetry and log broadcasts."""
        self.broadcast_callbacks.append(cb)

    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Dispatches real-time event to all registered listeners."""
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        for cb in list(self.broadcast_callbacks):
            try:
                res = cb(payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error invoking broadcast callback: {e}")

    def connect_mt5(self) -> bool:
        """Initializes connection to Live MT5 terminal."""
        if MT5_AVAILABLE:
            init_args = {}
            if MT5_PATH:
                init_args["path"] = MT5_PATH
            if MT5_LOGIN > 0:
                init_args["login"] = MT5_LOGIN
                init_args["password"] = MT5_PASSWORD
                init_args["server"] = MT5_SERVER

            try:
                connected = mt5.initialize(**init_args)
                if connected:
                    self.mt5_client = mt5
                    self.terminal_connected = True
                    acct = mt5.account_info()
                    self.starting_daily_balance = getattr(acct, "balance", 1000.0) if acct else 1000.0
                    self.state = "RUNNING"
                    logger.info("Connected directly to Live MT5 Terminal.")
                    return True
                else:
                    err = mt5.last_error()
                    logger.warning(f"MT5 terminal initialization returned False: {err}")
            except Exception as e:
                logger.warning(f"Could not connect to MT5 desktop terminal: {e}")

        self.mt5_client = None
        self.terminal_connected = False
        self.state = "WAITING_TERMINAL"
        logger.warning("MT5 Terminal is not connected. Awaiting connection via heartbeat monitor...")
        return False

    initialize_mt5 = connect_mt5

    async def _heartbeat_loop(self):
        """Monitors MT5 connection health and automatically reconnects if disconnected."""
        while True:
            try:
                if self.mt5_client:
                    term = self.mt5_client.terminal_info()
                    if not term or not getattr(term, "connected", False):
                        logger.warning("MT5 Terminal disconnect detected. Reconnecting...")
                        self.terminal_connected = False
                        self.connect_mt5()
                    else:
                        self.terminal_connected = True
                else:
                    self.connect_mt5()
            except Exception as e:
                logger.error(f"Heartbeat monitor error: {e}")
            await asyncio.sleep(MT5_HEARTBEAT_INTERVAL_SECONDS)

    def is_within_trading_session(self, symbol: str) -> Tuple[bool, str]:
        """
        Validates if current time in East Africa Time (EAT - UTC+3) is within allowed session windows:
        - XAUUSD: 15:30 to 19:30 EAT
        - USDJPY: 03:00 to 07:00 EAT OR 15:30 to 19:30 EAT
        """
        eat_zone = pytz.timezone(TIMEZONE_EAT)
        now_eat = datetime.now(eat_zone).time()

        windows = SESSION_WINDOWS.get(symbol, [])
        for start_str, end_str in windows:
            start_t = datetime.strptime(start_str, "%H:%M").time()
            end_t = datetime.strptime(end_str, "%H:%M").time()

            if start_t <= now_eat <= end_t:
                return True, f"In Session ({start_str} - {end_str} EAT)"

        return False, f"Outside Session Window for {symbol} (Current EAT: {now_eat.strftime('%H:%M:%S')})"

    def is_session_active(self, symbol: str) -> bool:
        active, _ = self.is_within_trading_session(symbol)
        return active

    def calculate_atr(self, symbol: str, period: int = 14) -> float:
        """
        Calculates Average True Range on M15 timeframe using real broker data.
        Fetches the last `period+1` closed M15 candles from MT5 and computes
        the Wilder ATR. Falls back to per-symbol conservative defaults if MT5
        data is unavailable.
        """
        # Per-symbol safe fallback ATR values — realistic M15 ATR in price units.
        # Only used when MT5 is offline. Calibrated to typical broker conditions.
        # 0.15 * ATR gives the max spread gate:
        #   XAUUSD:  0.15 * 3.50  = $0.525  (plenty of room for gold spreads)
        #   USDJPY:  0.15 * 0.35  = 0.0525  (~5 pips, generous for JPY pairs)
        #   EURUSD:  0.15 * 0.0008 = too tight! → use 0.010 fallback → gate = 0.0015 (1.5 pips)
        FALLBACK_ATR = {
            "XAUUSD": 3.50,    # ~$3.50 M15 ATR typical during London/NY
            "USDJPY": 0.35,    # ~35 pips M15 ATR
            "EURUSD": 0.010,   # ~10 pips M15 ATR → max spread gate 1.5 pips
            "GBPUSD": 0.013,   # ~13 pips M15 ATR → max spread gate ~2 pips
            "AUDUSD": 0.009,   # ~9 pips  M15 ATR → max spread gate ~1.3 pips
            "USDCAD": 0.010,   # ~10 pips M15 ATR → max spread gate ~1.5 pips
            "USDCHF": 0.009,   # ~9 pips  M15 ATR → max spread gate ~1.3 pips
            "NZDUSD": 0.008,   # ~8 pips  M15 ATR → max spread gate ~1.2 pips
        }

        if not self.mt5_client:
            return FALLBACK_ATR.get(symbol, 0.00080)

        try:
            tf = getattr(self.mt5_client, "TIMEFRAME_M15", 15)
            # Fetch period+1 candles so we have `period` True Range values
            rates = self.mt5_client.copy_rates_from_pos(symbol, tf, 1, period + 1)

            if rates is None or len(rates) < 2:
                return FALLBACK_ATR.get(symbol, 0.00080)

            true_ranges = []
            for i in range(1, len(rates)):
                c = rates[i]
                p = rates[i - 1]

                if isinstance(c, dict):
                    high, low, prev_close = c["high"], c["low"], p["close"]
                else:
                    high, low, prev_close = c[2], c[3], p[4]

                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)

            if not true_ranges:
                return FALLBACK_ATR.get(symbol, 0.00080)

            # Simple average (sufficient for entry-time ATR filter)
            atr = sum(true_ranges) / len(true_ranges)
            return round(atr, 6)

        except Exception as e:
            logger.warning(f"ATR calculation failed for {symbol}: {e}. Using fallback.")
            return FALLBACK_ATR.get(symbol, 0.00080)

    def validate_h4_trend(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """
        Validates M15 signal against H4 macro trend (SMA 200).
        """
        if not self.mt5_client:
            return False, "MT5 not connected"
            
        tf = getattr(self.mt5_client, "TIMEFRAME_H4", 16388) # MT5 TIMEFRAME_H4 is usually 16388
        rates = self.mt5_client.copy_rates_from_pos(symbol, tf, 1, 200)
        
        if rates is None or len(rates) < 200:
            return True, "Insufficient H4 data for SMA200"
            
        # Compute SMA200
        closes = [r["close"] if isinstance(r, dict) else r[4] for r in rates]
        sma200 = sum(closes) / len(closes)
        
        tick = self.mt5_client.symbol_info_tick(symbol)
        if not tick:
            return False, "No live tick data"
            
        current_price = getattr(tick, "ask" if direction == "BUY" else "bid", 0.0)
        
        if direction == "BUY":
            if current_price > sma200:
                return True, f"H4 Trend Aligned: {current_price:.3f} > SMA200 ({sma200:.3f})"
            return False, f"H4 Trend Block: {current_price:.3f} <= SMA200 ({sma200:.3f})"
        elif direction == "SELL":
            if current_price < sma200:
                return True, f"H4 Trend Aligned: {current_price:.3f} < SMA200 ({sma200:.3f})"
            return False, f"H4 Trend Block: {current_price:.3f} >= SMA200 ({sma200:.3f})"
            
        return False, "Unknown direction"

    def validate_candle_reversal(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """
        Verifies rejection wick proportion on the LAST COMPLETED M15 candle (bar[1]).
        Also enforces that the closed candle's body direction matches the signal.
        """
        cfg = SYMBOL_CONFIGS.get(symbol, {})
        min_ratio = cfg.get("min_reversal_wick_ratio", 0.50)

        if not self.mt5_client:
            return False, "MT5 terminal not connected"

        tf = getattr(self.mt5_client, "TIMEFRAME_M15", 15)
        # Strictly evaluate closed candle (pos=1)
        rates = self.mt5_client.copy_rates_from_pos(symbol, tf, 1, 1)

        if rates is None or len(rates) == 0:
            rates = self.mt5_client.copy_rates_from_pos(symbol, tf, 0, 2)
            if rates is not None and len(rates) >= 2:
                last_candle = rates[0]
            else:
                return False, "Rates unavailable - candle check rejected for safety"
        else:
            last_candle = rates[0]

        c_open = last_candle["open"] if isinstance(last_candle, dict) else last_candle[1]
        c_high = last_candle["high"] if isinstance(last_candle, dict) else last_candle[2]
        c_low = last_candle["low"] if isinstance(last_candle, dict) else last_candle[3]
        c_close = last_candle["close"] if isinstance(last_candle, dict) else last_candle[4]

        total_range = c_high - c_low
        min_range = 0.10 if symbol == "XAUUSD" else 0.04
        if total_range < min_range:
            return False, f"Flat candle range ({total_range:.3f} < {min_range:.3f}) - rejecting doji bar"

        if direction == "BUY":
            # Require a bullish close (or doji) for a buy signal
            if c_close < c_open:
                return False, "Closed M15 candle body is bearish (Wait for bullish close)"
                
            lower_wick = min(c_open, c_close) - c_low
            ratio = lower_wick / total_range
            if ratio >= min_ratio:
                return True, f"Bullish Wick Ratio {ratio * 100:.1f}% >= {min_ratio * 100:.0f}%"
            return False, f"Bullish Wick {ratio * 100:.1f}% < required {min_ratio * 100:.0f}%"

        elif direction == "SELL":
            # Require a bearish close (or doji) for a sell signal
            if c_close > c_open:
                return False, "Closed M15 candle body is bullish (Wait for bearish close)"
                
            upper_wick = c_high - max(c_open, c_close)
            ratio = upper_wick / total_range
            if ratio >= min_ratio:
                return True, f"Bearish Wick Ratio {ratio * 100:.1f}% >= {min_ratio * 100:.0f}%"
            return False, f"Bearish Wick {ratio * 100:.1f}% < required {min_ratio * 100:.0f}%"

        return False, f"Unknown direction {direction}"

    async def run_cycle(self):
        """Single evaluation step for all configured assets."""
        if self.state != "RUNNING":
            return

        is_circuit_active = await self.evaluate_circuit_breaker()
        if is_circuit_active:
            return

        # Time-Based auto exits (4 hours)
        if hasattr(self, "manage_time_based_exits"):
            await self.manage_time_based_exits()

        # Trailing Stop & Breakeven Management for active bot positions
        await self.manage_open_positions_trailing_stop()

        with SessionLocal() as db:
            configs = {c.symbol: c.active for c in db.query(ConfigModel).all()}

        for symbol in SYMBOL_CONFIGS.keys():
            if not configs.get(symbol, True):
                continue

            in_session, sess_msg = self.is_within_trading_session(symbol)
            if not in_session:
                continue

            is_blackout, blk_msg = await news_filter.is_news_blackout(symbol)
            if is_blackout:
                log_signal_audit(symbol=symbol, status="REJECTED_NEWS_BLACKOUT", reason=blk_msg)
                continue

            # Stagger TradingView API calls to prevent 429 rate-limit throttling
            # (0.5s gap between symbol fetches — minimal impact on a 5s cycle)
            await asyncio.sleep(0.5)

            aligned = tv_analyzer.get_aligned_signal(symbol)
            direction = aligned.get("direction", "NEUTRAL")
            m15_rec = aligned.get("m15_recommendation", "NEUTRAL")
            h1_rec = aligned.get("h1_recommendation", "NEUTRAL")

            if not aligned.get("is_aligned") or direction == "NEUTRAL":
                continue

            # 1. Closed Candle Reversal / Body Check
            valid_wick, wick_reason = self.validate_candle_reversal(symbol, direction)
            if not valid_wick:
                log_signal_audit(
                    symbol=symbol,
                    status="REJECTED_WICK",
                    direction=direction,
                    reason=wick_reason,
                    m15_consensus=m15_rec,
                    h1_consensus=h1_rec,
                )
                continue

            # 2. H4 Macro Trend Alignment Check
            trend_aligned, trend_reason = self.validate_h4_trend(symbol, direction)
            if not trend_aligned:
                log_signal_audit(
                    symbol=symbol,
                    status="REJECTED_MACRO_TREND",
                    direction=direction,
                    reason=trend_reason,
                    m15_consensus=m15_rec,
                    h1_consensus=h1_rec,
                )
                continue

            # Record Executed Signal Audit
            log_signal_audit(
                symbol=symbol,
                status="EXECUTED",
                direction=direction,
                reason=aligned.get("reason", ""),
                m15_consensus=m15_rec,
                h1_consensus=h1_rec,
            )

            # 3. Pre-entry Telegram Signal Alert (all filters passed — engine is entering)
            try:
                from bot.notifications.telegram import send_telegram_alert
                asyncio.create_task(send_telegram_alert(
                    f"📡 <b>SIGNAL CONFIRMED: {symbol} {direction}</b>\n"
                    f"• M15: {aligned.get('m15_recommendation')} | H1: {aligned.get('h1_recommendation')}\n"
                    f"• RSI: {aligned.get('rsi', 'N/A')} | MACD: {'↑ Bull' if aligned.get('macd_bull_cross') else '↓ Bear'}\n"
                    f"• {trend_reason}\n"
                    f"• {wick_reason}\n"
                    f"<i>Executing trade now...</i>"
                ))
            except Exception:
                pass

            await self.execute_trade_signal(symbol, direction, aligned_reason=aligned.get("reason", ""))

    async def start(self):
        """Starts the background bot loop, heartbeat, and daily digest scheduler."""
        self.connect_mt5()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # Launch daily P&L digest at 20:00 EAT
        try:
            from bot.notifications.telegram import schedule_daily_digest
            asyncio.create_task(schedule_daily_digest())
            logger.info("Daily P&L digest scheduler started (fires at 20:00 EAT).")
        except Exception as e:
            logger.warning(f"Could not start daily digest scheduler: {e}")

        async def loop():
            while True:
                try:
                    await self.run_cycle()
                except Exception as e:
                    logger.error(f"Error in bot execution cycle: {e}")
                await asyncio.sleep(5.0)

        self._loop_task = asyncio.create_task(loop())
        logger.info("Bot execution background loop started.")

    async def stop(self):
        """Stops the trading bot process."""
        if self._loop_task:
            self._loop_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.mt5_client:
            self.mt5_client.shutdown()
        self.state = "HALTED"
        logger.info("Bot execution stopped.")


bot_engine = BotEngine()
