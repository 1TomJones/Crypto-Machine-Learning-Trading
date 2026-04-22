"""Shared ML strategy types.

This module defines the Signal dataclass that flows through the entire
trading pipeline: backtest engine → risk gate → OMS → live engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Signal:
    """A trading signal produced by a strategy model.

    Attributes
    ----------
    timestamp:
        Bar timestamp the signal was generated from.
    target_weight:
        Desired portfolio weight in [-1, 1]. Positive = long, negative = short,
        0 = flat.  The OMS converts this to a notional delta order.
    confidence:
        Model confidence in [0, 1].  Can be used for position sizing.
    strategy_id:
        Identifier of the strategy that produced the signal.
    meta:
        Optional free-form metadata (feature values, model version, etc.).
    """

    timestamp: pd.Timestamp
    target_weight: float  # [-1, 1]
    confidence: float = 1.0
    strategy_id: str = ""
    meta: dict = field(default_factory=dict)


class BaseStrategy:
    """Minimal interface every strategy must implement."""

    strategy_id: str = "base"

    def fit(self, features: pd.DataFrame, labels: pd.Series) -> None:
        """Train the model on the given feature/label data."""
        raise NotImplementedError

    def predict(self, features: pd.DataFrame) -> Signal:
        """Return a Signal for the latest row of *features*.

        Parameters
        ----------
        features:
            DataFrame whose last row corresponds to the current bar (no
            future data).  The strategy must only use ``features.iloc[-1]``
            or a trailing window – never future rows.
        """
        raise NotImplementedError

    def predict_proba(self, features: pd.DataFrame) -> float:
        """Return raw model probability (used for confidence scaling)."""
        raise NotImplementedError
