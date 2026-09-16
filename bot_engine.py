"""
Bot Execution Engine and MT5 Trade Controller.
Implements MT5 execution, strict Magic Number isolation, dynamic ATR risk sizing,
daily floating drawdown circuit breaker ($4.50 limit), candle reversal wick validation,
and asynchronous task orchestration.
"""

import asyncio
from datetime import datetime, time, timedelta, timezone
import logging
import math
import random
from typing import Dict, List, Optional, Tuple, Any, Callable

import notifier

import pytz

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    mt5 = None

from config import (
    APP_NAME,
    BASE_CAPITAL_USD,
    MAGIC_XAUUSD,
    MAGIC_USDJPY,
    ALLOWED_MAGIC_NUMBERS,
    DAILY_DRAWDOWN_LIMIT_USD,
    CIRCUIT_BREAKER_HALT_HOURS,
    RISK_PERCENT_PER_TRADE,
    TIER1_PROFIT_THRESHOLD,
    TIER2_PROFIT_THRESHOLD,
    DRAWDOWN_OVERRIDE_THRESHOLD_USD,
    TIMEZONE_EAT,
    SESSION_WINDOWS,
    SYMBOL_CONFIGS,
    MT5_LOGIN,
    MT5_PASSWORD,
    MT5_SERVER,
    MT5_PATH,
    MT5_RECONNECT_INTERVAL_SECONDS,
    MT5_HEARTBEAT_INTERVAL_SECONDS,
    settings,
)
from database import (
    SessionLocal,
    ConfigModel,
    StrategyConfigModel,
    TradeLogModel,
    TradingLogModel,
    CircuitBreakerEventModel,
    SignalAuditModel,
    log_system_event,
    log_trading_log,
    log_circuit_breaker_event,
    log_signal_audit,
)
from news_filter import news_filter, news_shield
from tradingview_ta_module import tv_analyzer, get_aligned_signal

logger = logging.getLogger("BotEngine")


