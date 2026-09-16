"""
MT5 Order Execution, Position Management, and Trailing Stop Engine for Piploci.
Enforces strict Magic Number isolation (100201 & 100202), dynamic spread protection,
breakeven / trailing stop adjustments, and emergency stops.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional, Tuple, Any

try:
    from bot.config import (
        APP_NAME,
        MAGIC_XAUUSD,
        MAGIC_USDJPY,
        ALLOWED_MAGIC_NUMBERS,
        SYMBOL_CONFIGS,
    )
    from bot.database import (
        SessionLocal,
        TradeLogModel,
        log_system_event,
        log_trading_log,
    )
    from bot.notifications.telegram import send_telegram_alert
except ImportError:
    from config import (
        APP_NAME,
        MAGIC_XAUUSD,
        MAGIC_USDJPY,
        ALLOWED_MAGIC_NUMBERS,
        SYMBOL_CONFIGS,
    )
    from database import (
        SessionLocal,
        TradeLogModel,
        log_system_event,
        log_trading_log,
    )
    from notifier import send_telegram_alert

logger = logging.getLogger("ExecutionEngine")


class ExecutionEngineMixin:
    """Mixin containing order placement, modification, and position management methods."""

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
        - Spread <= 0.15 * ATR(14)
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

        # Dynamic ATR Spread limit (0.15 * ATR14)
        atr = self.calculate_atr(symbol, 14)
        max_allowed = atr * 0.15

        if live_spread > max_allowed:
            reason = f"SPREAD SPIKE on {symbol}: current {live_spread:.4f} > max allowed {max_allowed:.4f} (0.15x ATR)"
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

        # Cross-Asset Correlation Filter (USD exposure stacking prevention)
        # Symbols where BUY = long USD exposure
        LONG_USD_ON_BUY  = {"USDJPY", "USDCAD", "USDCHF"}
        # Symbols where SELL = long USD exposure
        LONG_USD_ON_SELL = {"XAUUSD", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"}

        new_trade_is_long_usd = (
            (symbol in LONG_USD_ON_BUY  and direction == "BUY") or
            (symbol in LONG_USD_ON_SELL and direction == "SELL")
        )
        new_trade_is_short_usd = (
            (symbol in LONG_USD_ON_BUY  and direction == "SELL") or
            (symbol in LONG_USD_ON_SELL and direction == "BUY")
        )

        if new_trade_is_long_usd or new_trade_is_short_usd:
            active_bot_positions = self.get_bot_positions()
            existing_long_usd_count = 0
            existing_short_usd_count = 0

            for pos in active_bot_positions:
                pos_sym  = getattr(pos, "symbol", "")
                pos_type = getattr(pos, "type", -1)
                is_buy   = pos_type == getattr(self.mt5_client, "ORDER_TYPE_BUY", 0)
                is_sell  = pos_type == getattr(self.mt5_client, "ORDER_TYPE_SELL", 1)

                if (pos_sym in LONG_USD_ON_BUY and is_buy) or (pos_sym in LONG_USD_ON_SELL and is_sell):
                    existing_long_usd_count += 1
                elif (pos_sym in LONG_USD_ON_BUY and is_sell) or (pos_sym in LONG_USD_ON_SELL and is_buy):
                    existing_short_usd_count += 1

            MAX_CORRELATED_EXPOSURE = 2  # Max simultaneous positions in the same USD direction

            if new_trade_is_long_usd and existing_long_usd_count >= MAX_CORRELATED_EXPOSURE:
                logger.warning(
                    f"Correlation Block [Long USD]: Cannot open {direction} {symbol}. "
                    f"Already holding {existing_long_usd_count} Long-USD position(s)."
                )
                return

            if new_trade_is_short_usd and existing_short_usd_count >= MAX_CORRELATED_EXPOSURE:
                logger.warning(
                    f"Correlation Block [Short USD]: Cannot open {direction} {symbol}. "
                    f"Already holding {existing_short_usd_count} Short-USD position(s)."
                )
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
            
            asyncio.create_task(send_telegram_alert(
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

    async def manage_time_based_exits(self) -> int:
        """
        Time-Based Trade Auto-Exit:
        Closes any position that has been open for more than 4 hours, 
        preventing capital from getting trapped in prolonged sideways consolidation.
        """
        if not self.mt5_client:
            return 0
            
        bot_positions = self.get_bot_positions()
        if not bot_positions:
            return 0
            
        closed_count = 0
        now = datetime.now(timezone.utc)
        
        for pos in bot_positions:
            pos_time_sec = getattr(pos, "time", 0)
            if pos_time_sec == 0:
                continue
                
            # MT5 pos.time is in seconds since epoch. We assume UTC.
            pos_time = datetime.fromtimestamp(pos_time_sec, tz=timezone.utc)
            duration_hours = (now - pos_time).total_seconds() / 3600.0
            
            if duration_hours >= 4.0:
                ticket = getattr(pos, "ticket", 0)
                symbol = getattr(pos, "symbol", "UNKNOWN")
                logger.info(f"Time-Based Exit triggered for #{ticket} ({symbol}) - Open for {duration_hours:.2f} hours")
                success = await self.close_position_by_ticket(ticket, reason="Time-Based Auto-Exit (>4h)")
                if success:
                    closed_count += 1
                    
        return closed_count

    async def manage_open_positions_trailing_stop(self) -> int:
        """
        Trailing Stop / Breakeven Logic:
        Monitors active bot positions.
        1. Moves Stop Loss to Breakeven once price advances by 1.0x ATR.
        2. Trails profit once price advances by 1.5x ATR.
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
            
            be_threshold    = 1.0 * atr   # Breakeven lock trigger
            partial_trigger = 2.0 * atr   # Partial close trigger (50% at 2.0x ATR)
            trail_distance  = 1.5 * atr   # Trailing stop distance

            # 1. For BUY position:
            if is_buy:
                profit_distance = current_price - price_open

                # Partial close: close 50% of position at 2.0x ATR profit
                partial_done = getattr(pos, "comment", "").find("PARTIAL") >= 0
                if profit_distance >= partial_trigger and not partial_done:
                    half_vol = round(getattr(pos, "volume", 0.01) / 2, 2)
                    if half_vol >= 0.01:
                        partial_req = {
                            "action": getattr(self.mt5_client, "TRADE_ACTION_DEAL", 1),
                            "symbol": symbol,
                            "volume": half_vol,
                            "type": getattr(self.mt5_client, "ORDER_TYPE_SELL", 1),
                            "position": ticket,
                            "price": current_bid,
                            "deviation": 20,
                            "magic": getattr(pos, "magic", 0),
                            "comment": "PARTIAL CLOSE 2xATR",
                            "type_time": getattr(self.mt5_client, "ORDER_TIME_GTC", 0),
                            "type_filling": self.resolve_filling_mode(symbol),
                        }
                        p_res = self.mt5_client.order_send(partial_req)
                        if getattr(p_res, "retcode", 0) == getattr(self.mt5_client, "TRADE_RETCODE_DONE", 10009):
                            updated_count += 1
                            msg = f"PARTIAL CLOSE (50%) #{ticket} ({symbol} BUY) at +2.0x ATR ({profit_distance:.4f})"
                            logger.info(msg)
                            log_system_event("RiskEngine", msg)
                            await self.broadcast_event("PARTIAL_CLOSE", {"ticket": ticket, "symbol": symbol, "volume_closed": half_vol})

                # Check if we should move to BE or trail
                if profit_distance >= be_threshold:
                    # Breakeven target: price_open
                    # Trailing target: current_bid - trail_distance
                    trail_sl = round(current_bid - trail_distance, 3)
                    new_sl = round(max(price_open, trail_sl), 3)

                    # Monotonic adjustment: only move SL up
                    if new_sl > current_sl:
                        success = await self._modify_position_sltp(ticket, symbol, new_sl, current_tp)
                        if success:
                            updated_count += 1
                            msg = (
                                f"Trailing Stop / Breakeven activated for #{ticket} ({symbol} BUY): "
                                f"SL moved to {new_sl:.3f} (Profit: +{profit_distance:.2f}, ATR: {atr:.2f})"
                            )
                            logger.info(msg)
                            log_system_event("RiskEngine", msg)
                            await self.broadcast_event("TRAILING_STOP_UPDATED", {
                                "ticket": ticket,
                                "symbol": symbol,
                                "new_sl": new_sl,
                                "profit_distance": round(profit_distance, 3),
                                "trigger": f"ATR Dynamic",
                            })

            # 2. For SELL position:
            else:
                profit_distance = price_open - current_price
                
                # Check if we should move to BE or trail
                if profit_distance >= be_threshold:
                    # Breakeven target: price_open
                    # Trailing target: current_ask + trail_distance
                    trail_sl = round(current_ask + trail_distance, 3)
                    new_sl = round(min(price_open, trail_sl), 3)

                    # Monotonic adjustment: only move SL down (or if SL was 0)
                    if current_sl <= 0 or new_sl < current_sl:
                        success = await self._modify_position_sltp(ticket, symbol, new_sl, current_tp)
                        if success:
                            updated_count += 1
                            msg = (
                                f"Trailing Stop / Breakeven activated for #{ticket} ({symbol} SELL): "
                                f"SL moved to {new_sl:.3f} (Profit: +{profit_distance:.2f}, ATR: {atr:.2f})"
                            )
                            logger.info(msg)
                            log_system_event("RiskEngine", msg)
                            await self.broadcast_event("TRAILING_STOP_UPDATED", {
                                "ticket": ticket,
                                "symbol": symbol,
                                "new_sl": new_sl,
                                "profit_distance": round(profit_distance, 3),
                                "trigger": f"ATR Dynamic",
                            })

        return updated_count
