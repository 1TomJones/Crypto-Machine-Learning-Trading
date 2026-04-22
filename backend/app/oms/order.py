"""Order state machine and domain model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrderStatus(str, Enum):
    PENDING   = "pending"    # created locally, not yet sent
    OPEN      = "open"       # acknowledged by exchange
    PARTIAL   = "partial"    # partially filled
    FILLED    = "filled"     # fully filled
    CANCELLED = "cancelled"
    REJECTED  = "rejected"
    EXPIRED   = "expired"


class OrderSide(str, Enum):
    BUY  = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT  = "limit"


# Valid state transitions
_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING:   {OrderStatus.OPEN, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.OPEN:      {OrderStatus.PARTIAL, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED},
    OrderStatus.PARTIAL:   {OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.FILLED:    set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED:  set(),
    OrderStatus.EXPIRED:   set(),
}


class Order:
    """Mutable order with validated state transitions."""

    def __init__(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        qty: float,
        price: float | None = None,
        reduce_only: bool = False,
        strategy_id: str | None = None,
    ) -> None:
        self.client_order_id: str = str(uuid.uuid4())
        self.exchange_order_id: str | None = None
        self.symbol = symbol
        self.side = side
        self.order_type = order_type
        self.qty = qty
        self.filled_qty: float = 0.0
        self.avg_fill_price: float | None = None
        self.price = price
        self.reduce_only = reduce_only
        self.strategy_id = strategy_id
        self.status = OrderStatus.PENDING
        self.created_at: datetime = datetime.now(timezone.utc)
        self.updated_at: datetime = self.created_at
        self.raw_exchange_data: dict[str, Any] = {}

    # ------------------------------------------------------------------

    def transition(self, new_status: OrderStatus) -> None:
        allowed = _TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid transition {self.status} → {new_status} for order {self.client_order_id}"
            )
        self.status = new_status
        self.updated_at = datetime.now(timezone.utc)

    def apply_fill(self, filled_qty: float, avg_price: float) -> None:
        self.filled_qty = filled_qty
        self.avg_fill_price = avg_price
        self.updated_at = datetime.now(timezone.utc)
        if abs(self.filled_qty - self.qty) < 1e-12:
            self.transition(OrderStatus.FILLED)
        elif self.filled_qty > 0:
            if self.status == OrderStatus.OPEN:
                self.transition(OrderStatus.PARTIAL)

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }

    def to_dict(self) -> dict:
        return {
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "qty": self.qty,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "price": self.price,
            "reduce_only": self.reduce_only,
            "strategy_id": self.strategy_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
