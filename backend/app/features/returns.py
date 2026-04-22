"""Return-based and statistical features."""
from __future__ import annotations

import numpy as np
import pandas as pd


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def multi_horizon_returns(
    close: pd.Series, horizons: list[int] = [1, 5, 15, 60, 240]
) -> pd.DataFrame:
    """Log returns over multiple lookback horizons."""
    frames = {}
    for h in horizons:
        frames[f"ret_{h}"] = np.log(close / close.shift(h))
    return pd.DataFrame(frames)


def rolling_moments(
    returns: pd.Series, windows: list[int] = [20, 60, 240]
) -> pd.DataFrame:
    """Rolling mean, std, skew, kurtosis for each window."""
    frames = {}
    for w in windows:
        r = returns.rolling(w, min_periods=w)
        frames[f"ret_mean_{w}"] = r.mean()
        frames[f"ret_std_{w}"] = r.std(ddof=1)
        frames[f"ret_skew_{w}"] = r.skew()
        frames[f"ret_kurt_{w}"] = r.kurt()
    return pd.DataFrame(frames)


def autocorrelations(
    returns: pd.Series, lags: list[int] = [1, 5, 20]
) -> pd.DataFrame:
    """Rolling autocorrelation and abs-return autocorrelation at given lags."""
    frames = {}
    abs_ret = returns.abs()
    window = max(lags) * 4
    for lag in lags:
        frames[f"autocorr_{lag}"] = returns.rolling(window, min_periods=window).apply(
            lambda x: pd.Series(x).autocorr(lag=lag), raw=True
        )
        frames[f"abs_autocorr_{lag}"] = abs_ret.rolling(window, min_periods=window).apply(
            lambda x: pd.Series(x).autocorr(lag=lag), raw=True
        )
    return pd.DataFrame(frames)


def range_features(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series
) -> pd.DataFrame:
    """HL ratio, CO ratio, close-location value."""
    return pd.DataFrame({
        "hl_ratio": (high - low) / (close + 1e-10),
        "co_ratio": (close - open_) / (open_ + 1e-10),
        "close_location": (close - low) / (high - low + 1e-10),
    })


def time_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Cyclic time features for 24/7 crypto markets."""
    if not hasattr(index, "hour"):
        index = pd.DatetimeIndex(index)
    hour = index.hour + index.minute / 60.0
    dow = index.dayofweek
    frames = {
        "hour_sin": np.sin(2 * np.pi * hour / 24),
        "hour_cos": np.cos(2 * np.pi * hour / 24),
        "dow_sin": np.sin(2 * np.pi * dow / 7),
        "dow_cos": np.cos(2 * np.pi * dow / 7),
        "is_asia_session": ((hour >= 0) & (hour < 8)).astype(float),
        "is_europe_session": ((hour >= 7) & (hour < 16)).astype(float),
        "is_us_session": ((hour >= 13) & (hour < 21)).astype(float),
        "is_weekend": (dow >= 5).astype(float),
        "is_us_equity_open": ((hour >= 13.5) & (hour < 14.0)).astype(float),
    }
    return pd.DataFrame(frames, index=index)
