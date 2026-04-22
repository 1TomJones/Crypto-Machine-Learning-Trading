"""Target construction: triple-barrier labelling and meta-labelling.

Based on López de Prado, *Advances in Financial Machine Learning*, Ch. 3–4.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_volatility(close: pd.Series, span: int = 100) -> pd.Series:
    """EWMA daily volatility estimate for triple-barrier thresholds."""
    ret = np.log(close / close.shift(1))
    return ret.ewm(span=span, min_periods=span).std()


def get_vertical_barriers(
    t_events: pd.DatetimeIndex, close: pd.Series, num_days: float = 1.0
) -> pd.Series:
    """Compute vertical barrier timestamps (t_events + num_days trading periods)."""
    t1 = close.index.searchsorted(t_events + pd.Timedelta(days=num_days))
    t1 = t1[t1 < close.shape[0]]
    t1 = pd.Series(close.index[t1], index=t_events[: t1.shape[0]])
    return t1


def triple_barrier(
    close: pd.Series,
    events: pd.DataFrame,
    pt_sl: tuple[float, float] = (1.0, 1.0),
    vol: pd.Series | None = None,
) -> pd.DataFrame:
    """Triple-barrier labelling (López de Prado Ch.3).

    Parameters
    ----------
    close: price series
    events: DataFrame with index=t0 (entry time), columns:
        't1'   – vertical barrier timestamp
        'trgt' – volatility target (used to scale barriers)
        'side' – optional: +1 long / -1 short (default +1)
    pt_sl: (profit-take multiplier, stop-loss multiplier)
    vol: pre-computed volatility; if None, computed from daily_volatility

    Returns
    -------
    DataFrame with columns: ret (return at exit), label (+1/0/-1)
    """
    if vol is None:
        vol = daily_volatility(close)

    out = events[["t1"]].copy()
    pt, sl = pt_sl

    for t0, row in events.iterrows():
        t1 = row["t1"]
        trgt = row.get("trgt", vol.get(t0, np.nan))
        if pd.isna(trgt) or trgt <= 0:
            out.loc[t0, "ret"] = np.nan
            out.loc[t0, "label"] = np.nan
            continue

        side = row.get("side", 1)
        path = close.loc[t0:t1]
        if len(path) < 2:
            out.loc[t0, "ret"] = 0.0
            out.loc[t0, "label"] = 0
            continue

        r = np.log(path / path.iloc[0]) * side
        upper = pt * trgt if pt > 0 else np.inf
        lower = -sl * trgt if sl > 0 else -np.inf

        t_up = r[r >= upper].index.min() if pt > 0 else pd.NaT
        t_dn = r[r <= lower].index.min() if sl > 0 else pd.NaT

        candidates = [x for x in [t_up, t_dn, t1] if pd.notna(x)]
        t_end = min(candidates) if candidates else t1

        ret_val = float(r.get(t_end, r.iloc[-1]))
        if pd.notna(t_up) and t_end == t_up:
            label = 1
        elif pd.notna(t_dn) and t_end == t_dn:
            label = -1
        else:
            label = 0

        out.loc[t0, "ret"] = ret_val
        out.loc[t0, "label"] = label

    out["label"] = out["label"].fillna(0).astype(int)
    return out


def meta_labels(
    primary_signal: pd.Series, triple_barrier_labels: pd.DataFrame
) -> pd.Series:
    """Generate binary meta-labels (1 = primary model agrees with barrier outcome).

    primary_signal: +1 or -1 per bar
    triple_barrier_labels: output of triple_barrier() with 'label' column
    """
    aligned = primary_signal.reindex(triple_barrier_labels.index)
    meta = (aligned == triple_barrier_labels["label"]).astype(int)
    # Where barrier label is 0 (vertical hit), meta-label is 0
    meta[triple_barrier_labels["label"] == 0] = 0
    return meta


def get_concurrency(t1: pd.Series, all_idx: pd.DatetimeIndex) -> pd.Series:
    """Count how many labels are active (overlapping) at each timestamp."""
    counts = pd.Series(0, index=all_idx, dtype=float)
    for t0, t_end in t1.items():
        if pd.isna(t_end):
            continue
        counts.loc[t0:t_end] += 1
    return counts.replace(0, np.nan)


def get_sample_weights(
    events: pd.DataFrame, close: pd.Series
) -> pd.Series:
    """Sample weights based on return attribution and average uniqueness.

    w_i ∝ |r_i| / c_t  averaged over [t0, t1].
    """
    t1 = events["t1"]
    c_t = get_concurrency(t1, close.index)
    weights = pd.Series(index=events.index, dtype=float)

    for t0, row in events.iterrows():
        t1_val = row["t1"]
        if pd.isna(t1_val):
            weights[t0] = 0.0
            continue
        r = np.log(close.loc[t0:t1_val] / close.loc[t0]).iloc[-1]
        span = c_t.loc[t0:t1_val]
        avg_uniqueness = (1.0 / span.replace(0, np.nan)).mean()
        weights[t0] = abs(r) * avg_uniqueness

    weights = weights.fillna(0.0)
    if weights.sum() > 0:
        weights /= weights.sum()
    return weights
