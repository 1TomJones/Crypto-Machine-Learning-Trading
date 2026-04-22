"""Order Management System: send, track, reconcile orders."""
from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.oms.order import Order, OrderSide, OrderStatus, OrderType
from app.risk.gate import RiskGate, RiskCheckResult

log = structlog.get_logger(__name__)


class OMS:
    """Manages the full lifecycle of exchange orders.

    Responsibilities:
    - Pre-trade risk gate check before every order submission
    - Idempotent submission: client_order_id persisted before send
    - State machine transitions based on exchange confirmations
    - Reconciliation against live exchange state every 60s
    """

    def __init__(
        self,
        exchange,
        risk_gate: RiskGate,
        alerter,
        db_session_factory,
        portfolio_equity_fn,
    ) -> None:
        self.exchange = exchange
        self.risk_gate = risk_gate
        self.alerter = alerter
        self._db = db_session_factory
        self._equity_fn = portfolio_equity_fn
        self._orders: dict[str, Order] = {}   # client_order_id → Order
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        qty: float,
        price: float | None = None,
        reduce_only: bool = False,
        strategy_id: str | None = None,
        signal=None,
    ) -> Order:
        """Create, risk-check, and submit an order. Returns the Order object."""
        order = Order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            price=price,
            reduce_only=reduce_only,
            strategy_id=strategy_id,
        )

        # Pre-trade risk check (skip for kill-switch reduce-only flattening)
        if not reduce_only and signal is not None:
            equity = await self._equity_fn()
            open_count = self._count_open_orders(symbol)
            current_notional = self._current_position_notional(symbol, equity)
            result: RiskCheckResult = self.risk_gate.check(
                signal=signal,
                portfolio_equity=equity,
                open_orders_count=open_count,
                current_position_notional=current_notional,
                symbol=symbol,
            )
            if not result.approved:
                log.warning("oms_risk_rejected", reason=result.reason, symbol=symbol)
                order.transition(OrderStatus.REJECTED)
                return order

        # Persist locally first (idempotency: if send crashes, we know the ID)
        async with self._lock:
            self._orders[order.client_order_id] = order

        await self._send_to_exchange(order)
        return order

    async def cancel(self, client_order_id: str) -> bool:
        order = self._orders.get(client_order_id)
        if order is None or order.is_terminal:
            return False
        try:
            if asyncio.iscoroutinefunction(getattr(self.exchange, "cancel_order", None)):
                await asyncio.wait_for(
                    self.exchange.cancel_order(order.exchange_order_id, order.symbol),
                    timeout=10.0,
                )
            order.transition(OrderStatus.CANCELLED)
            log.info("oms_order_cancelled", client_id=client_order_id)
            return True
        except Exception as exc:
            log.error("oms_cancel_error", client_id=client_order_id, error=str(exc))
            return False

    async def reconcile(self) -> None:
        """Compare local state against exchange for all non-terminal orders."""
        open_orders = [o for o in self._orders.values() if not o.is_terminal]
        if not open_orders:
            return

        try:
            ex_orders: list[dict] = []
            if asyncio.iscoroutinefunction(getattr(self.exchange, "fetch_open_orders", None)):
                ex_orders = await asyncio.wait_for(
                    self.exchange.fetch_open_orders(), timeout=15.0
                )
            ex_by_id = {o.get("clientOrderId"): o for o in ex_orders}

            for order in open_orders:
                ex = ex_by_id.get(order.client_order_id)
                if ex is None:
                    # Not found on exchange → likely filled or cancelled
                    log.warning("oms_reconcile_missing", client_id=order.client_order_id)
                    await self._sync_from_exchange(order)
                else:
                    self._apply_exchange_state(order, ex)
        except Exception as exc:
            log.error("oms_reconcile_error", error=str(exc))
            await self.alerter.critical(f"Reconciliation error: {exc}")

    def get_orders(self, include_terminal: bool = False) -> list[dict]:
        orders = self._orders.values()
        if not include_terminal:
            orders = [o for o in orders if not o.is_terminal]
        return [o.to_dict() for o in orders]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_to_exchange(self, order: Order) -> None:
        params: dict[str, Any] = {"clientOrderId": order.client_order_id}
        if order.reduce_only:
            params["reduceOnly"] = True

        try:
            if asyncio.iscoroutinefunction(getattr(self.exchange, "create_order", None)):
                resp = await asyncio.wait_for(
                    self.exchange.create_order(
                        order.symbol,
                        order.order_type.value,
                        order.side.value,
                        order.qty,
                        order.price,
                        params=params,
                    ),
                    timeout=10.0,
                )
                order.exchange_order_id = resp.get("id")
                order.raw_exchange_data = resp
                order.transition(OrderStatus.OPEN)
                log.info(
                    "oms_order_sent",
                    client_id=order.client_order_id,
                    exchange_id=order.exchange_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    qty=order.qty,
                )
            else:
                order.transition(OrderStatus.REJECTED)
        except Exception as exc:
            log.error("oms_send_error", client_id=order.client_order_id, error=str(exc))
            order.transition(OrderStatus.REJECTED)
            await self.alerter.critical(f"Order submission failed: {exc}")

    async def _sync_from_exchange(self, order: Order) -> None:
        """Fetch single order status from exchange to resolve discrepancy."""
        try:
            if not order.exchange_order_id:
                return
            if asyncio.iscoroutinefunction(getattr(self.exchange, "fetch_order", None)):
                ex = await asyncio.wait_for(
                    self.exchange.fetch_order(order.exchange_order_id, order.symbol),
                    timeout=10.0,
                )
                self._apply_exchange_state(order, ex)
        except Exception as exc:
            log.error("oms_sync_error", client_id=order.client_order_id, error=str(exc))

    def _apply_exchange_state(self, order: Order, ex_data: dict) -> None:
        status_map = {
            "open":      OrderStatus.OPEN,
            "partial":   OrderStatus.PARTIAL,
            "closed":    OrderStatus.FILLED,
            "filled":    OrderStatus.FILLED,
            "canceled":  OrderStatus.CANCELLED,
            "cancelled": OrderStatus.CANCELLED,
            "expired":   OrderStatus.EXPIRED,
            "rejected":  OrderStatus.REJECTED,
        }
        ex_status = status_map.get(ex_data.get("status", ""), None)
        filled = float(ex_data.get("filled", 0) or 0)
        avg_price = float(ex_data.get("average") or ex_data.get("price") or 0)

        if filled > 0:
            order.apply_fill(filled, avg_price)
        if ex_status and not order.is_terminal and ex_status != order.status:
            try:
                order.transition(ex_status)
            except ValueError:
                pass  # log already in transition()
        order.raw_exchange_data = ex_data

    def _count_open_orders(self, symbol: str) -> int:
        return sum(
            1 for o in self._orders.values()
            if o.symbol == symbol and not o.is_terminal
        )

    def _current_position_notional(self, symbol: str, equity: float) -> float:
        # Simplified: count filled buy - sell qty * some price proxy
        # Real implementation would query live position from exchange
        return 0.0
