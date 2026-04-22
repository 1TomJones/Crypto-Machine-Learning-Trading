"""Data API router – OHLCV retrieval and historical data loading."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import OHLCVBar, User
from app.schemas import OHLCVSchema

router = APIRouter()


@router.get("/ohlcv", response_model=list[OHLCVSchema])
async def get_ohlcv(
    symbol: str = Query(..., description="e.g. BTCUSDT"),
    exchange: str = Query("binance"),
    timeframe: str = Query("1m"),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    # Map timeframe → continuous aggregate view name
    view_map = {"5m": "ohlcv_5m", "15m": "ohlcv_15m", "1h": "ohlcv_1h",
                "4h": "ohlcv_4h", "1d": "ohlcv_1d"}
    if timeframe in view_map:
        tbl = view_map[timeframe]
        q = f"""
            SELECT 0 AS id, exchange, symbol, bucket AS ts, open, high, low, close, volume, 1 AS source_quality
            FROM {tbl}
            WHERE symbol = :sym AND exchange = :exch
        """
        params: dict = {"sym": symbol, "exch": exchange}
        if start:
            q += " AND bucket >= :start"
            params["start"] = start
        if end:
            q += " AND bucket <= :end"
            params["end"] = end
        q += " ORDER BY bucket DESC LIMIT :lim"
        params["lim"] = limit
        result = await db.execute(text(q), params)
        rows = result.mappings().all()
        return [OHLCVSchema(**dict(r)) for r in rows]

    # Default: raw 1m table
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


@router.post("/fetch-history")
async def fetch_history(
    symbol: str,
    interval: str = "1m",
    start_year: int = 2023,
    start_month: int = 1,
    end_year: int = 2024,
    end_month: int = 12,
    _user: User = Depends(get_current_user),
):
    """Queue an arq job to download historical Binance zip archives."""
    import arq

    from app.config import get_settings
    settings = get_settings()
    pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.redis_url))
    job = await pool.enqueue_job(
        "fetch_history",
        symbol=symbol,
        interval=interval,
        start_year=start_year,
        start_month=start_month,
        end_year=end_year,
        end_month=end_month,
    )
    await pool.aclose()
    return {"job_id": job.job_id, "status": "queued"}


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
