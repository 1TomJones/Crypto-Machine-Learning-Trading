"""Unit tests for risk metrics."""
import pytest
import numpy as np
from app.risk.metrics import var_historical, expected_shortfall, kupiec_test


def test_var_positive_loss():
    returns = np.random.default_rng(42).normal(-0.01, 0.02, 500).tolist()
    v = var_historical(returns, confidence=0.95)
    assert v > 0


def test_es_ge_var():
    returns = np.random.default_rng(0).normal(0, 0.015, 500).tolist()
    v = var_historical(returns)
    es = expected_shortfall(returns)
    assert es >= v


def test_kupiec_empty():
    result = kupiec_test([], confidence=0.95)
    assert "error" in result


def test_kupiec_passes_on_correct_model():
    rng = np.random.default_rng(1)
    # Generate returns where ~5% fall below VaR
    returns = rng.normal(0, 0.01, 1000).tolist()
    result = kupiec_test(returns, confidence=0.95)
    assert "passed" in result
    assert result["n_observations"] == 1000
