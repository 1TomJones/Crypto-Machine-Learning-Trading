"""Risk settings and metrics router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import Position, RiskSettings, User

router = APIRouter()


class RiskSettingsUpdate(BaseModel):
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_position_notional_pct: float | None = None
    max_open_orders: int | None = None
    max_order_rate_per_min: int | None = None
    symbol_whitelist: list[str] | None = None
    leverage_limit: float | None = None


@router.get("/settings")
async def get_risk_settings(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(RiskSettings).where(RiskSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        # Create default row
        settings = RiskSettings(id=1)
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


@router.patch("/settings")
async def update_risk_settings(
    body: RiskSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(RiskSettings).where(RiskSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = RiskSettings(id=1)
        db.add(settings)

    for field, val in body.model_dump(exclude_none=True).items():
        setattr(settings, field, val)
    await db.flush()
    await db.refresh(settings)
    return settings


@router.get("/metrics")
async def risk_metrics(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    positions_result = await db.execute(select(Position))
    positions = positions_result.scalars().all()
    total_notional = sum(float(p.avg_entry_price) * abs(float(p.qty)) for p in positions)
    total_unrealized = sum(float(p.unrealized_pnl) for p in positions)
    total_realized = sum(float(p.realized_pnl) for p in positions)
    return {
        "var_95": None,
        "es_95": None,
        "current_drawdown": 0.0,
        "daily_pnl": total_realized if positions else None,
        "total_position_notional": total_notional,
        "total_unrealized_pnl": total_unrealized,
        "open_positions": len(positions),
    }
