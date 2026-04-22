"""Technical indicators implemented from scratch (no TA-Lib dependency required).

All functions are pure, vectorised, and shift-safe: they never look ahead.
Warm-up NaN rows are left intact so the caller can decide how to handle them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int, adjust: bool = False) -> pd.Series:
    """EMA with α = 2/(n+1). adjust=False matches Wilder/TA-Lib convention."""
    return series.ewm(span=n, adjust=adjust, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI using Wilder smoothing (equivalent to EMA with α=1/n)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD line, signal line, histogram."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram}
    )


def bollinger_bands(
    close: pd.Series, n: int = 20, k: float = 2.0
) -> pd.DataFrame:
    """Upper, middle, lower bands; %B; bandwidth."""
    middle = sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=1)
    upper = middle + k * std
    lower = middle - k * std
    pct_b = (close - lower) / (upper - lower + 1e-10)
    bandwidth = (upper - lower) / (middle + 1e-10)
    return pd.DataFrame(
        {"bb_upper": upper, "bb_middle": middle, "bb_lower": lower,
         "bb_pct_b": pct_b, "bb_bandwidth": bandwidth}
    )


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """ATR using Wilder smoothing."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14
) -> pd.DataFrame:
    """ADX + DI+/DI- using Wilder smoothing."""
    up = high.diff()
    down = -low.diff()
    dm_plus = np.where((up > down) & (up > 0), up, 0.0)
    dm_minus = np.where((down > up) & (down > 0), down, 0.0)
    tr_s = atr(high, low, close, n) * n  # Wilder-smoothed TR (sum proxy)

    di_plus = 100 * pd.Series(dm_plus, index=close.index).ewm(
        alpha=1 / n, adjust=False, min_periods=n
    ).mean() / (tr_s + 1e-10)
    di_minus = 100 * pd.Series(dm_minus, index=close.index).ewm(
        alpha=1 / n, adjust=False, min_periods=n
    ).mean() / (tr_s + 1e-10)

    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus + 1e-10)
    adx_val = dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return pd.DataFrame({"adx": adx_val, "di_plus": di_plus, "di_minus": di_minus})


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series,
    k: int = 14, d: int = 3, smooth_k: int = 3,
) -> pd.DataFrame:
    """Fast stochastic %K, %D."""
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    raw_k = 100 * (close - ll) / (hh - ll + 1e-10)
    pct_k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean()
    pct_d = pct_k.rolling(d, min_periods=d).mean()
    return pd.DataFrame({"stoch_k": pct_k, "stoch_d": pct_d})


def williams_r(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14
) -> pd.Series:
    hh = high.rolling(n, min_periods=n).max()
    ll = low.rolling(n, min_periods=n).min()
    return -100 * (hh - close) / (hh - ll + 1e-10)


def cci(
    high: pd.Series, low: pd.Series, close: pd.Series, n: int = 20
) -> pd.Series:
    tp = (high + low + close) / 3
    tp_mean = tp.rolling(n, min_periods=n).mean()
    mad = tp.rolling(n, min_periods=n).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (tp - tp_mean) / (0.015 * mad + 1e-10)


def vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    """Session VWAP resetting at midnight UTC."""
    tp = (high + low + close) / 3
    idx = close.index
    # Group by date (UTC)
    dates = idx.normalize() if hasattr(idx, "normalize") else pd.DatetimeIndex(idx).normalize()
    cum_tpv = (tp * volume).groupby(dates).cumsum()
    cum_vol = volume.groupby(dates).cumsum()
    return cum_tpv / (cum_vol + 1e-10)


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


# ---------------------------------------------------------------------------
# Volatility estimators
# ---------------------------------------------------------------------------

def yang_zhang_vol(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    n: int = 30,
) -> pd.Series:
    """Yang-Zhang volatility estimator (best for OHLC data)."""
    log_oc = np.log(open_ / close.shift(1))       # overnight return
    log_co = np.log(close / open_)                 # close-to-open return
    log_ho = np.log(high / open_)
    log_lo = np.log(low / open_)

    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    rs = (log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co))
    sigma_rs = rs.rolling(n, min_periods=n).mean()
    sigma_oc = log_oc.rolling(n, min_periods=n).var(ddof=1)
    sigma_co = log_co.rolling(n, min_periods=n).var(ddof=1)
    result = np.sqrt(sigma_oc + k * sigma_co + (1 - k) * sigma_rs)
    return result


def parkinson_vol(high: pd.Series, low: pd.Series, n: int = 20) -> pd.Series:
    """Parkinson historical volatility."""
    log_hl = np.log(high / low)
    return np.sqrt((log_hl**2).rolling(n, min_periods=n).mean() / (4 * np.log(2)))


def garman_klass_vol(
    open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series,
    n: int = 20,
) -> pd.Series:
    """Garman-Klass volatility estimator."""
    log_hl = np.log(high / low)
    log_co = np.log(close / open_)
    term1 = 0.5 * log_hl**2
    term2 = (2 * np.log(2) - 1) * log_co**2
    return np.sqrt((term1 - term2).rolling(n, min_periods=n).mean())


# ---------------------------------------------------------------------------
# Microstructure
# ---------------------------------------------------------------------------

def book_imbalance(bid_vol: pd.Series, ask_vol: pd.Series) -> pd.Series:
    """L2 book imbalance in [-1, 1]."""
    total = bid_vol + ask_vol
    return (bid_vol - ask_vol) / (total + 1e-10)


def kyle_lambda(
    price_changes: pd.Series, signed_volume: pd.Series, n: int = 20
) -> pd.Series:
    """Kyle's lambda via rolling OLS of ΔP on signed volume."""
    results = []
    for i in range(len(price_changes)):
        if i < n:
            results.append(np.nan)
            continue
        y = price_changes.iloc[i - n:i].values
        x = signed_volume.iloc[i - n:i].values
        if np.std(x) < 1e-10:
            results.append(np.nan)
            continue
        beta = np.cov(x, y)[0, 1] / (np.var(x) + 1e-10)
        results.append(beta)
    return pd.Series(results, index=price_changes.index)
