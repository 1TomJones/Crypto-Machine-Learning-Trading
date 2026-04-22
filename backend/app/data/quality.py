"""Data quality checks and gap-filling."""
from __future__ import annotations

import numpy as np
import pandas as pd
import structlog

log = structlog.get_logger(__name__)


class DataQualityChecker:
    def fill_gaps(self, df: pd.DataFrame, freq: str = "1min") -> pd.DataFrame:
        """Reindex to full time range, mark gap rows with source_quality=0."""
        if df.empty:
            return df
        full_idx = pd.date_range(df.index[0], df.index[-1], freq=freq, tz="UTC")
        df_reindexed = df.reindex(full_idx)
        gap_mask = df_reindexed["close"].isna()
        # Forward-fill OHLCV (gap bar = flat bar at last close)
        df_reindexed[["open", "high", "low", "close"]] = df_reindexed[
            ["open", "high", "low", "close"]
        ].ffill()
        df_reindexed["volume"] = df_reindexed["volume"].fillna(0.0)
        df_reindexed["source_quality"] = df_reindexed.get(
            "source_quality", pd.Series(1, index=df_reindexed.index)
        )
        df_reindexed.loc[gap_mask, "source_quality"] = 0
        n_gaps = gap_mask.sum()
        if n_gaps > 0:
            log.info("gaps_filled", n_gaps=int(n_gaps), freq=freq)
        return df_reindexed

    def clip_outliers(
        self, df: pd.DataFrame, n_atr: float = 5.0, window: int = 20
    ) -> pd.DataFrame:
        """Clip OHLCV bars where close deviates > n*ATR from rolling median."""
        df = df.copy()
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(window).mean()
        median_c = df["close"].rolling(window).median()
        upper = median_c + n_atr * atr
        lower = median_c - n_atr * atr
        outlier_mask = (df["close"] > upper) | (df["close"] < lower)
        n_out = outlier_mask.sum()
        if n_out > 0:
            log.warning("outliers_clipped", count=int(n_out))
            df.loc[outlier_mask, "close"] = median_c[outlier_mask]
            df.loc[outlier_mask, "open"] = median_c[outlier_mask]
            df.loc[outlier_mask, "high"] = median_c[outlier_mask]
            df.loc[outlier_mask, "low"] = median_c[outlier_mask]
            df.loc[outlier_mask, "source_quality"] = 0
        return df

    def validate_ohlcv(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, list[str]]:
        """Validate OHLCV integrity. Returns (cleaned_df, warnings)."""
        warnings: list[str] = []
        df = df.copy()

        # High >= Open, Close, Low
        bad_high = df["high"] < df[["open", "close", "low"]].max(axis=1)
        if bad_high.any():
            warnings.append(f"{bad_high.sum()} bars with high < max(O,C,L)")
            df.loc[bad_high, "high"] = df.loc[bad_high, ["open", "close", "low"]].max(axis=1)

        # Low <= Open, Close, High
        bad_low = df["low"] > df[["open", "close", "high"]].min(axis=1)
        if bad_low.any():
            warnings.append(f"{bad_low.sum()} bars with low > min(O,C,H)")
            df.loc[bad_low, "low"] = df.loc[bad_low, ["open", "close", "high"]].min(axis=1)

        # No negative prices
        for col in ["open", "high", "low", "close"]:
            neg = df[col] <= 0
            if neg.any():
                warnings.append(f"{neg.sum()} negative/zero {col} values")
                df = df.loc[~neg]

        # No negative volume
        neg_vol = df["volume"] < 0
        if neg_vol.any():
            warnings.append(f"{neg_vol.sum()} negative volume bars")
            df.loc[neg_vol, "volume"] = 0.0

        return df, warnings
