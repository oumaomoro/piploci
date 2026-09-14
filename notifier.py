"""
Notifier module for automated Telegram alerts.
Pushes real-time trade fills, circuit breaker triggers, and daily profit summaries.
"""

import os
import httpx
import logging
import asyncio

logger = logging.getLogger("Notifier")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

async def send_telegram_alert(message: str) -> None:
    """
    Sends a formatted Markdown message to a designated Telegram chat.
    Fails silently with a warning if tokens are not configured.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"Telegram alert skipped (Not configured): {message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
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

