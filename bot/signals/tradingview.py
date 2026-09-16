"""
TradingView Technical Analysis Consensus Analyzer.
Utilizes tradingview-ta for multi-timeframe trend alignment across M15 and H1 intervals.
Enforces strict consensus rules for Gold and USDJPY execution.

Rate-limit protection: results are cached per symbol/interval for CACHE_TTL_SECONDS
to avoid HTTP 429 errors from TradingView's public scanner endpoint.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import logging

try:
    from tradingview_ta import TA_Handler, Interval
    TV_AVAILABLE = True
except ImportError:
    TV_AVAILABLE = False
    Interval = None

try:
    from bot.config import SYMBOL_CONFIGS
except ImportError:
    from config import SYMBOL_CONFIGS

logger = logging.getLogger("TradingViewTA")

# Minimum seconds between live API calls per (symbol, interval) pair.
CACHE_TTL_SECONDS = 60
# Short negative cache TTL for failures (e.g. 429 rate limits) to allow faster recovery
CACHE_ERROR_TTL_SECONDS = 10

INTERVAL_MAP = {
    "M15": getattr(Interval, "INTERVAL_15_MINUTES", "15m") if TV_AVAILABLE else "15m",
    "H1":  getattr(Interval, "INTERVAL_1_HOUR",       "1h") if TV_AVAILABLE else "1h",
}


class TradingViewAnalyzer:
    def __init__(self):
        # Stores the last successful result per cache key
        self._result_cache: Dict[str, Dict[str, Any]] = {}
        # Stores the UTC datetime of the last successful fetch per cache key
        self._fetch_time:   Dict[str, datetime] = {}
        # Final aligned-signal cache (keyed by symbol)
        self.cached_signals: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_key(self, symbol: str, interval_key: str) -> str:
        return f"{symbol}:{interval_key}"

    def _is_cache_fresh(self, key: str) -> bool:
        """Returns True if the cached result is younger than applicable TTL."""
        last = self._fetch_time.get(key)
        if last is None:
            return False
        age = (datetime.now(timezone.utc) - last).total_seconds()
        
        status = self._result_cache.get(key, {}).get("status", "LIVE")
        if status in ["STALE_CACHE", "FEED_UNAVAILABLE"]:
            return age < CACHE_ERROR_TTL_SECONDS
            
        return age < CACHE_TTL_SECONDS

    def _store_cache(self, key: str, result: Dict[str, Any]) -> None:
        self._result_cache[key] = result
        self._fetch_time[key] = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_interval_analysis(self, symbol: str, interval_key: str = "M15") -> Dict[str, Any]:
        """
        Fetches technical indicators for a specific timeframe.
        Returns a cached result if the last fetch is within CACHE_TTL_SECONDS,
        preventing HTTP 429 rate-limit errors from TradingView.
        """
        key = self._cache_key(symbol, interval_key)

        # Return cached result if still fresh
        if self._is_cache_fresh(key):
            logger.debug(f"TradingViewTA: cache hit for {symbol} ({interval_key}).")
            return self._result_cache[key]

        # Library unavailable — return neutral state immediately
        if not TV_AVAILABLE:
            return self._neutral_response(symbol, interval_key, reason="LIBRARY_UNAVAILABLE")

        cfg         = SYMBOL_CONFIGS.get(symbol, {})
        tv_sym      = cfg.get("tradingview_symbol", symbol)
        tv_exchange = cfg.get("tradingview_exchange", "OANDA")
        tv_screener = cfg.get("tradingview_screener", "forex")
        interval    = INTERVAL_MAP.get(interval_key, Interval.INTERVAL_15_MINUTES)

        try:
            handler = TA_Handler(
                symbol=tv_sym,
                exchange=tv_exchange,
                screener=tv_screener,
                interval=interval,
                timeout=4,
            )
            analysis    = handler.get_analysis()
            summary     = analysis.summary    or {}
            indicators  = analysis.indicators or {}

            result = {
                "symbol":           symbol,
                "interval":         interval_key,
                "recommendation":   summary.get("RECOMMENDATION", "NEUTRAL"),
                "buy_votes":        summary.get("BUY",     0),
                "sell_votes":       summary.get("SELL",    0),
                "neutral_votes":    summary.get("NEUTRAL", 0),
                "rsi":              round(indicators.get("RSI", 50.0), 2),
                "macd":             indicators.get("MACD.macd",   0.0),
                "macd_signal":      indicators.get("MACD.signal", 0.0),
                "ema20":            indicators.get("EMA20",  0.0),
                "sma50":            indicators.get("SMA50",  0.0),
                "close":            indicators.get("close",  0.0),
                "atr":              indicators.get("ATR",    1.0),
                "status":           "LIVE",
            }
            self._store_cache(key, result)
            logger.info(f"TradingViewTA: live fetch OK — {symbol} ({interval_key}) → {result['recommendation']}")
            return result

        except Exception as e:
            err_str = str(e)
            # On 429 or any network error serve the stale cache if available,
            # otherwise fall back to neutral state.
            if key in self._result_cache and self._result_cache[key].get("status") == "LIVE":
                stale = dict(self._result_cache[key])
                stale["status"] = "STALE_CACHE"
                # Cooldown so we don't immediately bombard the API again
                self._fetch_time[key] = datetime.now(timezone.utc)
                logger.warning(
                    f"TradingViewTA: fetch failed for {symbol} ({interval_key}) — "
                    f"serving stale cache. Cooldown set. Error: {err_str}"
                )
                return stale

            neutral = self._neutral_response(symbol, interval_key, reason="FEED_UNAVAILABLE")
            # Store cooling cache for CACHE_TTL_SECONDS so we don't bombard TradingView while rate-limited
            self._store_cache(key, neutral)
            logger.warning(
                f"TradingViewTA: fetch failed for {symbol} ({interval_key}) — "
                f"cached NEUTRAL cooldown for {CACHE_TTL_SECONDS}s. Error: {err_str}"
            )
            return neutral

    def get_aligned_signal(self, symbol: str) -> Dict[str, Any]:
        """
        Evaluates multi-timeframe alignment across M15 and H1 timeframes for all 8 pairs.

        XAUUSD  — Strictest: STRONG_BUY/SELL on M15 + BUY/SELL on H1 (high volatility asset).
        USDJPY  — Strict:    BUY/STRONG_BUY on BOTH M15 + H1.
        FX Pairs — Confluence: M15 + H1 must agree direction (BUY family or SELL family),
                               PLUS at least one of: RSI confirmation, MACD crossover.
                               Prevents weak/random signals from entering.
        """
        m15_data = self.fetch_interval_analysis(symbol, "M15")
        h1_data  = self.fetch_interval_analysis(symbol, "H1")

        m15_rec = str(m15_data.get("recommendation", "NEUTRAL")).upper()
        h1_rec  = str(h1_data.get("recommendation",  "NEUTRAL")).upper()

        # RSI and MACD for confluence confirmation on forex pairs
        rsi        = m15_data.get("rsi") or 50.0
        macd_val   = m15_data.get("macd", 0.0) or 0.0
        macd_sig   = m15_data.get("macd_signal", 0.0) or 0.0
        macd_cross_bull = macd_val > macd_sig   # MACD line crossed above signal
        macd_cross_bear = macd_val < macd_sig   # MACD line crossed below signal
        rsi_bull   = rsi < 60.0  # Not overbought — room to run
        rsi_bear   = rsi > 40.0  # Not oversold — room to run

        BUY_RECS  = {"BUY", "STRONG_BUY"}
        SELL_RECS = {"SELL", "STRONG_SELL"}

        direction  = "NEUTRAL"
        is_aligned = False
        reason     = "No multi-timeframe consensus"

        # ------------------------------------------------------------------ #
        # XAUUSD — Strictest filter (high volatility, news sensitive)
        # ------------------------------------------------------------------ #
        if symbol == "XAUUSD":
            if m15_rec == "STRONG_BUY" and h1_rec in BUY_RECS:
                direction, is_aligned = "BUY", True
                reason = f"Gold Bullish: M15=STRONG_BUY + H1={h1_rec}"
            elif m15_rec == "STRONG_SELL" and h1_rec in SELL_RECS:
                direction, is_aligned = "SELL", True
                reason = f"Gold Bearish: M15=STRONG_SELL + H1={h1_rec}"
            else:
                reason = f"Gold Pending: M15={m15_rec}, H1={h1_rec} (Needs STRONG_BUY/SELL on M15)"

        # ------------------------------------------------------------------ #
        # USDJPY — Strict alignment both timeframes required
        # ------------------------------------------------------------------ #
        elif symbol == "USDJPY":
            if m15_rec in BUY_RECS and h1_rec in BUY_RECS:
                direction, is_aligned = "BUY", True
                reason = f"USDJPY Bullish: M15={m15_rec} + H1={h1_rec}"
            elif m15_rec in SELL_RECS and h1_rec in SELL_RECS:
                direction, is_aligned = "SELL", True
                reason = f"USDJPY Bearish: M15={m15_rec} + H1={h1_rec}"
            else:
                reason = f"USDJPY Divergence: M15={m15_rec}, H1={h1_rec}"

        # ------------------------------------------------------------------ #
        # All other FX pairs — Confluence: TF alignment + RSI or MACD confirm
        # ------------------------------------------------------------------ #
        elif symbol in {"EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"}:
            both_bullish = m15_rec in BUY_RECS  and h1_rec in BUY_RECS
            both_bearish = m15_rec in SELL_RECS and h1_rec in SELL_RECS

            if both_bullish:
                # Require at least one extra confluence: RSI not overbought OR MACD bull cross
                if rsi_bull or macd_cross_bull:
                    direction, is_aligned = "BUY", True
                    confluence = f"RSI={rsi:.1f}" if rsi_bull else f"MACD-CrossBull"
                    reason = f"{symbol} Bullish: M15={m15_rec} + H1={h1_rec} | {confluence}"
                else:
                    reason = (
                        f"{symbol} Bullish TF aligned but no confluence "
                        f"(RSI={rsi:.1f} overbought, MACD bearish cross)"
                    )

            elif both_bearish:
                # Require at least one extra confluence: RSI not oversold OR MACD bear cross
                if rsi_bear or macd_cross_bear:
                    direction, is_aligned = "SELL", True
                    confluence = f"RSI={rsi:.1f}" if rsi_bear else f"MACD-CrossBear"
                    reason = f"{symbol} Bearish: M15={m15_rec} + H1={h1_rec} | {confluence}"
                else:
                    reason = (
                        f"{symbol} Bearish TF aligned but no confluence "
                        f"(RSI={rsi:.1f} oversold, MACD bullish cross)"
                    )
            else:
                reason = f"{symbol} Divergence: M15={m15_rec}, H1={h1_rec}"

        result = {
            "symbol":             symbol,
            "direction":          direction,
            "action":             direction,
            "is_aligned":         is_aligned,
            "reason":             reason,
            "m15":                m15_data,
            "h1":                 h1_data,
            "m15_recommendation": m15_rec,
            "h1_recommendation":  h1_rec,
            "rsi":                round(rsi, 2),
            "macd_bull_cross":    macd_cross_bull,
            "macd_bear_cross":    macd_cross_bear,
            "atr_14":             m15_data.get("atr", 1.0),
            "overall_status":     "ALIGNED" if is_aligned else "WAITING",
        }
        self.cached_signals[symbol] = result
        return result


    async def get_aligned_signal_async(self, symbol: str) -> Dict[str, Any]:
        """Asynchronously evaluates multi-timeframe alignment without blocking the async event loop."""
        import asyncio
        return await asyncio.to_thread(self.get_aligned_signal, symbol)

    async def refresh_all_signals_async(self, symbols: Optional[list] = None) -> Dict[str, Any]:
        """Concurrently evaluates multiple symbols using thread pool for ultra-low latency."""
        import asyncio
        sym_list = symbols or list(SYMBOL_CONFIGS.keys())
        tasks = [asyncio.to_thread(self.get_aligned_signal, s) for s in sym_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for s, res in zip(sym_list, results):
            if isinstance(res, Exception):
                logger.warning(f"Async TA fetch error for {s}: {res}")
                out[s] = self.cached_signals.get(s) or self._neutral_response(s, "M15")
            else:
                out[s] = res
        return out

    def _neutral_response(self, symbol: str, interval: str, reason: str = "FEED_UNAVAILABLE") -> Dict[str, Any]:
        """Returns a safe neutral indicator state when a live fetch is impossible."""
        return {
            "symbol":        symbol,
            "interval":      interval,
            "recommendation": "NEUTRAL",
            "buy_votes":     0,
            "sell_votes":    0,
            "neutral_votes": 0,
            "rsi":           None,
            "macd":          0.0,
            "macd_signal":   0.0,
            "ema20":         0.0,
            "sma50":         0.0,
            "close":         0.0,
            "atr":           0.0,
            "status":        reason,
        }


tv_analyzer = TradingViewAnalyzer()
get_aligned_signal = tv_analyzer.get_aligned_signal

