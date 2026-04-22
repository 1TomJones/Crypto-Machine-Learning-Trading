"""Smoke tests for BacktestEngine."""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from app.backtest.engine import BacktestEngine, BacktestConfig
from app.ml.strategy import BaseStrategy, Signal


class AlwaysBuyStrategy(BaseStrategy):
    def predict(self, features: pd.DataFrame) -> Signal:
        return Signal(target_weight=1.0, confidence=1.0, strategy_id="always_buy")


class AlternatingStrategy(BaseStrategy):
    def __init__(self):
        self._n = 0

    def predict(self, features: pd.DataFrame) -> Signal:
        weight = 1.0 if self._n % 2 == 0 else -1.0
        self._n += 1
        return Signal(target_weight=weight, confidence=1.0, strategy_id="alt")


def make_ohlcv(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    prices = 30_000 + np.cumsum(rng.normal(0, 100, n))
    dates = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame({
        "open": prices,
        "high": prices * 1.001,
        "low": prices * 0.999,
        "close": prices,
        "volume": rng.uniform(1, 10, n),
    }, index=dates)
    return df


def make_config() -> BacktestConfig:
    return BacktestConfig(
        strategy_id="test",
        symbol="BTC/USDT",
        timeframe="1h",
        start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2023, 12, 31, tzinfo=timezone.utc),
        initial_capital=10_000.0,
    )


def test_backtest_runs_without_error():
    ohlcv = make_ohlcv(100)
    features = ohlcv.copy()  # trivial features
    engine = BacktestEngine(make_config(), AlwaysBuyStrategy(), features)
    results = engine.run(ohlcv)
    assert "metrics" in results
    assert "equity_curve" in results


def test_backtest_always_buy_has_trades():
    ohlcv = make_ohlcv(100)
    features = ohlcv.copy()
    engine = BacktestEngine(make_config(), AlwaysBuyStrategy(), features)
    results = engine.run(ohlcv)
    assert results["metrics"]["n_trades"] >= 1


def test_backtest_equity_floor():
    ohlcv = make_ohlcv(50)
    features = ohlcv.copy()
    engine = BacktestEngine(make_config(), AlternatingStrategy(), features)
    results = engine.run(ohlcv)
    equities = [p["equity"] for p in results["equity_curve"]]
    assert all(e >= 0.01 for e in equities)
