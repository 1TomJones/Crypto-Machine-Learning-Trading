"""Backtest router."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import BacktestResult, OHLCVBar, User

router = APIRouter()


class BacktestRequest(BaseModel):
    strategy_id: uuid.UUID
    model_id: uuid.UUID | None = None
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    start_date: str  # ISO date e.g. "2023-01-01"
    end_date: str
    initial_capital: float = 10000.0
    maker_fee: float = 0.0025
    taker_fee: float = 0.004


@router.post("")
async def run_backtest(
    body: BacktestRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Run a simple buy-and-hold backtest synchronously using stored OHLCV data."""
    start_dt = datetime.fromisoformat(body.start_date).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(body.end_date).replace(tzinfo=timezone.utc)

    q = (
        select(OHLCVBar)
        .where(
            OHLCVBar.symbol == body.symbol,
            OHLCVBar.exchange == "binance",
            OHLCVBar.ts >= start_dt,
            OHLCVBar.ts <= end_dt,
        )
        .order_by(OHLCVBar.ts)
        .limit(10000)
    )
    result = await db.execute(q)
    bars = result.scalars().all()

    config = body.model_dump(mode="json")

    if not bars:
        metrics: dict = {}
        equity_curve: list = []
        trade_log: list = []
    else:
        capital = body.initial_capital
        initial_price = bars[0].close
        equity_curve = []
        for bar in bars:
            eq = capital * (bar.close / initial_price)
            equity_curve.append({"ts": bar.ts.isoformat(), "equity": round(eq, 2)})

        returns = [
            (equity_curve[i]["equity"] / equity_curve[i - 1]["equity"]) - 1
            for i in range(1, len(equity_curve))
        ]
        avg_ret = sum(returns) / len(returns) if returns else 0
        std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 0
        annualise = {"1m": 525600, "5m": 105120, "15m": 35040, "1h": 8760, "4h": 2190, "1d": 365}
        ann_factor = annualise.get(body.timeframe, 8760) ** 0.5
        sharpe = (avg_ret / std_ret) * ann_factor if std_ret > 0 else 0

        max_eq = capital
        max_dd = 0.0
        for pt in equity_curve:
            max_eq = max(max_eq, pt["equity"])
            dd = (max_eq - pt["equity"]) / max_eq if max_eq > 0 else 0
            max_dd = max(max_dd, dd)

        final_eq = equity_curve[-1]["equity"]
        n_days = max((end_dt - start_dt).days, 1)
        cagr = (final_eq / capital) ** (365 / n_days) - 1

        metrics = {
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(max_dd, 4),
            "cagr": round(cagr, 4),
            "win_rate": 1.0 if final_eq > capital else 0.0,
            "n_trades": 1,
        }
        trade_log = [
            {"side": "buy", "ts": bars[0].ts.isoformat(), "price": bars[0].close, "qty": capital / bars[0].close},
            {"side": "sell", "ts": bars[-1].ts.isoformat(), "price": bars[-1].close, "qty": capital / bars[0].close},
        ]

    record = BacktestResult(
        strategy_id=body.strategy_id,
        model_id=body.model_id,
        config=config,
        metrics=metrics,
        equity_curve=equity_curve,
        trade_log=trade_log,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return {"backtest_id": str(record.id)}


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
            "config": r.config,
            "metrics": r.metrics,
            "status": "completed",
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
        "status": "completed",
        "created_at": row.created_at.isoformat(),
    }
