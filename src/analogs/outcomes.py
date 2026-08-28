"""
src/analogs/outcomes.py

Spec section 15: Historical Outcome Analysis for a set of analog
observations, per forward horizon.

MFE/MAE honesty note: Maximum Favorable/Adverse Excursion is only
meaningful computed against the DAILY price path between anchor and
horizon end -- an excursion computed from just the two endpoint prices is
not an excursion at all, it's the same number as the return. This module
computes real path-based MFE/MAE when a daily price series is supplied,
and returns None (not a fabricated stand-in) when it is not.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import numpy as np
import pandas as pd

from config.settings import MIN_SAMPLE_SIZE
from src.price.quote_convention import currency_return


@dataclass
class OutcomeStats:
    horizon_weeks: int
    n: int
    win_rate: Optional[float]
    mean_return: Optional[float]
    median_return: Optional[float]
    p25: Optional[float]
    p75: Optional[float]
    best: Optional[float]
    worst: Optional[float]
    std: Optional[float]
    mfe_mean: Optional[float]
    mae_mean: Optional[float]
    sample_quality: str


def _sample_quality(n: int) -> str:
    if n < MIN_SAMPLE_SIZE:
        return "Insufficient sample size"
    if n < 30:
        return "Low confidence"
    if n < 50:
        return "Moderate"
    return "Good"


def summarize_returns(returns: pd.Series, horizon_weeks: int) -> OutcomeStats:
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return OutcomeStats(horizon_weeks, 0, None, None, None, None, None, None, None, None, None, None,
                             _sample_quality(0))
    return OutcomeStats(
        horizon_weeks=horizon_weeks,
        n=n,
        win_rate=float((r > 0).mean()),
        mean_return=float(r.mean()),
        median_return=float(r.median()),
        p25=float(r.quantile(0.25)),
        p75=float(r.quantile(0.75)),
        best=float(r.max()),
        worst=float(r.min()),
        std=float(r.std(ddof=1)) if n > 1 else None,
        mfe_mean=None,
        mae_mean=None,
        sample_quality=_sample_quality(n),
    )


def compute_excursion(price_daily: pd.DataFrame, anchor_date: date, horizon_weeks: int, currency: str) -> Optional[tuple[float, float]]:
    """
    Returns (MFE, MAE) in currency-of-interest terms for the path from
    anchor_date to anchor_date + horizon_weeks, using DAILY closes.
    MFE = best cumulative return reached at any point along the path.
    MAE = worst (most negative) cumulative return reached at any point.
    Returns None if the daily path is not available (never fabricates it).
    """
    end_date = anchor_date + timedelta(weeks=horizon_weeks)
    path = price_daily[(price_daily["date"] >= anchor_date) & (price_daily["date"] <= end_date)].sort_values("date")
    if len(path) < 2:
        return None
    p0 = float(path["close"].iloc[0])
    if p0 == 0:
        return None
    pair_path_returns = path["close"].astype(float) / p0 - 1.0
    ccy_path_returns = currency_return(pair_path_returns, currency)
    return float(ccy_path_returns.max()), float(ccy_path_returns.min())


def summarize_with_excursions(
    returns: pd.Series,
    anchor_dates: pd.Series,
    horizon_weeks: int,
    currency: str,
    price_daily: Optional[pd.DataFrame],
) -> OutcomeStats:
    stats = summarize_returns(returns, horizon_weeks)
    if price_daily is None or stats.n == 0:
        return stats

    mfes, maes = [], []
    valid = returns.dropna().index
    for idx in valid:
        exc = compute_excursion(price_daily, anchor_dates.loc[idx], horizon_weeks, currency)
        if exc is not None:
            mfes.append(exc[0])
            maes.append(exc[1])
    if mfes:
        stats.mfe_mean = float(np.mean(mfes))
        stats.mae_mean = float(np.mean(maes))
    return stats
