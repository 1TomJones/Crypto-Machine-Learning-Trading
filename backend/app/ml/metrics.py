"""Performance and ML evaluation metrics.

Used by the backtest engine (get_results), walk-forward validation, and the
report generator.  All functions are pure / stateless.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Core return-series metrics
# ---------------------------------------------------------------------------


def annualised_return(equity_curve: pd.Series, periods_per_year: float = 252.0) -> float:
    """Compound annualised growth rate (CAGR)."""
    if len(equity_curve) < 2:
        return 0.0
    total_return = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1.0
    n_years = len(equity_curve) / periods_per_year
    if n_years <= 0:
        return 0.0
    return float((1.0 + total_return) ** (1.0 / n_years) - 1.0)


def annualised_volatility(returns: pd.Series, periods_per_year: float = 252.0) -> float:
    """Annualised standard deviation of daily returns."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(periods_per_year))


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    """Annualised Sharpe ratio."""
    vol = annualised_volatility(returns, periods_per_year)
    if vol == 0.0:
        return 0.0
    excess = returns.mean() * periods_per_year - risk_free_rate
    return float(excess / vol)


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    """Sortino ratio (downside deviation denominator)."""
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0
    downside_vol = float(downside.std(ddof=1) * math.sqrt(periods_per_year))
    if downside_vol == 0.0:
        return 0.0
    excess = returns.mean() * periods_per_year - risk_free_rate
    return float(excess / downside_vol)


