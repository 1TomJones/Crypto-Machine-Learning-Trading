"""Data API router – OHLCV retrieval and historical data loading."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import OHLCVBar, User
from app.schemas import OHLCVSchema

router = APIRouter()

_BUCKET_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


@router.get("/ohlcv", response_model=list[OHLCVSchema])
async def get_ohlcv(
    symbol: str = Query(...),
    exchange: str = Query("binance"),
    timeframe: str = Query("1m"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    if timeframe in _BUCKET_SECONDS:
        # Aggregate using epoch bucketing — works without TimescaleDB
        secs = _BUCKET_SECONDS[timeframe]
        where_extra = ""
        params: dict = {"sym": symbol, "exch": exchange, "lim": limit}
        if start:
            where_extra += " AND ts >= :start"
            params["start"] = start
        if end:
            where_extra += " AND ts <= :end"
            params["end"] = end

        q = text(f"""
            WITH b AS (
                SELECT exchange, symbol,
                       to_timestamp(FLOOR(EXTRACT(EPOCH FROM ts) / {secs}) * {secs}) AS bucket,
                       open, high, low, close, volume, ts
                FROM ohlcv
                WHERE symbol = :sym AND exchange = :exch{where_extra}
            )
            SELECT 0 AS id, exchange, symbol, bucket AS ts,
                   (array_agg(open  ORDER BY ts))[1]      AS open,
                   max(high)                               AS high,
                   min(low)                                AS low,
                   (array_agg(close ORDER BY ts DESC))[1]  AS close,
                   sum(volume)                             AS volume,
                   1                                       AS source_quality
            FROM b
            GROUP BY exchange, symbol, bucket
            ORDER BY bucket DESC
            LIMIT :lim
        """)
        result = await db.execute(q, params)
        rows = result.mappings().all()
        return [OHLCVSchema(**dict(r)) for r in rows]

    # Raw 1m table
    q = select(OHLCVBar).where(
        OHLCVBar.symbol == symbol, OHLCVBar.exchange == exchange
    )
    if start:
        q = q.where(OHLCVBar.ts >= start)
    if end:
        q = q.where(OHLCVBar.ts <= end)
    q = q.order_by(OHLCVBar.ts.desc()).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/symbols")
async def get_symbols(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(
            OHLCVBar.exchange,
            OHLCVBar.symbol,
            func.count(OHLCVBar.id).label("bar_count"),
            func.min(OHLCVBar.ts).label("first_bar"),
            func.max(OHLCVBar.ts).label("last_bar"),
        ).group_by(OHLCVBar.exchange, OHLCVBar.symbol)
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.post("/seed")
async def seed_ohlcv(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("1h"),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Fetch recent candles directly from Binance public REST and store in DB."""
    binance_symbol = symbol.replace("/", "")
    interval_map = {"1m": "1m", "5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    interval = interval_map.get(timeframe, "1h")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://data-api.binance.vision/api/v3/klines",
                params={"symbol": binance_symbol, "interval": interval, "limit": limit},
            )
            resp.raise_for_status()
            klines = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Binance API error: {exc}")

    rows = [
        {
            "exchange": "binance",
            "symbol": symbol,
            "ts": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "source_quality": 1,
        }
        for k in klines
    ]
    stmt = pg_insert(OHLCVBar).values(rows).on_conflict_do_nothing()
    await db.execute(stmt)
    return {"inserted": len(rows), "symbol": symbol, "timeframe": timeframe}


@router.get("/quality")
async def data_quality(
    symbol: str = Query(...),
    exchange: str = Query("binance"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    total = await db.scalar(
        select(func.count(OHLCVBar.id)).where(
            OHLCVBar.symbol == symbol, OHLCVBar.exchange == exchange
        )
    )
    gaps = await db.scalar(
        select(func.count(OHLCVBar.id)).where(
            OHLCVBar.symbol == symbol,
            OHLCVBar.exchange == exchange,
            OHLCVBar.source_quality == 0,
        )
    )
    first = await db.scalar(
        select(func.min(OHLCVBar.ts)).where(
            OHLCVBar.symbol == symbol, OHLCVBar.exchange == exchange
        )
    )
    last = await db.scalar(
        select(func.max(OHLCVBar.ts)).where(
            OHLCVBar.symbol == symbol, OHLCVBar.exchange == exchange
        )
    )
    return {
        "symbol": symbol,
        "exchange": exchange,
        "total_bars": total or 0,
        "gap_bars": gaps or 0,
        "completeness_pct": round(100 * (1 - (gaps or 0) / max(total or 1, 1)), 2),
        "first_bar": first,
        "last_bar": last,
    }
