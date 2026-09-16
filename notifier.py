"""
Notifier module for automated Telegram alerts.
Pushes real-time trade fills, circuit breaker triggers, and daily profit summaries.
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
    # Allow some basic html tags by reversing the escape for <b> </b> <i> </i>
    html_msg = html_msg.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")
    html_msg = html_msg.replace("&lt;i&gt;", "<i>").replace("&lt;/i&gt;", "</i>")
    
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

