"""Pre-trade risk gate. Every order MUST pass through check() before execution."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.ml.strategy import Signal

log = structlog.get_logger(__name__)


@dataclass
class RiskLimits:
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    max_position_notional_pct: float = 1.0
    max_open_orders: int = 5
    max_order_rate_per_min: int = 30
    symbol_whitelist: list[str] = field(default_factory=lambda: ["BTC/GBP", "BTC/USDT"])
    leverage_limit: float = 1.0


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""
    adjusted_qty: float | None = None


class RiskGate:
    """Pre-trade risk gate. No order reaches the exchange without passing here."""

    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits
        self._trading_enabled: bool = True
        self._halt_reason: str = ""
        self._start_of_day_equity: float | None = None
        self._peak_equity: float = 0.0
        self._daily_pnl: float = 0.0
        self._order_timestamps: deque[float] = deque()

    def check(
        self,
        signal: "Signal",
        portfolio_equity: float,
        open_orders_count: int,
        current_position_notional: float,
        symbol: str,
    ) -> RiskCheckResult:
        """Run all pre-trade checks in order. First failure blocks the order."""
        now = datetime.now(timezone.utc).timestamp()

        # 1. Trading enabled flag
        if not self._trading_enabled:
            return RiskCheckResult(False, f"Trading halted: {self._halt_reason}")

        # 2. Symbol whitelist
        if symbol not in self.limits.symbol_whitelist:
            return RiskCheckResult(False, f"Symbol {symbol} not in whitelist")

        # 3. Max daily loss
        if self._start_of_day_equity is not None:
            daily_loss_pct = self._daily_pnl / self._start_of_day_equity
            if daily_loss_pct < -self.limits.max_daily_loss_pct:
                self.halt(f"Max daily loss exceeded: {daily_loss_pct:.2%}")
                return RiskCheckResult(False, f"Max daily loss: {daily_loss_pct:.2%}")

        # 4. Max drawdown from peak
        if self._peak_equity > 0:
            dd = (portfolio_equity - self._peak_equity) / self._peak_equity
            if dd < -self.limits.max_drawdown_pct:
                self.halt(f"Max drawdown exceeded: {dd:.2%}")
                return RiskCheckResult(False, f"Max drawdown: {dd:.2%}")

        # 5. Max position notional
        max_notional = portfolio_equity * self.limits.max_position_notional_pct
        if current_position_notional + abs(signal.target_weight) * portfolio_equity > max_notional:
            return RiskCheckResult(False, "Max position notional exceeded")

        # 6. Max open orders
        if open_orders_count >= self.limits.max_open_orders:
            return RiskCheckResult(False, f"Max open orders ({self.limits.max_open_orders}) reached")

        # 7. Order rate limit (rolling 60s window)
        cutoff = now - 60.0
        while self._order_timestamps and self._order_timestamps[0] < cutoff:
            self._order_timestamps.popleft()
        if len(self._order_timestamps) >= self.limits.max_order_rate_per_min:
            return RiskCheckResult(False, "Order rate limit reached")

        # 8. Leverage check (no leverage – position <= equity)
        if abs(signal.target_weight) > self.limits.leverage_limit:
            return RiskCheckResult(False, "Leverage limit exceeded")

        # All checks passed
        self._order_timestamps.append(now)
        log.info(
            "risk_gate_approved",
            symbol=symbol,
            weight=signal.target_weight,
            equity=portfolio_equity,
        )
        return RiskCheckResult(True)

    def update_equity(self, equity: float) -> None:
        if self._start_of_day_equity is None:
            self._start_of_day_equity = equity
        self._daily_pnl = equity - (self._start_of_day_equity or equity)
        self._peak_equity = max(self._peak_equity, equity)

    def reset_daily(self) -> None:
        self._start_of_day_equity = None
        self._daily_pnl = 0.0
        log.info("risk_gate_daily_reset")

    def halt(self, reason: str) -> None:
        self._trading_enabled = False
        self._halt_reason = reason
        log.error("risk_gate_halt", reason=reason)

    def enable(self) -> None:
        self._trading_enabled = True
        self._halt_reason = ""
        log.info("risk_gate_enabled")

    @property
    def trading_enabled(self) -> bool:
        return self._trading_enabled
