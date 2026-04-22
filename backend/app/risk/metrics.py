"""Risk metrics: VaR, Expected Shortfall, Kupiec back-test."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from scipy import stats


def var_historical(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Historical VaR at `confidence` level (positive number = loss)."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    return float(-np.percentile(arr, (1 - confidence) * 100))


def expected_shortfall(returns: Sequence[float], confidence: float = 0.95) -> float:
    """Historical Expected Shortfall (CVaR) — mean of losses beyond VaR."""
    arr = np.asarray(returns, dtype=float)
    if len(arr) == 0:
        return 0.0
    cutoff = np.percentile(arr, (1 - confidence) * 100)
    tail = arr[arr <= cutoff]
    if len(tail) == 0:
        return float(-cutoff)
    return float(-tail.mean())


def kupiec_test(
    returns: Sequence[float],
    confidence: float = 0.95,
    var_estimate: float | None = None,
) -> dict:
    """Kupiec proportion-of-failures (POF) test for VaR model accuracy.

    Returns dict with: exceptions, expected_exceptions, pof_stat, p_value, passed.
    """
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    if n == 0:
        return {"error": "empty returns"}

    v = var_estimate if var_estimate is not None else var_historical(arr, confidence)
    p = 1.0 - confidence
    x = int(np.sum(arr < -v))          # observed exceptions (losses > VaR)

    expected = p * n
    if x == 0:
        # Avoid log(0); LR statistic → 0 if no exceptions and expected is small
        lr = 2.0 * (n * math.log(1 - p) - 0.0) if p < 1 else 0.0
    elif x == n:
        lr = 0.0
    else:
        hat_p = x / n
        lr = 2.0 * (
            x * math.log(hat_p / p) + (n - x) * math.log((1 - hat_p) / (1 - p))
        )

    p_value = float(1.0 - stats.chi2.cdf(lr, df=1))
    return {
        "n_observations": n,
        "confidence": confidence,
        "var_estimate": round(v, 6),
        "exceptions": x,
        "expected_exceptions": round(expected, 2),
        "pof_stat": round(lr, 4),
        "p_value": round(p_value, 4),
        "passed": p_value > 0.05,  # fail to reject H0 → model is adequate
    }
