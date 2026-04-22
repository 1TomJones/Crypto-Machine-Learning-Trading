"""Purged k-fold and walk-forward cross-validation.

Based on López de Prado AFML Ch.7.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator


class PurgedKFold(BaseCrossValidator):
    """Sklearn-compatible CV with purging and embargo.

    Purging: removes training observations whose label span overlaps the test set.
    Embargo: removes an additional buffer after the test block from training.
    """

    def __init__(self, n_splits: int = 5, pct_embargo: float = 0.01) -> None:
        super().__init__()
        self.n_splits = n_splits
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, groups=None):
        n = len(X)
        fold = n // self.n_splits
        embargo = int(n * self.pct_embargo)
        idx = np.arange(n)

        for k in range(self.n_splits):
            ts = k * fold
            te = (k + 1) * fold if k < self.n_splits - 1 else n
            test = idx[ts:te]
            mask = np.ones(n, dtype=bool)
            mask[ts:te] = False  # test block
            # embargo after test block
            mask[te: min(n, te + embargo)] = False
            train = idx[mask]
            yield train, test

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits


def purged_kfold_split(
    n: int, n_splits: int, horizon: int, embargo: int
):
    """Generator yielding (train_idx, test_idx) with purge and embargo.

    horizon: number of bars a label spans (used for purging)
    embargo: number of bars after the test block to exclude from training
    """
    fold = n // n_splits
    idx = np.arange(n)
    for k in range(n_splits):
        ts = k * fold
        te = (k + 1) * fold if k < n_splits - 1 else n
        test = idx[ts:te]
        mask = np.ones(n, dtype=bool)
        mask[max(0, ts - horizon): te + 1] = False  # purge
        mask[te + 1: min(n, te + 1 + embargo)] = False  # embargo
        yield idx[mask], test


def walk_forward_splits(
    n: int,
    train_size: int,
    test_size: int,
    step_size: int,
    expanding: bool = False,
):
    """Generator yielding (train_idx, test_idx) for walk-forward validation."""
    start = 0
    while start + train_size + test_size <= n:
        train_start = 0 if expanding else start
        train_end = start + train_size
        test_start = train_end
        test_end = min(test_start + test_size, n)
        yield np.arange(train_start, train_end), np.arange(test_start, test_end)
        start += step_size


def combinatorial_purged_cv(
    n: int,
    n_folds: int = 6,
    k_test: int = 2,
    pct_embargo: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Combinatorial Purged CV (CPCV).

    Partition n observations into n_folds groups.
    For each C(n_folds, k_test) combination, k_test groups form the test set.
    Returns list of (train_idx, test_idx) tuples.
    C(6,2) = 15 splits → 5 distinct backtest paths.
    """
    fold_size = n // n_folds
    groups = []
    for i in range(n_folds):
        start = i * fold_size
        end = (i + 1) * fold_size if i < n_folds - 1 else n
        groups.append(np.arange(start, end))

    embargo = max(1, int(n * pct_embargo))
    splits = []

    for test_combo in combinations(range(n_folds), k_test):
        test_idx = np.concatenate([groups[i] for i in test_combo])
        test_min, test_max = test_idx.min(), test_idx.max()

        train_parts = []
        for i in range(n_folds):
            if i in test_combo:
                continue
            g = groups[i]
            # Purge: drop group if it ends within horizon of test start
            if g[-1] >= test_min:
                continue
            # Embargo: drop group immediately after test
            if g[0] <= test_max + embargo:
                continue
            train_parts.append(g)

        if train_parts:
            train_idx = np.concatenate(train_parts)
            splits.append((np.sort(train_idx), np.sort(test_idx)))

    return splits