def calmar_ratio(equity_curve: pd.Series, periods_per_year: float = 252.0) -> float:
    """CAGR / Max Drawdown (absolute value)."""
    cagr = annualised_return(equity_curve, periods_per_year)
    mdd = max_drawdown(equity_curve)
    if mdd == 0.0:
        return 0.0
    return float(cagr / abs(mdd))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown as a negative fraction (e.g. -0.25 = -25%)."""
    if len(equity_curve) < 2:
        return 0.0
    roll_max = equity_curve.cummax()
    dd = (equity_curve - roll_max) / roll_max
    return float(dd.min())


def max_drawdown_duration(equity_curve: pd.Series) -> int:
    """Length (in bars) of the longest drawdown period."""
    if len(equity_curve) < 2:
        return 0
    roll_max = equity_curve.cummax()
    underwater = equity_curve < roll_max
    # Find runs of True
    max_run = 0
    current_run = 0
    for u in underwater:
        if u:
            current_run += 1
            max_run = max(max_run, current_run)
        else:
            current_run = 0
    return max_run


def profit_factor(trades_pnl: list[float]) -> float:
    """Gross profit / Gross loss."""
    gross_profit = sum(p for p in trades_pnl if p > 0)
    gross_loss = abs(sum(p for p in trades_pnl if p < 0))
    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0 else 0.0
    return float(gross_profit / gross_loss)


def win_rate(trades_pnl: list[float]) -> float:
    """Fraction of winning trades."""
    if not trades_pnl:
        return 0.0
    return float(sum(1 for p in trades_pnl if p > 0) / len(trades_pnl))


def avg_win_loss_ratio(trades_pnl: list[float]) -> float:
    """Average win / |average loss|."""
    wins = [p for p in trades_pnl if p > 0]
    losses = [p for p in trades_pnl if p < 0]
    if not wins or not losses:
        return 0.0
    return float((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)))


def expectancy(trades_pnl: list[float]) -> float:
    """Expected value per trade."""
    if not trades_pnl:
        return 0.0
    return float(sum(trades_pnl) / len(trades_pnl))


# ---------------------------------------------------------------------------
# Advanced metrics
# ---------------------------------------------------------------------------


def probabilistic_sharpe_ratio(
    returns: pd.Series,
    benchmark_sr: float = 0.0,
    periods_per_year: float = 252.0,
) -> float:
    """Probabilistic Sharpe Ratio – probability that the true SR > benchmark SR.

    Bailey & Lopez de Prado (2012).
    """
    n = len(returns)
    if n < 4:
        return 0.0
    sr_hat = sharpe_ratio(returns, 0.0, periods_per_year)
    skew = float(returns.skew())
    kurt = float(returns.kurtosis())  # excess kurtosis
    # Standard error of SR estimate
    se = math.sqrt(
        (1.0 + 0.5 * sr_hat**2 - skew * sr_hat + (kurt / 4.0) * sr_hat**2) / (n - 1)
    )
    if se == 0.0:
        return 1.0 if sr_hat > benchmark_sr else 0.0
    z = (sr_hat - benchmark_sr) / se
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    returns: pd.Series,
    n_trials: int = 1,
    periods_per_year: float = 252.0,
) -> float:
    """Deflated Sharpe Ratio – PSR adjusted for multiple-testing.

    Uses the Bonferroni-like expected maximum SR from Lopez de Prado (2018).
    """
    n = len(returns)
    if n < 4 or n_trials < 1:
        return 0.0
    # Expected maximum SR under IID N(0,1)
    gamma_val = 0.5772156649  # Euler–Mascheroni constant
    e_max_sr = (
        (1.0 - gamma_val) * stats.norm.ppf(1.0 - 1.0 / n_trials)
        + gamma_val * stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    )
    # Rescale to same annualisation as the computed SR
    e_max_sr_annualised = e_max_sr / math.sqrt(periods_per_year)
    return probabilistic_sharpe_ratio(returns, e_max_sr_annualised, periods_per_year)


# ---------------------------------------------------------------------------
# Consolidated metrics dict
# ---------------------------------------------------------------------------


def full_metrics(
    equity_curve: pd.Series,
    trades_pnl: list[float] | None = None,
    benchmark_returns: pd.Series | None = None,
    periods_per_year: float = 252.0,
    n_trials: int = 1,
) -> dict[str, Any]:
    """Compute the complete set of performance metrics.

    Parameters
    ----------
    equity_curve:
        Time series of portfolio equity values.
    trades_pnl:
        List of per-trade P&L values (after fees & slippage).
    benchmark_returns:
        Daily returns of the benchmark (e.g. BTC buy-and-hold).
    periods_per_year:
        252 for daily, 365 for calendar-day crypto, 8760 for hourly, etc.
    n_trials:
        Number of strategy variants tested (for DSR deflation).

    Returns
    -------
    dict with all scalar metrics.
    """
    if len(equity_curve) < 2:
        return {}

    returns = equity_curve.pct_change().dropna()
    trades_pnl = trades_pnl or []

    m: dict[str, Any] = {}

    # Return / risk
    m["cagr"] = annualised_return(equity_curve, periods_per_year)
    m["annualised_vol"] = annualised_volatility(returns, periods_per_year)
    m["sharpe"] = sharpe_ratio(returns, 0.0, periods_per_year)
    m["sortino"] = sortino_ratio(returns, 0.0, periods_per_year)
    m["calmar"] = calmar_ratio(equity_curve, periods_per_year)
    m["max_drawdown"] = max_drawdown(equity_curve)
    m["max_drawdown_duration_bars"] = max_drawdown_duration(equity_curve)
    m["psr"] = probabilistic_sharpe_ratio(returns, 0.0, periods_per_year)
    m["dsr"] = deflated_sharpe_ratio(returns, n_trials, periods_per_year)

    # Trade statistics
    if trades_pnl:
        m["n_trades"] = len(trades_pnl)
        m["win_rate"] = win_rate(trades_pnl)
        m["profit_factor"] = profit_factor(trades_pnl)
        m["avg_win_loss_ratio"] = avg_win_loss_ratio(trades_pnl)
        m["expectancy"] = expectancy(trades_pnl)
        m["avg_trade_pnl"] = float(np.mean(trades_pnl))
        m["std_trade_pnl"] = float(np.std(trades_pnl, ddof=1)) if len(trades_pnl) > 1 else 0.0

    # Benchmark comparison
    if benchmark_returns is not None and len(benchmark_returns) > 1:
        aligned_r, aligned_bm = returns.align(benchmark_returns, join="inner")
        if len(aligned_r) > 1:
            covar = np.cov(aligned_r, aligned_bm)
            beta = float(covar[0, 1] / covar[1, 1]) if covar[1, 1] != 0 else 0.0
            alpha = float(
                aligned_r.mean() * periods_per_year
                - beta * aligned_bm.mean() * periods_per_year
            )
            corr = float(np.corrcoef(aligned_r, aligned_bm)[0, 1])
            bm_sharpe = sharpe_ratio(aligned_bm, 0.0, periods_per_year)
            m["alpha"] = alpha
            m["beta"] = beta
            m["correlation_to_benchmark"] = corr
            m["benchmark_sharpe"] = bm_sharpe
            m["information_ratio"] = (
                float((aligned_r - aligned_bm).mean() * periods_per_year
                      / ((aligned_r - aligned_bm).std(ddof=1) * math.sqrt(periods_per_year)))
                if (aligned_r - aligned_bm).std(ddof=1) > 0
                else 0.0
            )

    return m
