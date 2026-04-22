"""Unit tests for RiskGate."""
import pytest
from app.risk.gate import RiskGate, RiskLimits
from app.ml.strategy import Signal


def make_signal(weight: float = 0.5) -> Signal:
    return Signal(target_weight=weight, confidence=0.8, strategy_id="test")


def test_risk_gate_approves_valid_order():
    gate = RiskGate(RiskLimits())
    gate.update_equity(10_000.0)
    result = gate.check(make_signal(), 10_000.0, 0, 0.0, "BTC/USDT")
    assert result.approved


def test_risk_gate_rejects_unknown_symbol():
    gate = RiskGate(RiskLimits(symbol_whitelist=["BTC/USDT"]))
    gate.update_equity(10_000.0)
    result = gate.check(make_signal(), 10_000.0, 0, 0.0, "ETH/USDT")
    assert not result.approved
    assert "whitelist" in result.reason


def test_risk_gate_halts_on_max_drawdown():
    gate = RiskGate(RiskLimits(max_drawdown_pct=0.10))
    gate.update_equity(10_000.0)   # peak = 10_000
    gate.update_equity(8_900.0)    # drawdown = -11% > limit
    result = gate.check(make_signal(), 8_900.0, 0, 0.0, "BTC/USDT")
    assert not result.approved
    assert not gate.trading_enabled


def test_risk_gate_rejects_leverage():
    gate = RiskGate(RiskLimits(leverage_limit=1.0))
    gate.update_equity(10_000.0)
    result = gate.check(make_signal(weight=1.5), 10_000.0, 0, 0.0, "BTC/USDT")
    assert not result.approved
    assert "leverage" in result.reason.lower()


def test_risk_gate_rate_limit():
    gate = RiskGate(RiskLimits(max_order_rate_per_min=2))
    gate.update_equity(10_000.0)
    gate.check(make_signal(0.1), 10_000.0, 0, 0.0, "BTC/USDT")
    gate.check(make_signal(0.1), 10_000.0, 0, 0.0, "BTC/USDT")
    result = gate.check(make_signal(0.1), 10_000.0, 0, 0.0, "BTC/USDT")
    assert not result.approved
    assert "rate" in result.reason.lower()
