"""Kill switch: cancel all orders → flatten all positions → halt trading → alert."""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


class KillSwitch:
    """One command triggers the full kill sequence.

    Triggerable by:
    - CLI: python -m app.risk.kill_switch trigger "reason"
    - Telegram: /kill command
    - Automatic: reconciliation break, NaN model output, stale data feed, API 4xx loop
    """

    def __init__(self, exchange, alerter, state_store, redis_client) -> None:
        self.exchange = exchange
        self.alerter = alerter
        self.state = state_store
        self.redis = redis_client

    async def trigger(self, reason: str) -> None:
        """Execute full kill sequence."""
        log.critical("kill_switch_triggered", reason=reason)

        # 1. Disable trading
        self.state["trading_enabled"] = False
        await self._persist_state()

        # 2. Alert immediately
        await self.alerter.critical(f"KILL SWITCH: {reason}")

        # 3. Cancel all open orders
        await self._cancel_all_orders()

        # 4. Flatten all positions
        try:
            positions = await asyncio.wait_for(
                asyncio.coroutine(self.exchange.fetch_positions)()
                if asyncio.iscoroutinefunction(self.exchange.fetch_positions)
                else asyncio.coroutine(lambda: {})(),
                timeout=10.0,
            )
            for sym, pos in (positions or {}).items():
                qty = float(pos.get("qty", 0))
                if abs(qty) < 1e-12:
                    continue
                await self._flatten_position(sym, qty)
        except Exception as exc:
            log.error("kill_fetch_positions_error", error=str(exc))
            await self.alerter.critical(f"Failed to fetch positions during kill: {exc}")

        await self._persist_state()
        await self.alerter.critical("KILL COMPLETE — MANUAL RESTART REQUIRED")

    async def _cancel_all_orders(self) -> None:
        try:
            if asyncio.iscoroutinefunction(getattr(self.exchange, "cancel_all_orders", None)):
                await asyncio.wait_for(self.exchange.cancel_all_orders(), timeout=10.0)
            log.info("kill_all_orders_cancelled")
        except Exception as exc:
            log.error("kill_cancel_all_error", error=str(exc))
            await self.alerter.critical(f"cancel_all_orders error: {exc}")

    async def _flatten_position(self, symbol: str, qty: float) -> bool:
        side = "sell" if qty > 0 else "buy"
        client_id = f"kill-{symbol}-{uuid.uuid4()}"
        for attempt in range(3):
            try:
                if asyncio.iscoroutinefunction(getattr(self.exchange, "create_order", None)):
                    await self.exchange.create_order(
                        symbol, "market", side, abs(qty),
                        params={"clientOrderId": client_id, "reduceOnly": True},
                    )
                log.info("kill_position_flattened", symbol=symbol, qty=qty, attempt=attempt)
                return True
            except Exception as exc:
                log.error("kill_flatten_error", symbol=symbol, attempt=attempt, error=str(exc))
                await self.alerter.critical(f"flatten {symbol} attempt {attempt}: {exc}")
                await asyncio.sleep(2 ** attempt)
        return False

    async def _persist_state(self) -> None:
        try:
            import orjson
            await self.redis.set(
                "trader:state",
                orjson.dumps(self.state).decode(),
                ex=86400,
            )
        except Exception as exc:
            log.error("kill_persist_error", error=str(exc))