class BotEngine:
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

    def check_daily_balance_reset(self):
        """Resets the daily starting balance baseline at the start of a new calendar day."""
        today = datetime.now(timezone.utc).date()
        if today != self.last_balance_reset_date:
            if self.mt5_client:
                acct = self.mt5_client.account_info()
                if acct:
                    self.starting_daily_balance = getattr(acct, "balance", 1000.0)
                    self.last_balance_reset_date = today
                    logger.info(f"Daily starting balance reset to ${self.starting_daily_balance:.2f} USD")

    async def evaluate_circuit_breaker(self) -> bool:
        """
        Calculates daily floating drawdown:
        Drawdown = Starting Daily Balance - Current Equity
        If Drawdown >= $4.50 USD:
        - Closes all open bot positions for Magic 100201 & 100202
        - Suspends trade execution for 24 hours
        """
        now = datetime.now(timezone.utc)

        # Check if currently under circuit breaker halt
        if self.circuit_breaker_until:
            if now < self.circuit_breaker_until:
                self.state = "CIRCUIT_BREAKER_HALTED"
                return True
            else:
                self.circuit_breaker_until = None
                self.state = "RUNNING"
                log_system_event("RiskEngine", "24-hour circuit breaker expired. Trading resumed.")
                logger.info("Circuit breaker 24h cooldown complete. Resuming trading.")

        self.check_daily_balance_reset()

        if not self.mt5_client:
            return False

        acct = self.mt5_client.account_info()
        if not acct:
            return False

        # Strict isolation: compute floating loss exclusively on bot positions (excludes magic = 0)
        bot_positions = self.get_bot_positions()
        bot_floating_pnl = sum(getattr(p, "profit", 0.0) for p in bot_positions)
        loss = max(0.0, -bot_floating_pnl)

        if loss >= DAILY_DRAWDOWN_LIMIT_USD:
            msg = (
                f"CIRCUIT BREAKER TRIGGERED! Daily floating drawdown reached ${loss:.2f} USD "
                f"(Threshold: ${DAILY_DRAWDOWN_LIMIT_USD:.2f}). Emergency closing all bot positions."
            )
            logger.critical(msg)
            log_system_event("RiskEngine", msg, level="CRITICAL")
            log_circuit_breaker_event(drawdown_amount=round(loss, 2), state="CIRCUIT_BREAKER_HALTED")
            
            asyncio.create_task(notifier.send_telegram_alert(
                f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
                f"Daily drawdown reached: <b>${loss:.2f}</b>\n"
                f"Limit: ${DAILY_DRAWDOWN_LIMIT_USD:.2f}\n"
                f"All bot positions are being closed and trading is halted for {CIRCUIT_BREAKER_HALT_HOURS} hours."
            ))

            # Emergency close bot trades
            await self.close_all_bot_positions(reason=f"Daily Drawdown Circuit Breaker Triggered (${DAILY_DRAWDOWN_LIMIT_USD:.2f} USD)")

            self.circuit_breaker_until = now + timedelta(hours=CIRCUIT_BREAKER_HALT_HOURS)
            self.state = "CIRCUIT_BREAKER_HALTED"

            await self.broadcast_event("CIRCUIT_BREAKER_ALERT", {
                "message": msg,
                "current_drawdown": round(loss, 2),
                "threshold": DAILY_DRAWDOWN_LIMIT_USD,
                "halt_until": self.circuit_breaker_until.isoformat(),
            })
            return True

        return False

    def check_daily_drawdown(self, current_equity: Optional[float] = None) -> bool:
        # Strict isolation: compute floating loss exclusively on bot positions (excludes magic = 0)
        bot_positions = self.get_bot_positions()
        bot_floating_pnl = sum(getattr(p, "profit", 0.0) for p in bot_positions)
        loss = max(0.0, -bot_floating_pnl)
        if loss >= DAILY_DRAWDOWN_LIMIT_USD:
            self.is_halted = True
            self.halt_expiration = datetime.now(timezone.utc) + timedelta(hours=CIRCUIT_BREAKER_HALT_HOURS)
            self.state = "CIRCUIT_BREAKER_HALTED"
            logger.critical(f"Circuit Breaker Triggered! Loss ${loss:.2f} >= ${DAILY_DRAWDOWN_LIMIT_USD:.2f}")
            log_circuit_breaker_event(drawdown_amount=round(loss, 2), state="CIRCUIT_BREAKER_HALTED")
            
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(notifier.send_telegram_alert(
                    f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
                    f"Daily drawdown reached: <b>${loss:.2f}</b>\n"
                    f"Limit: ${DAILY_DRAWDOWN_LIMIT_USD:.2f}\n"
                    f"All bot positions are being closed and trading is halted."
                ))
            except RuntimeError:
                pass # No running event loop

            self.emergency_close_all()
            return True
        return False

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
        """Calculates Average True Range on M15 timeframe."""
        if symbol == "XAUUSD":
            return 3.50
        return 0.40

    def evaluate_compounding_tier(
        self,
        symbol: Optional[str] = None,
        balance: Optional[float] = None,
        equity: Optional[float] = None,
        floating_drawdown: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculates dynamic 'House-Money' compounding scaling tier and checks drawdown safety override:
        - Tier 0 (Base Capital): When realized net profit < +15%, 1.0% risk, 1.0x lot multiplier.
        - Tier 1 (Accelerated Growth): When realized net profit reaches +15% to +30%, 1.5% risk, 1.25x lot multiplier.
        - Tier 2 (Aggressive Compounding): When realized net profit exceeds +30%, 2.0% risk, 1.5x lot multiplier.
        - Drawdown Safety Override: If floating drawdown touches 50% of daily allowance ($2.25),
          instantly drop back to Tier 0 (1.0% base risk, 1.0x multiplier) regardless of total monthly gains.
        """
        # Resolve balance and equity
        if balance is None:
            acct = self.mt5_client.account_info() if self.mt5_client else None
            balance = getattr(acct, "balance", self.base_capital) if acct else self.base_capital

        if equity is None:
            acct = self.mt5_client.account_info() if self.mt5_client else None
            equity = getattr(acct, "equity", balance) if acct else balance

        # Resolve floating drawdown
        if floating_drawdown is None:
            if self.mt5_client:
                acct = self.mt5_client.account_info()
                drawdown_balance = max(0.0, self.starting_daily_balance - getattr(acct, "equity", balance)) if acct else 0.0
                bot_positions = self.get_bot_positions()
                bot_floating_pnl = sum(getattr(p, "profit", 0.0) for p in bot_positions)
                drawdown_positions = max(0.0, -bot_floating_pnl)
                floating_drawdown = max(drawdown_balance, drawdown_positions)
            else:
                floating_drawdown = 0.0

        tier1_thresh = TIER1_PROFIT_THRESHOLD
        tier2_thresh = TIER2_PROFIT_THRESHOLD
        scaling_active = True

        if symbol:
            try:
                with SessionLocal() as db:
                    cfg_db = db.query(StrategyConfigModel).filter_by(symbol=symbol.upper()).first()
                    if cfg_db:
                        scaling_active = cfg_db.scaling_tier_active
                        tier1_thresh = cfg_db.tier1_threshold if cfg_db.tier1_threshold is not None else TIER1_PROFIT_THRESHOLD
                        tier2_thresh = cfg_db.tier2_threshold if cfg_db.tier2_threshold is not None else TIER2_PROFIT_THRESHOLD
            except Exception:
                cfg = SYMBOL_CONFIGS.get(symbol, {})
                scaling_active = cfg.get("scaling_tier_active", True)
                tier1_thresh = cfg.get("tier1_threshold", TIER1_PROFIT_THRESHOLD)
                tier2_thresh = cfg.get("tier2_threshold", TIER2_PROFIT_THRESHOLD)

        # Realized net profit & safety cushion relative to base capital ($155)
        base_cap = self.base_capital if self.base_capital > 0 else 155.0
        profit_buffer = max(0.0, balance - base_cap)
        safety_cushion_usd = round(profit_buffer, 2)
        net_profit_pct = ((balance - base_cap) / base_cap) * 100.0

        # Drawdown safety override check ($2.25)
        drawdown_override = floating_drawdown >= DRAWDOWN_OVERRIDE_THRESHOLD_USD

        if not scaling_active:
            target_tier = 0
            tier_name = "TIER 0 - BASE"
            risk_pct = 1.0
            lot_multiplier = 1.0
            reason = "Dynamic scaling inactive for symbol."
        elif drawdown_override:
            target_tier = 0
            tier_name = "TIER 0 - BASE"
            risk_pct = 1.0
            lot_multiplier = 1.0
            reason = f"Drawdown Safety Override: Floating loss ${floating_drawdown:.2f} touched 50% daily limit (${DRAWDOWN_OVERRIDE_THRESHOLD_USD:.2f}). Fallback to Tier 0."
        else:
            if net_profit_pct >= tier2_thresh:
                target_tier = 2
                tier_name = "TIER 2 - AGGRESSIVE"
                risk_pct = 2.0
                lot_multiplier = 1.50
                reason = f"Aggressive Compounding: Realized profit +{net_profit_pct:.1f}% >= +{tier2_thresh:.1f}%."
            elif net_profit_pct >= tier1_thresh:
                target_tier = 1
                tier_name = "TIER 1 - ACCELERATED"
                risk_pct = 1.5
                lot_multiplier = 1.25
                reason = f"Accelerated Growth: Realized profit +{net_profit_pct:.1f}% in [{tier1_thresh:.1f}%, {tier2_thresh:.1f}%)."
            else:
                target_tier = 0
                tier_name = "TIER 0 - BASE"
                risk_pct = 1.0
                lot_multiplier = 1.00
                reason = f"Base Capital: Realized profit {net_profit_pct:+.1f}% < +{tier1_thresh:.1f}%."

        # Milestone progress calculation
        if target_tier == 0:
            next_milestone_pct = tier1_thresh
            progress = max(0.0, min(100.0, (net_profit_pct / tier1_thresh) * 100.0)) if tier1_thresh > 0 else 0.0
            distance_pct = max(0.0, tier1_thresh - max(0.0, net_profit_pct))
        elif target_tier == 1:
            next_milestone_pct = tier2_thresh
            span = tier2_thresh - tier1_thresh
            curr_in_tier = net_profit_pct - tier1_thresh
            progress = max(0.0, min(100.0, (curr_in_tier / span) * 100.0)) if span > 0 else 0.0
            distance_pct = max(0.0, tier2_thresh - net_profit_pct)
        else:
            next_milestone_pct = tier2_thresh
            progress = 100.0
            distance_pct = 0.0

        # State transition handling & Telegram / WebSocket alert
        old_tier = self.current_tier
        if target_tier != self.current_tier:
            self.current_tier = target_tier
            self.last_tier_transition = datetime.now(timezone.utc)
            log_msg = f"Compounding Tier Transition: {old_tier} -> {target_tier} ({tier_name}). Risk: {risk_pct}%, Lot Multiplier: {lot_multiplier}x. Reason: {reason}"
            logger.info(log_msg)
            log_system_event("RiskEngine", log_msg)

            # Non-blocking Telegram alert
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(notifier.send_tier_transition_alert(
                    old_tier=old_tier,
                    new_tier=target_tier,
                    risk_percent=risk_pct,
                    lot_multiplier=lot_multiplier,
                    reason=reason,
                    chat_id="884357013"
                ))
                loop.create_task(self.broadcast_event("TIER_TRANSITION", {
                    "old_tier": old_tier,
                    "new_tier": target_tier,
                    "tier_name": tier_name,
                    "risk_percent": risk_pct,
                    "lot_multiplier": lot_multiplier,
                    "reason": reason,
                    "net_profit_pct": round(net_profit_pct, 2),
                    "safety_cushion_usd": safety_cushion_usd,
                }))
            except RuntimeError:
                pass

        return {
            "tier": target_tier,
            "tier_name": tier_name,
            "net_profit_pct": round(net_profit_pct, 2),
            "safety_cushion_usd": safety_cushion_usd,
            "base_capital_usd": round(base_cap, 2),
            "effective_risk_pct": risk_pct,
            "lot_multiplier": lot_multiplier,
            "drawdown_override_active": drawdown_override,
            "floating_drawdown": round(floating_drawdown, 2),
            "drawdown_override_threshold": DRAWDOWN_OVERRIDE_THRESHOLD_USD,
            "next_milestone_pct": round(next_milestone_pct, 2),
            "distance_to_milestone_pct": round(distance_pct, 2),
            "progress_to_next_milestone": round(progress, 1),
            "reason": reason,
        }

    def calculate_lot_size(
        self,
        symbol_or_balance: Any,
        stop_loss_distance: float = 0.0,
        tick_value: float = 1.0,
        floating_drawdown: Optional[float] = None,
    ) -> float:
        """
        Dynamically computes lot size with Dynamic Tiered Scaling and Drawdown Protection:
        Lot Size = ((Account Balance * Risk %) / (Stop Loss Distance * Tick Value)) * Lot Multiplier
        Supports both signatures:
        - calculate_lot_size(symbol, stop_loss_distance)
        - calculate_lot_size(balance, sl_distance, tick_value)
        """
        if isinstance(symbol_or_balance, (int, float)):
            balance = float(symbol_or_balance)
            sl_distance = stop_loss_distance
            symbol = "XAUUSD"
            acct = None
        else:
            symbol = str(symbol_or_balance)
            sl_distance = stop_loss_distance
            acct = self.mt5_client.account_info() if self.mt5_client else None
            balance = getattr(acct, "balance", 1000.0) if acct else 1000.0

        if sl_distance <= 0:
            return 0.01

        # Calculate floating drawdown if not explicitly passed
        if floating_drawdown is None:
            if acct:
                floating_drawdown = max(0.0, self.starting_daily_balance - getattr(acct, "equity", balance))
            else:
                floating_drawdown = 0.0

        # Evaluate dynamic compounding tier
        tier_data = self.evaluate_compounding_tier(
            symbol=symbol,
            balance=balance,
            floating_drawdown=floating_drawdown
        )
        risk_pct = tier_data["effective_risk_pct"]
        lot_multiplier = tier_data["lot_multiplier"]

        risk_capital = balance * (risk_pct / 100.0)

        # Scale down 50% if floating drawdown touches 50% daily limit ($2.25)
        if floating_drawdown >= DRAWDOWN_OVERRIDE_THRESHOLD_USD:
            risk_capital *= 0.5
            logger.info(f"Risk scaled down 50% for {symbol} due to floating drawdown (${floating_drawdown:.2f})")

        tick_size = 0.01
        sym_info = self.mt5_client.symbol_info(symbol) if self.mt5_client else None
        if sym_info:
            tick_size = getattr(sym_info, "trade_tick_size", 0.01) or 0.01
            tick_value = getattr(sym_info, "trade_tick_value", 1.0) or 1.0
            vol_min = getattr(sym_info, "volume_min", 0.01) or 0.01
            vol_max = getattr(sym_info, "volume_max", 10.0) or 10.0
            vol_step = getattr(sym_info, "volume_step", 0.01) or 0.01
        else:
            vol_min, vol_max, vol_step = 0.01, 10.0, 0.01

        ticks_at_risk = sl_distance / tick_size
        if ticks_at_risk <= 0:
            return vol_min

        per_tick_risk = ticks_at_risk * tick_value
        if per_tick_risk <= 0:
            return vol_min

        raw_lot = (risk_capital / per_tick_risk) * lot_multiplier
        steps = math.floor(raw_lot / vol_step)
        norm_lot = steps * vol_step
        return round(max(vol_min, min(norm_lot, vol_max)), 2)

    def validate_candle_reversal(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """
        Verifies rejection wick proportion on the last completed M15 candle:
        - XAUUSD: Reversal wick >= 55% of candle range
        - USDJPY: Reversal wick >= 45% of candle range
        """
        cfg = SYMBOL_CONFIGS.get(symbol, {})
        min_ratio = cfg.get("min_reversal_wick_ratio", 0.50)

        if not self.mt5_client:
            return False, "MT5 terminal not connected"

        tf = getattr(self.mt5_client, "TIMEFRAME_M15", 15)
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
            lower_wick = min(c_open, c_close) - c_low
            ratio = lower_wick / total_range
            if ratio >= min_ratio:
                return True, f"Bullish Wick Ratio {ratio * 100:.1f}% >= {min_ratio * 100:.0f}%"
            return False, f"Bullish Wick {ratio * 100:.1f}% < required {min_ratio * 100:.0f}%"

        elif direction == "SELL":
            upper_wick = c_high - max(c_open, c_close)
            ratio = upper_wick / total_range
            if ratio >= min_ratio:
                return True, f"Bearish Wick Ratio {ratio * 100:.1f}% >= {min_ratio * 100:.0f}%"
            return False, f"Bearish Wick {ratio * 100:.1f}% < required {min_ratio * 100:.0f}%"

        return False, f"Unknown direction {direction}"

    def resolve_filling_mode(self, symbol: str) -> int:
        return 1

    def get_bot_positions(self, symbol: Optional[str] = None) -> List[Any]:
        """
        Queries open positions and STRICTLY filters by bot Magic Numbers.
        Manual positions (magic = 0) and third-party bots are completely ignored.
        """
        if not self.mt5_client:
            return []

        all_pos = self.mt5_client.positions_get(symbol=symbol) if symbol else self.mt5_client.positions_get()
        if not all_pos:
            return []

        return [p for p in all_pos if getattr(p, "magic", 0) in ALLOWED_MAGIC_NUMBERS]

    async def close_position_by_ticket(self, ticket: int, reason: str = "") -> bool:
        """
        Closes an open position strictly verifying it matches the bot's magic numbers.
        Refuses to close discretionary manual orders (magic = 0).
        """
        if not self.mt5_client:
            self.connect_mt5()

        positions = self.mt5_client.positions_get() or []
        target = next((p for p in positions if getattr(p, "ticket", 0) == ticket), None)

        if not target:
            logger.warning(f"Position #{ticket} not found.")
            return False

        # STRICT MAGIC ISOLATION ENFORCEMENT
        target_magic = getattr(target, "magic", 0)
        if target_magic not in ALLOWED_MAGIC_NUMBERS:
            logger.error(f"REFUSED: Position #{ticket} has magic {target_magic}. Not a bot order.")
            return False

        sym = getattr(target, "symbol", "")
        tick = self.mt5_client.symbol_info_tick(sym)
        is_buy = getattr(target, "type", 0) == 0
        price = getattr(tick, "bid", 0.0) if is_buy else getattr(tick, "ask", 0.0)
        order_type = getattr(self.mt5_client, "ORDER_TYPE_SELL", 1) if is_buy else getattr(self.mt5_client, "ORDER_TYPE_BUY", 0)

        req = {
            "action": getattr(self.mt5_client, "TRADE_ACTION_DEAL", 1),
            "symbol": sym,
            "volume": getattr(target, "volume", 0.01),
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": target_magic,
            "comment": f"Close: {reason[:20]}",
            "type_time": getattr(self.mt5_client, "ORDER_TIME_GTC", 0),
            "type_filling": self.resolve_filling_mode(sym),
        }

        res = self.mt5_client.order_send(req)
        retcode = getattr(res, "retcode", 0)
        done_code = getattr(self.mt5_client, "TRADE_RETCODE_DONE", 10009)

        if retcode == done_code:
            logger.info(f"Closed bot position #{ticket} ({sym}) successfully. Reason: {reason}")
            log_system_event("BotEngine", f"Closed position #{ticket} ({sym}) at {price}. Reason: {reason}")

            # Update DB trade log
            try:
                with SessionLocal() as db:
                    t_log = db.query(TradeLogModel).filter_by(ticket=ticket).first()
                    if t_log:
                        t_log.status = "CLOSED"
                        t_log.close_price = price
                        t_log.pnl = getattr(target, "profit", 0.0)
                        t_log.notes = reason
                        db.commit()
            except Exception as e:
                logger.error(f"Failed to update trade log in DB: {e}")

            await self.broadcast_event("TRADE_CLOSED", {
                "ticket": ticket,
                "symbol": sym,
                "close_price": price,
                "profit": getattr(target, "profit", 0.0),
                "reason": reason,
            })
            return True

        logger.error(f"Failed to close position #{ticket}: {getattr(res, 'comment', 'Unknown error')}")
        return False

    async def close_all_bot_positions(self, reason: str = "") -> int:
        """Closes all active trades belonging strictly to Magic Numbers 100201 and 100202."""
        bot_positions = self.get_bot_positions()
        closed_count = 0
        for pos in bot_positions:
            t = getattr(pos, "ticket", 0)
            if t:
                success = await self.close_position_by_ticket(t, reason=reason)
                if success:
                    closed_count += 1
        return closed_count

    def emergency_close_all(self):
        """Synchronous isolation closer for circuit breaker."""
        logger.warning("Closing all trades isolated to Magic Numbers [100201, 100202]")
        with SessionLocal() as db:
            open_trades = db.query(TradeLogModel).filter(
                TradeLogModel.magic.in_([MAGIC_XAUUSD, MAGIC_USDJPY]),
                TradeLogModel.status == "OPEN"
            ).all()
            for trade in open_trades:
                trade.status = "CLOSED"
            db.commit()

    async def trigger_emergency_stop(self) -> Dict[str, Any]:
        """Emergency Kill Switch: closes all bot trades and halts trading."""
        self.state = "HALTED"
        closed_count = await self.close_all_bot_positions(reason="EMERGENCY KILL SWITCH TRIGGERED")
        msg = f"EMERGENCY KILL SWITCH ACTIVATED! Closed {closed_count} active bot positions. State set to HALTED."
        logger.warning(msg)
        log_system_event("BotEngine", msg, level="CRITICAL")

        await self.broadcast_event("EMERGENCY_STOP", {
            "message": msg,
            "closed_trades": closed_count,
        })
        return {
            "status": "HALTED",
            "closed_positions": closed_count,
            "message": msg,
        }

    def validate_spread_protection(self, symbol: str) -> Tuple[bool, float, float, str]:
        """
        Dynamic Spread Protection:
        Verifies that current bid-ask spread does not exceed maximum allowable thresholds:
        - Gold (XAUUSD): Reject execution if current spread > $0.35 (35 points).
        - USDJPY (USDJPY): Reject execution if current spread > 2.0 pips / 0.020 (20 points).
        Returns: (is_allowed, current_spread, max_spread, reason)
        """
        if not self.mt5_client:
            return False, 0.0, 0.0, "MT5 client unavailable"

        tick = self.mt5_client.symbol_info_tick(symbol)
        if not tick or getattr(tick, "ask", None) is None or getattr(tick, "bid", None) is None:
            return False, 0.0, 0.0, f"Live tick data unavailable for {symbol}"

        ask = float(tick.ask)
        bid = float(tick.bid)
        live_spread = round(ask - bid, 4)

        cfg = SYMBOL_CONFIGS.get(symbol, {})
        default_max_price = 0.35 if "XAU" in symbol else 0.020
        max_allowed = cfg.get("max_spread_price", default_max_price)

        if live_spread > max_allowed:
            reason = f"SPREAD SPIKE on {symbol}: current {live_spread:.4f} > max allowed {max_allowed:.4f}"
            logger.warning(reason)
            log_system_event("RiskEngine", reason, level="WARNING")
            log_trading_log(symbol=symbol, message=reason, level="WARNING")
            return False, live_spread, max_allowed, reason

        return True, live_spread, max_allowed, f"Spread OK ({live_spread:.4f} <= {max_allowed:.4f})"

    async def execute_trade_signal(self, symbol: str, direction: str, aligned_reason: str = ""):
        """Places a new market order with dynamic ATR lot sizing, SL, and TP."""
        # Avoid duplicate open positions for same symbol
        if len(self.get_bot_positions(symbol=symbol)) > 0:
            return

        # Cross-Asset Correlation Filter (Long USD limit)
        is_long_usd_signal = (symbol == "XAUUSD" and direction == "SELL") or (symbol == "USDJPY" and direction == "BUY")
        if is_long_usd_signal:
            active_bot_positions = self.get_bot_positions()
            for pos in active_bot_positions:
                pos_sym = getattr(pos, "symbol", "")
                pos_type = getattr(pos, "type", -1)
                is_pos_sell = pos_type == getattr(self.mt5_client, "ORDER_TYPE_SELL", 1)
                is_pos_buy = pos_type == getattr(self.mt5_client, "ORDER_TYPE_BUY", 0)
                
                if (pos_sym == "XAUUSD" and is_pos_sell) or (pos_sym == "USDJPY" and is_pos_buy):
                    logger.warning(f"Cross-Asset Correlation Block: Cannot execute {direction} {symbol}, already holding Long USD exposure.")
                    return

        # Dynamic Spread Protection Check
        spread_ok, curr_spread, max_spread, spread_reason = self.validate_spread_protection(symbol)
        if not spread_ok:
            logger.warning(f"Skipping trade execution on {symbol}: {spread_reason}")
            await self.broadcast_event("SPREAD_REJECTED", {
                "symbol": symbol,
                "current_spread": curr_spread,
                "max_allowed": max_spread,
                "message": spread_reason,
                "alert": f"Trade blocked: Excessive spread on {symbol} ({curr_spread:.4f} > {max_spread:.4f})",
            })
            return

        cfg = SYMBOL_CONFIGS.get(symbol, {})
        magic = cfg.get("magic_number", MAGIC_XAUUSD)
        tick = self.mt5_client.symbol_info_tick(symbol)

        atr = self.calculate_atr(symbol, cfg.get("atr_period", 14))
        sl_mult = cfg.get("atr_sl_multiplier", 1.5)
        tp_mult = cfg.get("atr_tp_multiplier", 3.5)

        sl_distance = atr * sl_mult
        tp_distance = atr * tp_mult

        if direction == "BUY":
            price = getattr(tick, "ask", 0.0)
            sl = round(price - sl_distance, 3)
            tp = round(price + tp_distance, 3)
            lot = self.calculate_lot_size(symbol, stop_loss_distance=sl_distance)
            order_type = getattr(self.mt5_client, "ORDER_TYPE_BUY", 0)
        else:
            price = getattr(tick, "bid", 0.0)
            sl = round(price + sl_distance, 3)
            tp = round(price - tp_distance, 3)
            lot = self.calculate_lot_size(symbol, stop_loss_distance=sl_distance)
            order_type = getattr(self.mt5_client, "ORDER_TYPE_SELL", 1)

        req = {
            "action": getattr(self.mt5_client, "TRADE_ACTION_DEAL", 1),
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": magic,
            "comment": f"{APP_NAME} ATR:{atr:.2f}",
            "type_time": getattr(self.mt5_client, "ORDER_TIME_GTC", 0),
            "type_filling": self.resolve_filling_mode(symbol),
        }

        res = self.mt5_client.order_send(req)
        retcode = getattr(res, "retcode", 0)
        done_code = getattr(self.mt5_client, "TRADE_RETCODE_DONE", 10009)

        if retcode == done_code:
            order_ticket = getattr(res, "order", 0)
            actual_fill = getattr(res, "price", price)
            
            slippage = (actual_fill - price) if direction == "BUY" else (price - actual_fill)
            if slippage > 1.0:
                logger.warning(f"HIGH SLIPPAGE DETECTED: {symbol} requested {price}, filled {actual_fill} (Slippage: {slippage:.3f} pts)")
                log_trading_log(symbol=symbol, message=f"High slippage: {slippage:.3f} pts", level="WARNING")

            logger.info(f"NEW TRADE FILLED: {symbol} {direction} {lot} Lots @ {actual_fill:.3f} (Req: {price:.3f}) | SL: {sl:.3f} | TP: {tp:.3f} | Magic: {magic}")
            log_system_event("BotEngine", f"Opened {symbol} {direction} {lot}L @ {actual_fill}. Ticket #{order_ticket}")
            
            asyncio.create_task(notifier.send_telegram_alert(
                f"🚀 <b>NEW TRADE FILLED</b>\n"
                f"Symbol: <b>{symbol}</b>\n"
                f"Action: {direction}\n"
                f"Lots: {lot}\n"
                f"Price: {actual_fill:.3f}\n"
                f"SL: {sl:.3f} | TP: {tp:.3f}\n"
                f"Slippage: {slippage:.3f} pts"
            ))

            try:
                with SessionLocal() as db:
                    trade = TradeLogModel(
                        ticket=order_ticket,
                        symbol=symbol,
                        action=direction,
                        volume=lot,
                        open_price=actual_fill,
                        sl=sl,
                        tp=tp,
                        pnl=0.0,
                        magic=magic,
                        timestamp=datetime.now(timezone.utc),
                        status="OPEN",
                        notes=aligned_reason,
                    )
                    db.add(trade)
                    db.commit()
            except Exception as e:
                logger.error(f"Failed to record trade to database: {e}")

            await self.broadcast_event("ORDER_FILLED", {
                "ticket": order_ticket,
                "symbol": symbol,
                "direction": direction,
                "volume": lot,
                "open_price": price,
                "sl": sl,
                "tp": tp,
                "magic": magic,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        else:
            logger.error(f"Failed to place {symbol} {direction} order: {getattr(res, 'comment', 'Order send error')}")

    async def _modify_position_sltp(self, ticket: int, symbol: str, new_sl: float, current_tp: float) -> bool:
        """Sends TRADE_ACTION_SLTP to MT5 to update Stop Loss on an open position."""
        if not self.mt5_client:
            return False

        trade_action = getattr(self.mt5_client, "TRADE_ACTION_SLTP", 6)
        req = {
            "action": trade_action,
            "position": ticket,
            "symbol": symbol,
            "sl": new_sl,
            "tp": current_tp,
        }
        res = self.mt5_client.order_send(req)
        retcode = getattr(res, "retcode", 0)
        done_code = getattr(self.mt5_client, "TRADE_RETCODE_DONE", 10009)
        if retcode == done_code:
            try:
                with SessionLocal() as db:
                    t_log = db.query(TradeLogModel).filter_by(ticket=ticket).first()
                    if t_log:
                        t_log.sl = new_sl
                        db.commit()
            except Exception as e:
                logger.error(f"Error updating DB SL for #{ticket}: {e}")
            return True
        else:
            logger.warning(f"Failed to modify SL on #{ticket}: {getattr(res, 'comment', 'retcode ' + str(retcode))}")
            return False

    async def manage_open_positions_trailing_stop(self) -> int:
        """
        Trailing Stop / Breakeven Logic:
        Monitors active bot positions and automatically moves Stop Loss to Breakeven
        (and trails profit) once price advances by 1.5x ATR in profit.
        Locks in yield and protects winning trades against sudden reversals.
        Returns: number of positions updated.
        """
        if not self.mt5_client:
            return 0

        bot_positions = self.get_bot_positions()
        if not bot_positions:
            return 0

        updated_count = 0
        for pos in bot_positions:
            ticket = getattr(pos, "ticket", 0)
            symbol = getattr(pos, "symbol", "")
            price_open = getattr(pos, "price_open", 0.0)
            current_sl = getattr(pos, "sl", 0.0)
            current_tp = getattr(pos, "tp", 0.0)
            is_buy = getattr(pos, "type", 0) == 0

            tick = self.mt5_client.symbol_info_tick(symbol)
            if not tick:
                continue

            current_bid = getattr(tick, "bid", 0.0)
            current_ask = getattr(tick, "ask", 0.0)
            current_price = current_bid if is_buy else current_ask

            cfg = SYMBOL_CONFIGS.get(symbol, {})
            atr = self.calculate_atr(symbol, cfg.get("atr_period", 14))
            trailing_mult = cfg.get("trailing_atr_multiplier", 1.5)
            be_threshold = trailing_mult * atr  # 1.5x ATR profit trigger

            # 1. For BUY position:
            if is_buy:
                profit_distance = current_price - price_open
                if profit_distance >= be_threshold:
                    # Breakeven target: price_open; Trailing target: current_bid - be_threshold
                    trail_sl = round(current_bid - be_threshold, 3)
                    new_sl = round(max(price_open, trail_sl), 3)

                    # Monotonic adjustment: only move SL up
                    if new_sl > current_sl:
                        success = await self._modify_position_sltp(ticket, symbol, new_sl, current_tp)
                        if success:
                            updated_count += 1
                            msg = (
                                f"Trailing Stop / Breakeven activated for #{ticket} ({symbol} BUY): "
                                f"SL moved to {new_sl:.3f} (Profit >= 1.5x ATR: +{profit_distance:.2f} >= {be_threshold:.2f})"
                            )
                            logger.info(msg)
                            log_system_event("RiskEngine", msg)
                            await self.broadcast_event("TRAILING_STOP_UPDATED", {
                                "ticket": ticket,
                                "symbol": symbol,
                                "new_sl": new_sl,
                                "profit_distance": round(profit_distance, 3),
                                "trigger": f"{trailing_mult}x ATR",
                            })

            # 2. For SELL position:
            else:
                profit_distance = price_open - current_price
                if profit_distance >= be_threshold:
                    # Breakeven target: price_open; Trailing target: current_ask + be_threshold
                    trail_sl = round(current_ask + be_threshold, 3)
                    new_sl = round(min(price_open, trail_sl), 3)

                    # Monotonic adjustment: only move SL down (or if SL was 0)
                    if current_sl <= 0 or new_sl < current_sl:
                        success = await self._modify_position_sltp(ticket, symbol, new_sl, current_tp)
                        if success:
                            updated_count += 1
                            msg = (
                                f"Trailing Stop / Breakeven activated for #{ticket} ({symbol} SELL): "
                                f"SL moved to {new_sl:.3f} (Profit >= 1.5x ATR: +{profit_distance:.2f} >= {be_threshold:.2f})"
                            )
                            logger.info(msg)
                            log_system_event("RiskEngine", msg)
                            await self.broadcast_event("TRAILING_STOP_UPDATED", {
                                "ticket": ticket,
                                "symbol": symbol,
                                "new_sl": new_sl,
                                "profit_distance": round(profit_distance, 3),
                                "trigger": f"{trailing_mult}x ATR",
                            })

        return updated_count

    async def run_cycle(self):
        """Single evaluation step for all configured assets."""
        if self.state != "RUNNING":
            return

        is_circuit_active = await self.evaluate_circuit_breaker()
        if is_circuit_active:
            return

        # Trailing Stop & Breakeven Management for active bot positions
        await self.manage_open_positions_trailing_stop()

        with SessionLocal() as db:
            configs = {c.symbol: c.active for c in db.query(ConfigModel).all()}

        for symbol in ["XAUUSD", "USDJPY"]:
            if not configs.get(symbol, True):
                continue

            in_session, sess_msg = self.is_within_trading_session(symbol)
            if not in_session:
                continue

            is_blackout, blk_msg = await news_filter.is_news_blackout(symbol)
            if is_blackout:
                log_signal_audit(
                    symbol=symbol,
                    status="REJECTED_NEWS_BLACKOUT",
                    reason=blk_msg,
                )
                continue

            aligned = tv_analyzer.get_aligned_signal(symbol)
            direction = aligned.get("direction", "NEUTRAL")
            m15_rec = aligned.get("m15_recommendation", "NEUTRAL")
            h1_rec = aligned.get("h1_recommendation", "NEUTRAL")

            if not aligned.get("is_aligned") or direction == "NEUTRAL":
                continue

            valid_wick, wick_msg = self.validate_candle_reversal(symbol, direction)
            if not valid_wick:
                log_signal_audit(
                    symbol=symbol,
                    status="REJECTED_WICK",
                    direction=direction,
                    reason=wick_msg,
                    m15_consensus=m15_rec,
                    h1_consensus=h1_rec,
                )
                continue

            # Spread Guard Validation
            spread = 0.0
            if self.mt5_client:
                sym_info = self.mt5_client.symbol_info(symbol)
                spread = getattr(sym_info, "spread", 0.0) if sym_info else 0.0

            cfg = SYMBOL_CONFIGS.get(symbol, {})
            max_spread = cfg.get("max_spread_points", 35.0)
            if spread > max_spread and spread > 0:
                log_signal_audit(
                    symbol=symbol,
                    status="REJECTED_SPREAD",
                    direction=direction,
                    reason=f"Spread {spread:.1f} pts exceeds limit {max_spread:.1f} pts",
                    m15_consensus=m15_rec,
                    h1_consensus=h1_rec,
                    spread=spread,
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
                spread=spread,
            )
            await self.execute_trade_signal(symbol, direction, aligned_reason=aligned.get("reason", ""))

    async def start(self):
        """Starts the background bot loop and heartbeat."""
        self.connect_mt5()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

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
