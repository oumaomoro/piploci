"""
Notifier module for automated Telegram alerts.
Pushes real-time trade fills, circuit breaker triggers, tier transitions, and daily profit summaries.
"""

import os
import httpx
import logging
import asyncio
from typing import Optional

logger = logging.getLogger("Notifier")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


async def send_telegram_alert(message: str, chat_id: Optional[str] = None) -> None:
    """
    Sends a formatted HTML message to a designated Telegram chat.
    Fails silently with a warning if tokens are not configured.
    """
    target_chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target_chat_id:
        logger.debug(f"Telegram alert skipped (Not configured): {message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    # Basic HTML escaping for safety
    html_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Allow some basic html tags by reversing the escape for <b> </b> <i> </i> <code> </code>
    html_msg = html_msg.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    html_msg = html_msg.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    html_msg = html_msg.replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
    
    payload["text"] = html_msg

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code != 200:
                logger.warning(f"Telegram alert failed: {res.text}")
    except Exception as e:
        logger.warning(f"Telegram alert exception: {e}")


async def send_tier_transition_alert(
    old_tier: int,
    new_tier: int,
    risk_percent: float,
    lot_multiplier: float,
    reason: str,
    chat_id: str = "884357013"
) -> None:
    """
    Sends immediate Telegram notification to Chat ID 884357013 whenever the bot
    transitions between Compounding Tiers.
    """
    tier_names = {
        0: "Tier 0 (Base Capital)",
        1: "Tier 1 (Accelerated Growth)",
        2: "Tier 2 (Aggressive Compounding)",
    }
    old_name = tier_names.get(old_tier, f"Tier {old_tier}")
    new_name = tier_names.get(new_tier, f"Tier {new_tier}")

    if new_tier > old_tier:
        header = f"🚀 <b>SCALED TO {new_name.upper()}</b>"
    else:
        header = f"⚠️ <b>SAFETY OVERRIDE / FALLBACK TO {new_name.upper()}</b>"

    msg = (
        f"{header}\n"
        f"• <b>Previous Tier:</b> {old_name}\n"
        f"• <b>Active Tier:</b> {new_name}\n"
        f"• <b>Per-Trade Risk:</b> {risk_percent:.1f}%\n"
        f"• <b>Lot Multiplier:</b> {lot_multiplier:.2f}x\n"
        f"• <b>Trigger / Context:</b> {reason}\n\n"
        f"<i>Piploci Dynamic Lot-Scaling & Compounding Engine</i>"
    )
    await send_telegram_alert(msg, chat_id=chat_id)


def format_daily_digest(
    total_trades: int,
    net_realized_pnl: float,
    win_rate: float,
    max_drawdown_exposure: float,
    avg_slippage_pts: float,
    date_str: str = ""
) -> str:
    """
    Builds a clean, institutional-grade end-of-day Telegram digest message.
    """
    pnl_sign = "+" if net_realized_pnl >= 0 else ""
    return (
        f"<b>📊 Piploci Trading Desk — End of Day Digest</b>\n"
        f"<i>Date: {date_str or 'Today'}</i>\n\n"
        f"• <b>Total Trades:</b> {total_trades}\n"
        f"• <b>Net Realized P&L:</b> {pnl_sign}${net_realized_pnl:,.2f}\n"
        f"• <b>Win Rate:</b> {win_rate:.1f}%\n"
        f"• <b>Max Drawdown Exposure:</b> ${max_drawdown_exposure:,.2f}\n"
        f"• <b>Average Slippage:</b> {avg_slippage_pts:.1f} pts\n\n"
        f"<i>System: Piploci Engine (Automated Reporting)</i>"
    )


async def send_daily_digest(chat_id: Optional[str] = None) -> None:
    """
    Queries today's closed trades from the DB and sends a full end-of-day
    P&L digest to Telegram. Fires automatically at 20:00 EAT via schedule_daily_digest.
    """
    from datetime import date, timedelta, datetime, timezone

    try:
        try:
            from bot.database import SessionLocal, TradeLogModel
        except ImportError:
            from database import SessionLocal, TradeLogModel

        today_utc_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        today_utc_end   = today_utc_start + timedelta(days=1)

        with SessionLocal() as db:
            trades = db.query(TradeLogModel).filter(
                TradeLogModel.timestamp >= today_utc_start,
                TradeLogModel.timestamp < today_utc_end,
                TradeLogModel.status == "CLOSED"
            ).all()

        total    = len(trades)
        wins     = sum(1 for t in trades if (t.pnl or 0) > 0)
        losses   = total - wins
        net_pnl  = sum(t.pnl or 0 for t in trades)
        win_rate = (wins / total * 100) if total > 0 else 0.0
        max_dd   = abs(min((t.pnl or 0) for t in trades)) if trades else 0.0

        # Per-pair breakdown
        pair_summary: dict = {}
        for t in trades:
            sym = t.symbol or "?"
            if sym not in pair_summary:
                pair_summary[sym] = {"w": 0, "l": 0, "pnl": 0.0}
            if (t.pnl or 0) > 0:
                pair_summary[sym]["w"] += 1
            else:
                pair_summary[sym]["l"] += 1
            pair_summary[sym]["pnl"] += t.pnl or 0

        pair_lines = "\n".join(
            f"  {sym}: {s['w']}W/{s['l']}L  {'+'if s['pnl']>=0 else''}${s['pnl']:.2f}"
            for sym, s in sorted(pair_summary.items())
        ) or "No trades today"

        date_str  = date.today().strftime("%d %b %Y")
        pnl_sign  = "+" if net_pnl >= 0 else ""
        pnl_emoji = "🟢" if net_pnl >= 0 else "🔴"

        msg = (
            f"<b>📊 Piploci — Daily Report ({date_str})</b>\n\n"
            f"{pnl_emoji} <b>Net P&L:</b> {pnl_sign}${net_pnl:.2f}\n"
            f"• <b>Total Trades:</b> {total} ({wins}W / {losses}L)\n"
            f"• <b>Win Rate:</b> {win_rate:.1f}%\n"
            f"• <b>Max Drawdown:</b> ${max_dd:.2f}\n\n"
            f"<b>Per-Pair Breakdown:</b>\n<code>{pair_lines}</code>\n\n"
            f"<i>System: Piploci Automated Engine — 20:00 EAT Report</i>"
        )
        await send_telegram_alert(msg, chat_id=chat_id)
        logger.info(f"Daily digest sent. Trades={total}, Net PnL={pnl_sign}${net_pnl:.2f}")

    except Exception as e:
        logger.error(f"Failed to generate daily digest: {e}")


async def schedule_daily_digest(chat_id: Optional[str] = None) -> None:
    """
    Background coroutine: fires send_daily_digest every day at 20:00 EAT (17:00 UTC).
    Launch once at bot startup via asyncio.create_task(schedule_daily_digest()).
    """
    from datetime import date, timedelta, datetime, timezone

    while True:
        now_utc = datetime.now(timezone.utc)
        target  = now_utc.replace(hour=17, minute=0, second=0, microsecond=0)
        if now_utc >= target:
            target += timedelta(days=1)
        wait_secs = (target - now_utc).total_seconds()
        logger.info(f"Daily digest: next report in {wait_secs/3600:.1f}h (20:00 EAT)")
        await asyncio.sleep(wait_secs)
        await send_daily_digest(chat_id=chat_id)
