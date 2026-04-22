"""Event-driven bar-by-bar backtester with realistic fees and slippage."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from app.ml.metrics import full_metrics
from app.ml.strategy import BaseStrategy, Signal


@dataclass
class BacktestConfig:
    strategy_id: str
    symbol: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    initial_capital: float = 10_000.0
    maker_fee: float = 0.0025   # Kraken 0.25%
    taker_fee: float = 0.004    # Kraken 0.40%
    slippage_bps: float = 2.0   # 2 basis points
    use_limit_orders: bool = False
    atr_stop_mult: float = 2.0  # ATR-based stop loss multiplier


@dataclass
class BacktestTrade:
    entry_ts: datetime
    exit_ts: datetime
    side: str           # "long" | "short"
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    fee: float
    slippage: float
    exit_reason: str    # "signal" | "stop_loss" | "take_profit" | "time_stop"


class BacktestEngine:
    """Processes bars in strict time order. Strategy only sees t-1 data."""

    def __init__(
        self,
        config: BacktestConfig,
        strategy: BaseStrategy,
        features: pd.DataFrame,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.features = features

        # Portfolio state
        self.equity = config.initial_capital
        self.cash = config.initial_capital
        self.position = 0.0         # current BTC qty (negative = short)
        self.entry_price = 0.0
        self.entry_ts: datetime | None = None
        self.equity_curve: list[dict] = []
        self.trades: list[BacktestTrade] = []
        self._peak_equity = config.initial_capital

    def run(self, ohlcv: pd.DataFrame) -> dict:
        """Run backtest. Returns metrics dict + equity curve + trades."""
        mask = (ohlcv.index >= pd.Timestamp(self.config.start_date)) & \
               (ohlcv.index <= pd.Timestamp(self.config.end_date))
        ohlcv = ohlcv.loc[mask]

        if ohlcv.empty:
            return {"error": "No data in date range"}

        for i, (ts, bar) in enumerate(ohlcv.iterrows()):
            # Update unrealized P&L for current position
            close = float(bar["close"])
            self._update_equity(ts, close)

            # Get features up to bar i (already shifted -1 in pipeline)
            feat_slice = self.features.loc[:ts]
            if feat_slice.empty or feat_slice.isna().all(axis=None):
                continue

            # Generate signal
            try:
                signal: Signal = self.strategy.predict(feat_slice)
            except Exception:
                continue

            if signal is None or np.isnan(signal.target_weight):
                continue

            # Execute signal at next bar open (i+1) to avoid lookahead
            if i + 1 < len(ohlcv):
                next_bar = ohlcv.iloc[i + 1]
                self._execute(signal, next_bar, ts)

        return self.get_results()

    def _execute(self, signal: Signal, bar: pd.Series, signal_ts: datetime) -> None:
        """Execute a signal at the open of the next bar."""
        exec_price = float(bar["open"])
        new_position_sign = np.sign(signal.target_weight)
        new_position_sign = int(new_position_sign)

        current_sign = int(np.sign(self.position))
        if new_position_sign == current_sign:
            return  # No change needed

        # Close existing position
        if self.position != 0:
            self._close_position(exec_price, bar.name, "signal")

        # Open new position
        if new_position_sign != 0:
            self._open_position(new_position_sign, exec_price, bar.name)

    def _open_position(self, side: int, price: float, ts: datetime) -> None:
        """Open a new position. side=+1 long, -1 short."""
        slippage_mult = 1 + self.config.slippage_bps / 10_000 * side
        exec_price, fee = self._apply_fee_slippage(price, slippage_mult)

        # Size: 100% of cash for simplicity (no leverage)
        notional = self.cash
        qty = notional / exec_price
        cost = notional + fee

        if cost > self.cash:
            return  # Insufficient funds

        self.cash -= cost
        self.position = qty * side
        self.entry_price = exec_price
        self.entry_ts = ts

    def _close_position(self, price: float, ts: datetime, reason: str) -> None:
        """Close the current position and record the trade."""
        if self.position == 0:
            return

        side = int(np.sign(self.position))
        slippage_mult = 1 - self.config.slippage_bps / 10_000 * side
        exec_price, fee = self._apply_fee_slippage(price, slippage_mult)

        qty = abs(self.position)
        notional = qty * exec_price
        proceeds = notional - fee

        pnl = (exec_price - self.entry_price) * side * qty - fee
        slippage_cost = abs(exec_price - price) * qty

        self.trades.append(BacktestTrade(
            entry_ts=self.entry_ts or ts,
            exit_ts=ts,
            side="long" if side > 0 else "short",
            entry_price=self.entry_price,
            exit_price=exec_price,
            qty=qty,
            pnl=pnl,
            fee=fee,
            slippage=slippage_cost,
            exit_reason=reason,
        ))

        self.cash += proceeds
        self.position = 0.0
        self.entry_price = 0.0

    def _apply_fee_slippage(
        self, price: float, slippage_mult: float = 1.0
    ) -> tuple[float, float]:
        """Returns (execution_price_after_slippage, fee)."""
        exec_price = price * slippage_mult
        fee_rate = self.config.maker_fee if self.config.use_limit_orders else self.config.taker_fee
        notional = abs(self.position) * exec_price if self.position != 0 else self.cash
        fee = notional * fee_rate
        return exec_price, fee

    def _update_equity(self, ts: datetime, close: float) -> None:
        """Recompute equity and record in curve."""
        unrealized = 0.0
        if self.position != 0 and self.entry_price > 0:
            unrealized = (close - self.entry_price) * self.position

        self.equity = self.cash + abs(self.position) * close + unrealized - abs(
            self.position * close * self.config.taker_fee
        ) * (1 if self.position != 0 else 0)
        self.equity = max(self.equity, 0.01)  # floor at 1 cent

        self._peak_equity = max(self._peak_equity, self.equity)
        drawdown = (self.equity - self._peak_equity) / self._peak_equity

        self.equity_curve.append({
            "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            "equity": round(self.equity, 4),
            "drawdown": round(drawdown, 6),
            "position": round(self.position, 8),
            "cash": round(self.cash, 4),
        })

    def get_results(self) -> dict:
        """Compute full metrics and return results dict."""
        if not self.equity_curve:
            return {"error": "No equity curve"}

        eq = pd.Series([p["equity"] for p in self.equity_curve])
        ret = eq.pct_change().dropna()

        trade_pnl = [t.pnl for t in self.trades]
        wins = [p for p in trade_pnl if p > 0]
        losses = [p for p in trade_pnl if p <= 0]

        metrics = full_metrics(
            equity_curve=eq,
            trades_pnl=trade_pnl,
            n_trials=1,
        )
        metrics.update({
            "n_trades": len(self.trades),
            "win_rate": len(wins) / max(len(self.trades), 1),
            "avg_win": float(np.mean(wins)) if wins else 0.0,
            "avg_loss": float(np.mean(losses)) if losses else 0.0,
            "profit_factor": sum(wins) / max(abs(sum(losses)), 1e-10),
            "total_fees": sum(t.fee for t in self.trades),
            "total_slippage": sum(t.slippage for t in self.trades),
            "final_equity": self.equity,
        })

        return {
            "equity_curve": self.equity_curve,
            "metrics": metrics,
            "trade_log": [
                {
                    "entry_ts": t.entry_ts.isoformat() if hasattr(t.entry_ts, "isoformat") else str(t.entry_ts),
                    "exit_ts": t.exit_ts.isoformat() if hasattr(t.exit_ts, "isoformat") else str(t.exit_ts),
                    "side": t.side,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "qty": t.qty,
                    "pnl": round(t.pnl, 4),
                    "fee": round(t.fee, 4),
                    "exit_reason": t.exit_reason,
                }
                for t in self.trades
            ],
        }
