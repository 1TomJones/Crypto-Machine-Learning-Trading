"""Master feature pipeline.

compute_features() is the single deterministic entry point. It produces a
wide DataFrame aligned to the input OHLCV index. All features are shifted
by one bar to prevent lookahead bias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.frac_diff import frac_diff_ffd
from app.features.indicators import (
    adx, atr, bollinger_bands, cci, ema, macd, obv, parkinson_vol,
    rsi, sma, stochastic, vwap, williams_r, yang_zhang_vol,
)
from app.features.returns import (
    autocorrelations, log_returns, multi_horizon_returns,
    range_features, rolling_moments, time_features,
)

FEATURE_SET_VERSION = 1

FEATURE_MANIFEST = {
    "version": FEATURE_SET_VERSION,
    "features": {
        "rsi_14": {"formula": "RSI(close, 14)", "dtype": "float32", "range": [0, 100]},
        "macd_hist": {"formula": "MACD(12,26,9).histogram", "dtype": "float32"},
        "macd_slope": {"formula": "MACD_hist.diff()", "dtype": "float32"},
        "bb_pct_b": {"formula": "BB(20,2).pct_b", "dtype": "float32", "range": [0, 1]},
        "bb_bandwidth": {"formula": "BB(20,2).bandwidth", "dtype": "float32"},
        "atr_ratio": {"formula": "ATR(14)/close", "dtype": "float32"},
        "adx_14": {"formula": "ADX(14)", "dtype": "float32"},
        "stoch_k": {"formula": "Stoch(14,3,3).%K", "dtype": "float32"},
        "stoch_d": {"formula": "Stoch(14,3,3).%D", "dtype": "float32"},
        "yz_vol_20": {"formula": "YangZhang(20)", "dtype": "float32"},
        "yz_vol_60": {"formula": "YangZhang(60)", "dtype": "float32"},
        "vwap_dev": {"formula": "(close - VWAP) / VWAP", "dtype": "float32"},
        "obv_zscore": {"formula": "zscore(OBV, 20)", "dtype": "float32"},
        "fd_logprice": {"formula": "FracDiff(log(close), d=0.35)", "dtype": "float32"},
        "ema20_ratio": {"formula": "close/EMA(20) - 1", "dtype": "float32"},
        "ema50_ratio": {"formula": "close/EMA(50) - 1", "dtype": "float32"},
        "ema200_ratio": {"formula": "close/EMA(200) - 1", "dtype": "float32"},
    },
}


def compute_features(
    ohlcv: pd.DataFrame,
    version: int = FEATURE_SET_VERSION,
) -> pd.DataFrame:
    """Compute all features from OHLCV DataFrame.

    ohlcv must have columns: open, high, low, close, volume
    and a DatetimeIndex (UTC-aware).

    Returns a DataFrame with the same index. All features are shifted by 1
    bar (no lookahead). Warm-up rows are NaN.
    """
    if ohlcv.empty:
        return pd.DataFrame(index=ohlcv.index)

    o = ohlcv["open"]
    h = ohlcv["high"]
    l = ohlcv["low"]
    c = ohlcv["close"]
    v = ohlcv["volume"]

    parts: list[pd.DataFrame | pd.Series] = []

    # --- Trend indicators ---
    parts.append(pd.DataFrame({
        "rsi_14": rsi(c, 14),
        "ema20_ratio": c / ema(c, 20) - 1,
        "ema50_ratio": c / ema(c, 50) - 1,
        "ema200_ratio": c / ema(c, 200) - 1,
        "adx_14": adx(h, l, c, 14)["adx"],
    }))

    # --- MACD ---
    macd_df = macd(c, 12, 26, 9)
    parts.append(pd.DataFrame({
        "macd_hist": macd_df["histogram"],
        "macd_slope": macd_df["histogram"].diff(),
    }))

    # --- Bollinger Bands ---
    bb = bollinger_bands(c, 20, 2.0)
    parts.append(bb[["bb_pct_b", "bb_bandwidth"]])

    # --- ATR ---
    atr_series = atr(h, l, c, 14)
    parts.append(pd.DataFrame({"atr_ratio": atr_series / (c + 1e-10)}))

    # --- Stochastic ---
    stoch = stochastic(h, l, c, 14, 3, 3)
    parts.append(stoch)

    # --- Volatility ---
    parts.append(pd.DataFrame({
        "yz_vol_20": yang_zhang_vol(o, h, l, c, 20),
        "yz_vol_60": yang_zhang_vol(o, h, l, c, 60),
        "parkinson_vol_20": parkinson_vol(h, l, 20),
    }))

    # --- Volume ---
    vwap_s = vwap(h, l, c, v)
    obv_s = obv(c, v)
    obv_mean = obv_s.rolling(20, min_periods=20).mean()
    obv_std = obv_s.rolling(20, min_periods=20).std()
    parts.append(pd.DataFrame({
        "vwap_dev": (c - vwap_s) / (vwap_s + 1e-10),
        "obv_zscore": (obv_s - obv_mean) / (obv_std + 1e-10),
    }))

    # --- Fractional differentiation ---
    log_close = np.log(c + 1e-10)
    parts.append(pd.DataFrame({
        "fd_logprice": frac_diff_ffd(log_close, d=0.35, thresh=1e-4),
    }))

    # --- Return features ---
    ret = log_returns(c)
    parts.append(multi_horizon_returns(c, [1, 5, 15, 60, 240]))
    parts.append(rolling_moments(ret, [20, 60, 240]))
    parts.append(autocorrelations(ret, [1, 5, 20]))
    parts.append(range_features(o, h, l, c))

    # --- Time features ---
    parts.append(time_features(ohlcv.index))

    # Combine all features
    feat = pd.concat(parts, axis=1)

    # CRITICAL: shift all features by 1 bar to prevent lookahead
    feat = feat.shift(1)

    feat.index = ohlcv.index
    return feat.astype("float32")
