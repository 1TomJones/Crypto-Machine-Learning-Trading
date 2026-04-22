"""Kraken data fetcher using ccxt async_support.

Provides OHLCV REST fetching and L2 order-book snapshots.  The Kraken REST
API returns the last 720 candles at 1-minute resolution per call; this class
handles that limitation gracefully.
"""
from __future__ import annotations

from typing import Any

import ccxt.async_support as ccxt
import pandas as pd
import structlog

log = structlog.get_logger(__name__)

# Kraken timeframe string → approximate duration in seconds (for stale detection)
_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m":  60,
    "5m":  300,
    "15m": 900,
    "30m": 1800,
    "1h":  3600,
    "4h":  14400,
    "1d":  86400,
    "1w":  604800,
}

# Maximum candles Kraken returns per call at 1m resolution
_KRAKEN_MAX_CANDLES = 720


class KrakenDataFetcher:
    """Async Kraken data fetcher backed by ccxt.async_support.kraken.

    Usage::

        async with KrakenDataFetcher(api_key, api_secret) as kf:
            df = await kf.fetch_ohlcv("BTC/USDT", "1m")
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
    ) -> None:
        self.exchange: ccxt.kraken = ccxt.kraken(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )
        self._markets_loaded = False

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "KrakenDataFetcher":
        await self._ensure_markets()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_markets(self) -> None:
        if not self._markets_loaded:
            await self.exchange.load_markets()
            self._markets_loaded = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: int | None = None,
        limit: int = _KRAKEN_MAX_CANDLES,
    ) -> pd.DataFrame:
        """Fetch OHLCV from Kraken REST.

        Parameters
        ----------
        symbol:
            ccxt symbol, e.g. ``"BTC/USDT"`` or ``"BTC/USD"``.
        timeframe:
            ccxt timeframe string, e.g. ``"1m"``, ``"5m"``, ``"1h"``.
        since:
            Start time as milliseconds since Unix epoch.  Kraken ignores this
            for most resolutions and always returns the last ``limit`` candles.
        limit:
            Max candles to return (Kraken caps at 720 for 1m).

        Returns
        -------
        pd.DataFrame
            Columns: ``ts`` (UTC-aware datetime), ``open``, ``high``, ``low``,
            ``close``, ``volume``.  Sorted ascending by ``ts``.
        """
        await self._ensure_markets()

        effective_limit = min(limit, _KRAKEN_MAX_CANDLES)

        log.debug(
            "kraken.fetch_ohlcv",
            symbol=symbol,
            timeframe=timeframe,
            since=since,
            limit=effective_limit,
        )

        try:
            raw: list[list[Any]] = await self.exchange.fetch_ohlcv(
                symbol,
                timeframe=timeframe,
                since=since,
                limit=effective_limit,
            )
        except ccxt.NetworkError as exc:
            log.error("kraken.fetch_ohlcv.network_error", error=str(exc))
            raise
        except ccxt.ExchangeError as exc:
            log.error("kraken.fetch_ohlcv.exchange_error", error=str(exc))
            raise

        if not raw:
            log.warning("kraken.fetch_ohlcv.empty", symbol=symbol, timeframe=timeframe)
            return _empty_ohlcv_df()

        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = (
            df[["ts", "open", "high", "low", "close", "volume"]]
            .sort_values("ts")
            .reset_index(drop=True)
        )
        df[["open", "high", "low", "close", "volume"]] = df[
            ["open", "high", "low", "close", "volume"]
        ].astype("float64")

        log.debug(
            "kraken.fetch_ohlcv.done",
            symbol=symbol,
            timeframe=timeframe,
            rows=len(df),
            first_ts=str(df["ts"].iloc[0]) if len(df) > 0 else None,
            last_ts=str(df["ts"].iloc[-1]) if len(df) > 0 else None,
        )
        return df

    async def fetch_order_book(
        self,
        symbol: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Fetch L2 order book snapshot.

        Parameters
        ----------
        symbol:
            ccxt symbol, e.g. ``"BTC/USDT"``.
        limit:
            Number of price levels to request per side.

        Returns
        -------
        dict
            ccxt order-book dict with keys ``bids``, ``asks``, ``timestamp``,
            ``datetime``, ``nonce``.  Each of ``bids``/``asks`` is a list of
            ``[price, amount]`` pairs sorted best-first.
        """
        await self._ensure_markets()

        log.debug("kraken.fetch_order_book", symbol=symbol, limit=limit)

        try:
            book: dict[str, Any] = await self.exchange.fetch_order_book(
                symbol, limit=limit
            )
        except ccxt.NetworkError as exc:
            log.error("kraken.fetch_order_book.network_error", error=str(exc))
            raise
        except ccxt.ExchangeError as exc:
            log.error("kraken.fetch_order_book.exchange_error", error=str(exc))
            raise

        log.debug(
            "kraken.fetch_order_book.done",
            symbol=symbol,
            best_bid=book["bids"][0][0] if book.get("bids") else None,
            best_ask=book["asks"][0][0] if book.get("asks") else None,
        )
        return book

    async def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        """Fetch the latest ticker for a symbol.

        Returns the raw ccxt ticker dict (last, bid, ask, volume, etc.).
        """
        await self._ensure_markets()
        try:
            return await self.exchange.fetch_ticker(symbol)
        except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
            log.error("kraken.fetch_ticker.error", symbol=symbol, error=str(exc))
            raise

    async def list_symbols(self) -> list[str]:
        """Return all available ccxt symbol strings for this exchange."""
        await self._ensure_markets()
        return list(self.exchange.markets.keys())

    async def close(self) -> None:
        """Close the underlying ccxt HTTP session."""
        try:
            await self.exchange.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("kraken.close.error", error=str(exc))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_ohlcv_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
