"""Binance data fetcher – REST klines (paginated) and monthly zip archives.

Rate-limit budget: Binance allows 1200 weight per minute for the public data
API.  Each ``/api/v3/klines`` call costs 2 weight; we stay well below the cap
by using a token-bucket that refills at 1200/60 = 20 weight per second.
"""
from __future__ import annotations

import asyncio
import io
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KLINE_LIMIT = 1000          # max rows per REST request
_WEIGHT_PER_KLINES = 2       # weight cost for /api/v3/klines with limit≤1000
_WEIGHT_BUDGET = 1200        # weight allowed per minute
_WEIGHT_REFILL_RATE = _WEIGHT_BUDGET / 60.0  # per second

# Interval string → duration in milliseconds
_INTERVAL_MS: dict[str, int] = {
    "1s":   1_000,
    "1m":   60_000,
    "3m":   180_000,
    "5m":   300_000,
    "15m":  900_000,
    "30m":  1_800_000,
    "1h":   3_600_000,
    "2h":   7_200_000,
    "4h":   14_400_000,
    "6h":   21_600_000,
    "8h":   28_800_000,
    "12h":  43_200_000,
    "1d":   86_400_000,
    "3d":   259_200_000,
    "1w":   604_800_000,
    "1M":   2_592_000_000,
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class OHLCVRow:
    """Single OHLCV bar as returned by the Binance API."""

    ts: datetime                    # bar open-time, UTC-aware
    open: float
    high: float
    low: float
    close: float
    volume: float
    source_quality: int = field(default=1)


# ---------------------------------------------------------------------------
# Token-bucket rate limiter
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Thread-safe async token bucket for rate limiting."""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self._capacity = capacity
        self._tokens = capacity
        self._rate = refill_rate          # tokens per second
        self._last_refill = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def consume(self, amount: float = 1.0) -> None:
        """Block until `amount` tokens are available, then consume them."""
        async with self._lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < amount:
                wait = (amount - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= amount


# ---------------------------------------------------------------------------
# Main fetcher
# ---------------------------------------------------------------------------


class BinanceDataFetcher:
    """Async Binance kline fetcher with rate-limiting and bulk-upsert support."""

    BASE_URL = "https://data-api.binance.vision"
    ARCHIVE_URL = "https://data.binance.vision"

    def __init__(
        self,
        base_url: str | None = None,
        archive_url: str | None = None,
        http_timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._archive_url = (archive_url or self.ARCHIVE_URL).rstrip("/")
        self._timeout = httpx.Timeout(http_timeout)
        self._client: httpx.AsyncClient | None = None
        self._bucket = _TokenBucket(
            capacity=float(_WEIGHT_BUDGET),
            refill_rate=_WEIGHT_REFILL_RATE,
        )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BinanceDataFetcher":
        await self._ensure_client()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={"Accept": "application/json"},
                http2=False,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Low-level GET with retry/backoff
    # ------------------------------------------------------------------

    async def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        weight: float = 1.0,
        max_retries: int = 6,
    ) -> Any:
        """GET with exponential back-off on 429 / 5xx."""
        await self._bucket.consume(weight)
        client = await self._ensure_client()
        delay = 1.0
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                resp = await client.get(url, params=params)

                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", delay))
                    log.warning(
                        "binance.rate_limited",
                        retry_after=retry_after,
                        attempt=attempt,
                    )
                    await asyncio.sleep(retry_after)
                    delay = min(delay * 2, 60.0)
                    continue

                if resp.status_code == 418:
                    # IP banned – back off hard
                    ban_until = float(resp.headers.get("Retry-After", 120))
                    log.error("binance.ip_banned", seconds=ban_until)
                    await asyncio.sleep(ban_until)
                    continue

                if resp.status_code >= 500:
                    log.warning(
                        "binance.server_error",
                        status=resp.status_code,
                        attempt=attempt,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue

                resp.raise_for_status()
                return resp.json()

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                log.warning(
                    "binance.request_error",
                    error=str(exc),
                    attempt=attempt,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

        raise RuntimeError(
            f"Binance request failed after {max_retries} retries: {last_exc}"
        )

    # ------------------------------------------------------------------
    # Kline helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _interval_ms(interval: str) -> int:
        ms = _INTERVAL_MS.get(interval)
        if ms is None:
            raise ValueError(f"Unknown interval '{interval}'. Valid: {sorted(_INTERVAL_MS)}")
        return ms

    @staticmethod
    def _parse_raw_klines(raw: list[list[Any]]) -> list[OHLCVRow]:
        rows: list[OHLCVRow] = []
        for k in raw:
            ts = datetime.fromtimestamp(int(k[0]) / 1000.0, tz=timezone.utc)
            rows.append(
                OHLCVRow(
                    ts=ts,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                )
            )
        return rows

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_ts: int,
        end_ts: int,
    ) -> list[OHLCVRow]:
        """Fetch up to 1000 bars per request, paginate automatically.

        Parameters
        ----------
        symbol:
            Binance symbol, e.g. ``"BTCUSDT"``.
        interval:
            Binance interval string, e.g. ``"1m"``.
        start_ts:
            Start time in **milliseconds** since Unix epoch (inclusive).
        end_ts:
            End time in **milliseconds** since Unix epoch (inclusive).

        Returns
        -------
        list[OHLCVRow]
            All bars in ``[start_ts, end_ts]``, sorted ascending.
        """
        url = f"{self._base_url}/api/v3/klines"
        interval_ms = self._interval_ms(interval)
        all_rows: list[OHLCVRow] = []
        cursor = start_ts

        while cursor < end_ts:
            params: dict[str, Any] = {
                "symbol": symbol.upper(),
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ts,
                "limit": _KLINE_LIMIT,
            }
            raw: list[list[Any]] = await self._get(
                url, params=params, weight=float(_WEIGHT_PER_KLINES)
            )

            if not raw:
                break

            batch = self._parse_raw_klines(raw)
            all_rows.extend(batch)

            # Advance cursor past the last returned bar
            last_open_ms = int(raw[-1][0])
            cursor = last_open_ms + interval_ms

            if len(raw) < _KLINE_LIMIT:
                # No more data in range
                break

            log.debug(
                "binance.klines_page",
                symbol=symbol,
                interval=interval,
                fetched=len(batch),
                total=len(all_rows),
                cursor_ts=cursor,
            )

        return all_rows

    async def fetch_klines_all(
        self,
        symbol: str,
        interval: str,
        start_dt: datetime,
        end_dt: datetime,
        session: AsyncSession,
        exchange: str = "binance",
    ) -> int:
        """Fetch all klines in ``[start_dt, end_dt]`` and upsert to DB.

        Returns
        -------
        int
            Number of rows upserted.
        """
        start_ts = int(start_dt.timestamp() * 1000)
        end_ts = int(end_dt.timestamp() * 1000)

        log.info(
            "binance.fetch_klines_all.start",
            symbol=symbol,
            interval=interval,
            start=start_dt.isoformat(),
            end=end_dt.isoformat(),
        )

        rows = await self.fetch_klines(symbol, interval, start_ts, end_ts)
        if not rows:
            log.info("binance.fetch_klines_all.no_data", symbol=symbol)
            return 0

        count = await _upsert_rows(rows, symbol, exchange, interval, session)
        log.info(
            "binance.fetch_klines_all.done",
            symbol=symbol,
            interval=interval,
            upserted=count,
        )
        return count

    # ------------------------------------------------------------------
    # Monthly zip archive
    # ------------------------------------------------------------------

    async def download_monthly_zip(
        self,
        symbol: str,
        interval: str,
        year: int,
        month: int,
    ) -> pd.DataFrame:
        """Download and parse a monthly kline zip from data.binance.vision.

        The archive CSV columns are (no header in the file):
        open_time, open, high, low, close, volume, close_time,
        quote_asset_volume, number_of_trades, taker_buy_base, taker_buy_quote, ignore

        Returns
        -------
        pd.DataFrame
            Columns: ``ts`` (UTC datetime), ``open``, ``high``, ``low``,
            ``close``, ``volume``.  Index is a RangeIndex.
        """
        sym = symbol.upper()
        fname = f"{sym}-{interval}-{year}-{month:02d}.zip"
        url = f"{self._archive_url}/data/spot/monthly/klines/{sym}/{interval}/{fname}"

        log.info("binance.archive_download", url=url)
        client = await self._ensure_client()

        delay = 2.0
        for attempt in range(5):
            try:
                resp = await client.get(url)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                log.warning(
                    "binance.archive_network_error",
                    error=str(exc),
                    attempt=attempt,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue

            if resp.status_code == 404:
                raise FileNotFoundError(f"Archive not found: {url}")
            if resp.status_code >= 500:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
                continue

            resp.raise_for_status()

            # Parse zip in memory
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_name = next(
                    (n for n in zf.namelist() if n.endswith(".csv")), None
                )
                if csv_name is None:
                    raise ValueError(f"No CSV found in zip: {fname}")
                with zf.open(csv_name) as csv_file:
                    df = pd.read_csv(
                        csv_file,
                        header=None,
                        names=[
                            "open_time", "open", "high", "low", "close", "volume",
                            "close_time", "quote_vol", "trades",
                            "taker_buy_base", "taker_buy_quote", "ignore",
                        ],
                        dtype={
                            "open_time": "int64",
                            "open": "float64",
                            "high": "float64",
                            "low": "float64",
                            "close": "float64",
                            "volume": "float64",
                        },
                    )

            df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            result = df[["ts", "open", "high", "low", "close", "volume"]].copy()
            result = result.sort_values("ts").reset_index(drop=True)

            log.info(
                "binance.archive_parsed",
                symbol=sym,
                interval=interval,
                year=year,
                month=month,
                rows=len(result),
            )
            return result

        raise RuntimeError(f"Failed to download archive after retries: {url}")

    async def bulk_load_history(
        self,
        symbol: str,
        interval: str,
        start_year: int,
        start_month: int,
        end_year: int,
        end_month: int,
        session: AsyncSession,
        exchange: str = "binance",
    ) -> int:
        """Download monthly zip archives and bulk-upsert to DB.

        Iterates month-by-month from ``(start_year, start_month)`` through
        ``(end_year, end_month)`` inclusive.

        Returns
        -------
        int
            Total rows upserted.
        """
        total = 0
        year, month = start_year, start_month

        while (year, month) <= (end_year, end_month):
            try:
                df = await self.download_monthly_zip(symbol, interval, year, month)
            except FileNotFoundError:
                log.warning(
                    "binance.bulk_load.archive_missing",
                    symbol=symbol,
                    year=year,
                    month=month,
                )
                year, month = _next_month(year, month)
                continue

            rows = _df_to_ohlcv_rows(df)
            count = await _upsert_rows(rows, symbol, exchange, interval, session)
            total += count

            log.info(
                "binance.bulk_load.month_done",
                symbol=symbol,
                year=year,
                month=month,
                upserted=count,
                running_total=total,
            )
            year, month = _next_month(year, month)

        log.info(
            "binance.bulk_load.complete",
            symbol=symbol,
            interval=interval,
            total_upserted=total,
        )
        return total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _df_to_ohlcv_rows(df: pd.DataFrame) -> list[OHLCVRow]:
    rows: list[OHLCVRow] = []
    for row in df.itertuples(index=False):
        ts = row.ts
        if not isinstance(ts, datetime):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        rows.append(
            OHLCVRow(
                ts=ts,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
        )
    return rows


async def _upsert_rows(
    rows: list[OHLCVRow],
    symbol: str,
    exchange: str,
    timeframe: str,
    session: AsyncSession,
    batch_size: int = 2000,
) -> int:
    """Bulk-upsert OHLCVRow list into ohlcv_bars using ON CONFLICT DO UPDATE.

    Uses raw SQL with unnest for maximum throughput.
    """
    if not rows:
        return 0

    upsert_sql = text(
        """
        INSERT INTO ohlcv_bars (symbol, exchange, timeframe, ts, open, high, low, close, volume, source_quality)
        SELECT
            :symbol, :exchange, :timeframe,
            unnest(:ts_arr::timestamptz[]),
            unnest(:open_arr::float8[]),
            unnest(:high_arr::float8[]),
            unnest(:low_arr::float8[]),
            unnest(:close_arr::float8[]),
            unnest(:volume_arr::float8[]),
            unnest(:sq_arr::smallint[])
        ON CONFLICT ON CONSTRAINT uq_ohlcv_bar
        DO UPDATE SET
            open           = EXCLUDED.open,
            high           = EXCLUDED.high,
            low            = EXCLUDED.low,
            close          = EXCLUDED.close,
            volume         = EXCLUDED.volume,
            source_quality = EXCLUDED.source_quality
        """
    )

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        await session.execute(
            upsert_sql,
            {
                "symbol": symbol.upper(),
                "exchange": exchange,
                "timeframe": timeframe,
                "ts_arr": [r.ts.isoformat() for r in batch],
                "open_arr": [r.open for r in batch],
                "high_arr": [r.high for r in batch],
                "low_arr": [r.low for r in batch],
                "close_arr": [r.close for r in batch],
                "volume_arr": [r.volume for r in batch],
                "sq_arr": [r.source_quality for r in batch],
            },
        )
        total += len(batch)

    await session.commit()
    return total
