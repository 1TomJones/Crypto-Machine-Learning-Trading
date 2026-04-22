"""Live WebSocket ingestion – Binance primary, Kraken fallback."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Callable

import orjson
import redis.asyncio as aioredis
import structlog
import websockets
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.binance import OHLCVRow

log = structlog.get_logger(__name__)

_INTERVAL_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400,
}

_UPSERT_SQL = text("""
    INSERT INTO ohlcv (exchange, symbol, ts, open, high, low, close, volume, source_quality)
    VALUES (:exchange, :symbol, :ts, :open, :high, :low, :close, :volume, :sq)
    ON CONFLICT (exchange, symbol, ts)
    DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                  close=EXCLUDED.close, volume=EXCLUDED.volume,
                  source_quality=EXCLUDED.source_quality
""")


class BarAggregator:
    """Accumulates tick messages and emits completed bars."""

    def __init__(self) -> None:
        self._current: OHLCVRow | None = None
        self._bar_complete = False

    def update_from_binance_kline(self, kline: dict) -> OHLCVRow | None:
        """Parse a Binance kline WebSocket message. Returns bar only when closed."""
        bar = OHLCVRow(
            ts=datetime.fromtimestamp(kline["t"] / 1000, tz=timezone.utc),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
        )
        if kline.get("x"):  # bar is closed
            return bar
        return None


class LiveIngestionManager:
    """Manages live WebSocket feeds. Writes bars to DB and publishes to Redis."""

    def __init__(
        self,
        redis_client: aioredis.Redis,
        session_factory: Callable,
        exchange: str = "binance",
    ) -> None:
        self.redis = redis_client
        self.session_factory = session_factory
        self.exchange = exchange
        self._running = False
        self._stale_threshold: int = 5  # bars
        self._last_bar_ts: dict[str, float] = {}
        self._aggregator = BarAggregator()

    async def start(self, symbol: str = "BTCUSDT", interval: str = "1m") -> None:
        self._running = True
        log.info("ingestion_starting", symbol=symbol, interval=interval)
        while self._running:
            try:
                await self._binance_ws_loop(symbol, interval)
            except Exception as exc:
                log.warning("binance_ws_error", error=str(exc))
                if self._running:
                    await asyncio.sleep(5)
                    try:
                        await self._kraken_ws_fallback(symbol, interval)
                    except Exception as exc2:
                        log.error("kraken_fallback_error", error=str(exc2))
                    await asyncio.sleep(10)

    async def _binance_ws_loop(self, symbol: str, interval: str) -> None:
        stream = symbol.lower() + "@kline_" + interval
        url = f"wss://stream.binance.com:9443/ws/{stream}"
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    log.info("binance_ws_connected", url=url)
                    backoff = 1
                    async for raw in ws:
                        if not self._running:
                            return
                        msg = orjson.loads(raw)
                        if msg.get("e") == "kline":
                            bar = self._aggregator.update_from_binance_kline(msg["k"])
                            if bar is not None:
                                await self._on_bar(bar, symbol, "binance")
            except websockets.ConnectionClosed:
                log.warning("binance_ws_closed", backoff=backoff)
            except Exception as exc:
                log.warning("binance_ws_error", error=str(exc), backoff=backoff)
            if self._running:
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    async def _kraken_ws_fallback(self, symbol: str, interval: str) -> None:
        """Fallback using ccxt.pro kraken WebSocket."""
        try:
            import ccxt.pro as ccxtpro
        except ImportError:
            log.error("ccxt_pro_not_available")
            return

        exchange = ccxtpro.kraken({"enableRateLimit": True})
        kraken_symbol = symbol.replace("USDT", "/USDT").replace("GBP", "/GBP")
        try:
            while self._running:
                ohlcv = await exchange.watch_ohlcv(kraken_symbol, interval)
                for row in ohlcv:
                    ts, o, h, l, c, v = row
                    bar = OHLCVRow(
                        ts=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                        open=o, high=h, low=l, close=c, volume=v,
                    )
                    await self._on_bar(bar, symbol, "kraken")
        finally:
            await exchange.close()

    async def _on_bar(self, bar: OHLCVRow, symbol: str, source: str) -> None:
        """Persist bar to DB and publish to Redis."""
        self._last_bar_ts[symbol] = time.time()
        try:
            async with self.session_factory() as session:
                await session.execute(
                    _UPSERT_SQL,
                    {
                        "exchange": source,
                        "symbol": symbol,
                        "ts": bar.ts,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "sq": bar.source_quality,
                    },
                )
                await session.commit()
        except Exception as exc:
            log.error("bar_db_error", error=str(exc))

        tick_payload = orjson.dumps(
            {
                "symbol": symbol,
                "ts": bar.ts.isoformat(),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "source": source,
            }
        ).decode()
        await self.redis.publish("trader:ticks", tick_payload)

    def is_data_stale(self, symbol: str, interval: str = "1m") -> bool:
        last = self._last_bar_ts.get(symbol)
        if last is None:
            return True
        interval_secs = _INTERVAL_SECONDS.get(interval, 60)
        return (time.time() - last) > (self._stale_threshold * interval_secs)

    async def stop(self) -> None:
        self._running = False
        log.info("ingestion_stopped")
