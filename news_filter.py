"""
Economic News Shield & Blackout Buffer Evaluator.
Fetches high-impact economic events from live calendar feeds:
  1. Parse API (if PARSE_API_KEY is configured)
  2. Fair Economy Live ForexFactory Calendar feed (nfs.faireconomy.media)
  3. Stale cache (up to 1 hour)
  4. Deterministic fallback schedule for complete network blackouts

Enforces a strict configurable blackout window (default ±30 mins) on USD and JPY.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import logging
from typing import Tuple, List, Dict, Optional, Any

import httpx

from config import (
    NEWS_BUFFER_BEFORE_MINUTES,
    NEWS_BUFFER_AFTER_MINUTES,
    NEWS_SHIELD_CURRENCIES,
    PARSE_FOREXFACTORY_API_URL,
    PARSE_INVESTING_API_URL,
    PARSE_API_KEY,
    NEWS_REFRESH_INTERVAL_SECONDS,
)

logger = logging.getLogger("NewsFilter")

# Public ForexFactory feed provided by Fair Economy Media
PUBLIC_FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"


class EconomicNewsFilter:
    def __init__(self, blackout_minutes: int = 30):
        self.blackout_minutes = blackout_minutes
        self.cached_events: List[Dict[str, Any]] = []
        self.last_fetch_time: Optional[datetime] = None
        self.cache_ttl_seconds: int = NEWS_REFRESH_INTERVAL_SECONDS
        self._is_fetching: bool = False
        self._consecutive_failures: int = 0

    # ------------------------------------------------------------------
    # Calendar Fetching Pipeline
    # ------------------------------------------------------------------

    async def fetch_calendar_events(self) -> None:
        """Fetches the latest economic news calendar with multiple resilient sources."""
        if self._is_fetching:
            return
        self._is_fetching = True

        try:
            current_utc = datetime.now(timezone.utc)

            # 1. Try Parse API if API Key is configured
            if PARSE_API_KEY:
                headers = {"Authorization": f"Bearer {PARSE_API_KEY}"}
                for url in [PARSE_FOREXFACTORY_API_URL, PARSE_INVESTING_API_URL]:
                    if not url:
                        continue
                    events = await self._try_fetch_url(url, headers)
                    if events:
                        self._apply_events(events, current_utc, f"Parse API ({self._host(url)})")
                        return

            # 2. Try Public ForexFactory JSON Feed (Direct, reliable, no SSL issues)
            ff_events = await self._try_fetch_url(PUBLIC_FF_CALENDAR_URL, headers={})
            if ff_events:
                self._apply_events(ff_events, current_utc, "Fair Economy ForexFactory Feed")
                return

            # 3. If live feeds failed, check stale cache
            self._consecutive_failures += 1
            if self.cached_events:
                logger.warning(
                    f"Live economic feeds unreachable (attempt {self._consecutive_failures}). "
                    f"Retaining {len(self.cached_events)} cached events."
                )
                self.last_fetch_time = current_utc
            else:
                # 4. Safe offline fallback
                fallback = self._generate_fallback_schedule(current_utc)
                self._apply_events(fallback, current_utc, "Static Fallback Schedule (Offline)")

        finally:
            self._is_fetching = False

    def _apply_events(self, events: List[Dict[str, Any]], current_utc: datetime, source_name: str):
        self.cached_events = events
        self.last_fetch_time = current_utc
        self._consecutive_failures = 0
        logger.info(f"Loaded {len(events)} high-impact economic events from {source_name}.")

    async def _try_fetch_url(self, url: str, headers: Dict[str, str]) -> List[Dict[str, Any]]:
        """Safely executes HTTP GET and extracts matching high-impact news items."""
        for verify_ssl in (True, False):
            try:
                async with httpx.AsyncClient(
                    timeout=8.0,
                    verify=verify_ssl,
                    follow_redirects=True,
                    headers={"User-Agent": "MT5QuantEngine/1.0", **headers}
                ) as client:
                    resp = await client.get(url)

                    if resp.status_code != 200:
                        logger.debug(f"Calendar request to {self._host(url)} returned HTTP {resp.status_code}")
                        if resp.status_code == 526 and verify_ssl:
                            continue  # Retry with verify=False
                        return []

                    # Verify JSON content
                    content_type = resp.headers.get("content-type", "")
                    if "application/json" not in content_type and not resp.text.strip().startswith(("[", "{")):
                        logger.debug(f"Calendar response from {self._host(url)} was not JSON (content-type: {content_type})")
                        return []

                    data = resp.json()
                    events = self._parse_api_response(data)
                    if events:
                        return events
                    return []

            except httpx.ConnectError as e:
                if verify_ssl:
                    continue
                logger.debug(f"Connect error to {self._host(url)}: {e}")
                return []
            except Exception as e:
                logger.debug(f"Calendar fetch error ({self._host(url)}, verify={verify_ssl}): {e}")
                if verify_ssl:
                    continue
                return []

        return []

    @staticmethod
    def _host(url: str) -> str:
        try:
            return url.split("//", 1)[1].split("/", 1)[0]
        except Exception:
            return url[:40]

    # ------------------------------------------------------------------
    # Normalization & Filtering
    # ------------------------------------------------------------------

    def _parse_api_response(self, data: Any) -> List[Dict[str, Any]]:
        raw_list = data if isinstance(data, list) else data.get("events", data.get("data", []))
        parsed: List[Dict[str, Any]] = []

        for item in raw_list:
            impact = str(item.get("impact", "")).strip().upper()
            # Feed may use 'currency' or 'country'
            currency = str(item.get("currency") or item.get("country") or "").strip().upper()
            title = str(item.get("title") or item.get("event") or "Economic Release").strip()

            time_val = item.get("date") or item.get("time") or item.get("timestamp")
            event_dt = self._parse_iso_datetime(time_val) if time_val else None

            # Filter for High impact USD or JPY events
            if event_dt and currency in NEWS_SHIELD_CURRENCIES and impact in ["HIGH", "3", "RED"]:
                parsed.append({
                    "title": title,
                    "currency": currency,
                    "impact": "HIGH",
                    "time": event_dt,
                })

        return parsed

    def _parse_iso_datetime(self, val: Any) -> Optional[datetime]:
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        if isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return None

    def _generate_fallback_schedule(self, current_utc: datetime) -> List[Dict[str, Any]]:
        base_date = current_utc.replace(second=0, microsecond=0)
        return [
            {
                "title": "US Non-Farm Payrolls (Employment Situation)",
                "currency": "USD",
                "impact": "HIGH",
                "time": base_date.replace(hour=15, minute=30),
            },
            {
                "title": "Federal Reserve FOMC Rate Decision & Press Conference",
                "currency": "USD",
                "impact": "HIGH",
                "time": base_date.replace(hour=21, minute=0),
            },
            {
                "title": "Bank of Japan Interest Rate Decision & Monetary Statement",
                "currency": "JPY",
                "impact": "HIGH",
                "time": base_date.replace(hour=5, minute=0),
            },
        ]

    # ------------------------------------------------------------------
    # Blackout Window Evaluation (±30 mins)
    # ------------------------------------------------------------------

    async def is_news_blackout(self, symbol: str) -> Tuple[bool, Optional[str]]:
        now = datetime.now(timezone.utc)

        # Trigger background refresh if TTL expired or never fetched
        if not self.last_fetch_time or (now - self.last_fetch_time).total_seconds() > self.cache_ttl_seconds:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.fetch_calendar_events())
            except RuntimeError:
                pass

        target_currencies: List[str] = []
        sym = symbol.upper()
        if "USD" in sym:
            target_currencies.append("USD")
        if "JPY" in sym:
            target_currencies.append("JPY")
        if "XAU" in sym and "USD" not in target_currencies:
            target_currencies.append("USD")

        buffer_before = timedelta(minutes=self.blackout_minutes)
        buffer_after = timedelta(minutes=self.blackout_minutes)

        for event in self.cached_events:
            ev_curr = str(event.get("currency", "")).upper()
            if ev_curr not in target_currencies:
                continue

            ev_time = event.get("time")
            if not ev_time:
                continue

            if isinstance(ev_time, str):
                ev_time = self._parse_iso_datetime(ev_time)
                if not ev_time:
                    continue

            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=timezone.utc)

            window_start = ev_time - buffer_before
            window_end = ev_time + buffer_after

            if window_start <= now <= window_end:
                diff_minutes = (ev_time - now).total_seconds() / 60.0
                time_desc = f"in {diff_minutes:.0f}m" if diff_minutes >= 0 else f"{abs(diff_minutes):.0f}m ago"
                title = event.get("title", "High-Impact Release")
                reason = (
                    f"BLACKOUT SHIELD ACTIVE: {title} ({ev_curr}) scheduled {time_desc} "
                    f"(Window: ±{self.blackout_minutes} mins)"
                )
                return True, reason

        return False, None

    def get_upcoming_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        upcoming = [e for e in self.cached_events if e.get("time") and e["time"] >= now - timedelta(hours=1)]
        upcoming.sort(key=lambda x: x["time"])
        return upcoming[:limit]


# Singletons and aliases for backward-compatibility
news_filter = EconomicNewsFilter()
NewsFilter = EconomicNewsFilter
news_shield = news_filter
