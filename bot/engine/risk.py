"""
Risk Management Engine for Piploci.
Handles daily balance reset, circuit breaker evaluation, drawdown protection,
House-Money dynamic compounding scaling tiers, and lot sizing.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Dict, Any, Optional

try:
    from bot.config import (
        BASE_CAPITAL_USD,
        DAILY_DRAWDOWN_LIMIT_USD,
        CIRCUIT_BREAKER_HALT_HOURS,
        TIER1_PROFIT_THRESHOLD,
        TIER2_PROFIT_THRESHOLD,
        DRAWDOWN_OVERRIDE_THRESHOLD_USD,
        SYMBOL_CONFIGS,
    )
    from bot.database import (
        SessionLocal,
        StrategyConfigModel,
        log_system_event,
        log_circuit_breaker_event,
    )
    from bot.notifications.telegram import send_telegram_alert, send_tier_transition_alert
except ImportError:
    from config import (
        BASE_CAPITAL_USD,
        DAILY_DRAWDOWN_LIMIT_USD,
        CIRCUIT_BREAKER_HALT_HOURS,
        TIER1_PROFIT_THRESHOLD,
        TIER2_PROFIT_THRESHOLD,
        DRAWDOWN_OVERRIDE_THRESHOLD_USD,
        SYMBOL_CONFIGS,
    )
    from database import (
        SessionLocal,
        StrategyConfigModel,
        log_system_event,
        log_circuit_breaker_event,
    )
    from notifier import send_telegram_alert, send_tier_transition_alert

logger = logging.getLogger("RiskEngine")


class RiskEngineMixin:
    """Mixin containing all quantitative risk and drawdown evaluation logic."""

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
            
            asyncio.create_task(send_telegram_alert(
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
        """Synchronous drawdown check for circuit breaker."""
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
                loop.create_task(send_telegram_alert(
                    f"🚨 <b>CIRCUIT BREAKER TRIGGERED</b>\n"
                    f"Daily drawdown reached: <b>${loss:.2f}</b>\n"
                    f"Limit: ${DAILY_DRAWDOWN_LIMIT_USD:.2f}\n"
                    f"All bot positions are being closed and trading is halted."
                ))
            except RuntimeError:
                pass

            self.emergency_close_all()
            return True
        return False

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
                loop.create_task(send_tier_transition_alert(
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
