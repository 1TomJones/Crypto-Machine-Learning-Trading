"""Fractional differentiation (López de Prado AFML Ch.5).

Fixed-width window (FFD) variant preserves maximum memory while achieving
stationarity.  Use find_min_d() to select the minimum d that passes ADF.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def frac_weights(d: float, thresh: float = 1e-4) -> np.ndarray:
    """Compute FFD binomial series weights for fractional order d."""
    w = [1.0]
    k = 1
    while True:
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < thresh:
            break
        w.append(w_k)
        k += 1
    return np.array(w[::-1])


def frac_diff_ffd(s: pd.Series, d: float, thresh: float = 1e-4) -> pd.Series:
    """Fixed-width window fractional differentiation."""
    w = frac_weights(d, thresh)
    width = len(w) - 1
    out = np.full(len(s), np.nan)
    v = s.values
    for i in range(width, len(s)):
        out[i] = np.dot(w, v[i - width: i + 1])
    return pd.Series(out, index=s.index, name=f"fd_{s.name or 'price'}_{d:.2f}")


def find_min_d(
    s: pd.Series,
    thresh: float = 1e-4,
    d_start: float = 0.0,
    d_end: float = 1.0,
    step: float = 0.01,
    adf_threshold: float = 0.05,
) -> float:
    """Find minimum d such that ADF test rejects unit root at adf_threshold significance.

    Returns d* ≈ 0.15–0.4 for most price series per López de Prado.
    Falls back to 1.0 (full differencing) if no d found.
    """
    try:
        from statsmodels.tsa.stattools import adfuller
    except ImportError:
        return 0.35  # default if statsmodels not available

    d = d_start
    while d <= d_end:
        fd = frac_diff_ffd(s, d, thresh).dropna()
        if len(fd) < 20:
            d += step
            continue
        result = adfuller(fd, maxlag=1, regression="c", autolag=None)
        p_value = result[1]
        if p_value <= adf_threshold:
            return round(d, 4)
        d = round(d + step, 4)
    return 1.0
