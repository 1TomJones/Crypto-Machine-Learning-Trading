"""Position sizing functions."""
from __future__ import annotations

import numpy as np
import pandas as pd


def fixed_fractional_size(
    equity: float, stop_distance: float, risk_pct: float = 0.01
) -> float:
    """Size = equity * risk_pct / stop_distance."""
    if stop_distance <= 0:
        return 0.0
    return equity * risk_pct / stop_distance


def volatility_target_weight(
    close: pd.Series,
    target_vol: float = 0.10,
    ewma_lambda: float = 0.94,
    annualization: float = 365 * 24,
) -> float:
    """Volatility targeting: weight = target_vol / realized_vol.

    Uses EWMA volatility with lambda=0.94, annualized for hourly crypto.
    Returns weight in [0, 1].
    """
    if len(close) < 2:
        return 0.0
    ret = np.log(close / close.shift(1)).dropna()
    if len(ret) == 0:
        return 0.0
    # EWMA variance
    ewma_var = ret.ewm(alpha=1 - ewma_lambda, adjust=False).var().iloc[-1]
    realized_vol = float(np.sqrt(ewma_var * annualization))
    if realized_vol <= 0:
        return 0.0
    weight = target_vol / realized_vol
    return float(np.clip(weight, 0.0, 1.0))


def kelly_fraction(
    win_prob: float,
    win_return: float,
    loss_return: float,
    fraction: float = 0.25,
) -> float:
    """Fractional Kelly criterion.

    full_kelly = (p * b - q) / b  where b = win/loss ratio, q = 1 - p
    Returns fraction * full_kelly, clipped to [0, 1].
    """
    if loss_return <= 0 or win_prob <= 0:
        return 0.0
    b = win_return / loss_return
    q = 1 - win_prob
    full_kelly = (win_prob * b - q) / (b + 1e-10)
    return float(np.clip(fraction * full_kelly, 0.0, 1.0))
