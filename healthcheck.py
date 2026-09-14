"""
Piploci External Uptime Heartbeat & Alerts.
Monitors the local engine or tunnel endpoint every 60 seconds.
If the endpoint returns non-200 or connection times out twice consecutively,
triggers an emergency Telegram alert via notifier.py.
"""

import os
import asyncio
import logging
import httpx
from notifier import send_telegram_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("HealthCheck")

TARGET_URL = os.environ.get("HEALTHCHECK_URL", "http://127.0.0.1:8000/api/v1/status")
CHECK_INTERVAL_SECONDS = int(os.environ.get("HEALTHCHECK_INTERVAL", "60"))
CONSECUTIVE_FAILURE_THRESHOLD = 2

class HealthChecker:
    def __init__(self, target_url: str = TARGET_URL, interval: int = CHECK_INTERVAL_SECONDS):
        self.target_url = target_url
        self.interval = interval
        self.consecutive_failures = 0
        self.alert_dispatched = False

    async def check_once(self) -> bool:
        """
        Pings target URL. Returns True if status 200, False otherwise.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(self.target_url)
                if res.status_code == 200:
                    return True
                logger.warning(f"Health check non-200: status={res.status_code}")
                return False
        except Exception as e:
            logger.warning(f"Health check probe failed: {e}")
            return False

    async def handle_probe_result(self, is_healthy: bool) -> None:
        """
        Tracks consecutive failures and triggers alert if threshold met.
        """
        if is_healthy:
            if self.consecutive_failures > 0:
                logger.info(f"Health check recovered after {self.consecutive_failures} failures.")
            self.consecutive_failures = 0
            self.alert_dispatched = False
        else:
            self.consecutive_failures += 1
            logger.error(f"Health check consecutive failure count: {self.consecutive_failures}")
            if self.consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD and not self.alert_dispatched:
                alert_msg = (
                    "<b>🚨 CRITICAL: Piploci Engine Offline / Tunnel Disconnected!</b>\n\n"
                    f"Probe endpoint: <code>{self.target_url}</code>\n"
                    f"Consecutive failures: {self.consecutive_failures}\n"
                    "Automated watchdog alert."
                )
                logger.critical("Dispatching emergency heartbeat alert to Telegram.")
                await send_telegram_alert(alert_msg)
                self.alert_dispatched = True

    async def run_forever(self):
        logger.info(f"Starting HealthChecker on {self.target_url} (interval: {self.interval}s)")
        while True:
            is_healthy = await self.check_once()
            await self.handle_probe_result(is_healthy)
            await asyncio.sleep(self.interval)

if __name__ == "__main__":
    checker = HealthChecker()
    try:
        asyncio.run(checker.run_forever())
    except KeyboardInterrupt:
        logger.info("HealthCheck watchdog stopped.")
