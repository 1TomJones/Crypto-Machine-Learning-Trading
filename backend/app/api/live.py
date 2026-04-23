"""Live trading control router."""
from __future__ import annotations

import orjson
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.db_models import Order, Position, User

router = APIRouter()


class StartCommand(BaseModel):
    strategy_id: str


@router.get("/status")
async def live_status(request: Request, _user: User = Depends(get_current_user)):
    import time
    redis: aioredis.Redis = request.app.state.redis
    raw = await redis.get("trader:heartbeat")
    if raw is None:
        return {"running": False, "trading_enabled": False, "equity": 0.0, "strategies_active": 0}
    data = orjson.loads(raw)
    age_s = time.time() - data.get("ts", 0)
    return {
        "running": age_s < 30,
        "trading_enabled": data.get("trading_enabled", False),
        "equity": data.get("equity", 0.0),
        "strategies_active": data.get("strategies_active", 0),
        "age_seconds": age_s,
    }


@router.post("/start")
async def start_strategy(
    body: StartCommand,
    request: Request,
    _user: User = Depends(get_current_user),
):
    redis: aioredis.Redis = request.app.state.redis
    await redis.publish(
        "trader:cmd",
        orjson.dumps({"cmd": "start_strategy", "strategy_id": body.strategy_id}).decode(),
    )
    return {"message": "start command sent", "strategy_id": body.strategy_id}


@router.post("/stop")
async def stop_strategy(
    body: StartCommand,
    request: Request,
    _user: User = Depends(get_current_user),
):
    redis: aioredis.Redis = request.app.state.redis
    await redis.publish(
        "trader:cmd",
        orjson.dumps({"cmd": "stop_strategy", "strategy_id": body.strategy_id}).decode(),
    )
    return {"message": "stop command sent"}


@router.post("/kill")
async def kill_switch(request: Request, _user: User = Depends(get_current_user)):
    """Trigger the kill switch via Redis command channel."""
    redis: aioredis.Redis = request.app.state.redis
    await redis.publish(
        "trader:cmd",
        orjson.dumps({"cmd": "kill_switch", "reason": "manual_ui_trigger"}).decode(),
    )
    return {"message": "kill switch triggered"}


@router.get("/positions")
async def get_positions(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(select(Position))
    positions = result.scalars().all()
    return [
        {
            "symbol": p.symbol,
            "exchange": p.exchange,
            "qty": str(p.qty),
            "avg_entry_price": str(p.avg_entry_price),
            "unrealized_pnl": str(p.unrealized_pnl),
            "realized_pnl": str(p.realized_pnl),
        }
        for p in positions
    ]


@router.get("/orders")
async def get_orders(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).order_by(Order.created_at.desc()).limit(limit)
    )
    orders = result.scalars().all()
    return [
        {
            "id": str(o.id),
            "client_order_id": o.client_order_id,
            "symbol": o.symbol,
            "side": o.side,
            "order_type": o.order_type,
            "qty": str(o.qty),
            "status": o.status,
            "fee": str(o.fee),
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]
