"""Backtest router."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import BacktestResult, User

router = APIRouter()


class BacktestRequest(BaseModel):
    strategy_id: uuid.UUID
    model_id: uuid.UUID | None = None
    start_date: str  # ISO date
    end_date: str
    initial_capital: float = 10000.0
    maker_fee: float = 0.0025
    taker_fee: float = 0.004
    slippage_bps: float = 2.0


@router.post("")
async def run_backtest(
    body: BacktestRequest,
    _user: User = Depends(get_current_user),
):
    """Queue a backtest job."""
    import arq
    from app.config import get_settings
    settings = get_settings()
    pool = await arq.create_pool(arq.connections.RedisSettings.from_dsn(settings.redis_url))
    job = await pool.enqueue_job("run_backtest", config=body.model_dump(mode="json"))
    await pool.aclose()
    return {"job_id": job.job_id, "status": "queued"}


@router.get("")
async def list_backtests(
    strategy_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = select(BacktestResult).order_by(BacktestResult.created_at.desc()).limit(50)
    if strategy_id:
        q = q.where(BacktestResult.strategy_id == strategy_id)
    result = await db.execute(q)
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "strategy_id": str(r.strategy_id),
            "metrics": r.metrics,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{backtest_id}")
async def get_backtest(
    backtest_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BacktestResult).where(BacktestResult.id == backtest_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return {
        "id": str(row.id),
        "strategy_id": str(row.strategy_id),
        "config": row.config,
        "metrics": row.metrics,
        "equity_curve": row.equity_curve,
        "trade_log": row.trade_log,
        "created_at": row.created_at.isoformat(),
    }
