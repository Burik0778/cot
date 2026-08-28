"""
src/price/returns.py

Forward returns (spec section 11) -- computed from availability_date
forward, in currency-of-interest terms (see quote_convention.py), and
"maturity-aware": a forward return over horizon H weeks is only ever
produced if H weeks of price data actually exist after the anchor date. If
today is less than H weeks past the anchor, the value is None/NaN, never a
fabricated placeholder -- this matters for every downstream consumer
(base rate, analog outcomes, event study) that must not silently treat an
unmatured observation as a realized one (spec sections 16-19).
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional
import pandas as pd
import numpy as np

from src.price.quote_convention import currency_return


def _price_on_or_after(price_df: pd.DataFrame, target_date: date) -> Optional[tuple[date, float]]:
    """FX markets don't trade every calendar day; take the first available
    close ON OR AFTER target_date (never before -- that would look back)."""
    candidates = price_df[price_df["date"] >= target_date]
    if candidates.empty:
        return None
    row = candidates.iloc[0]
    return row["date"], float(row["close"])


def _price_on_or_before(price_df: pd.DataFrame, target_date: date) -> Optional[tuple[date, float]]:
    candidates = price_df[price_df["date"] <= target_date]
    if candidates.empty:
        return None
    row = candidates.iloc[-1]
    return row["date"], float(row["close"])


def compute_forward_return(
    price_df: pd.DataFrame,
    anchor_date: date,
    horizon_weeks: int,
    currency: str,
    as_of_date: Optional[date] = None,
) -> Optional[float]:
    """
    Returns the currency-of-interest forward return from `anchor_date` to
    `anchor_date + horizon_weeks*7`, or None if that target date has not
    happened yet relative to `as_of_date` (defaults to real today) -- i.e.
    the observation has not "matured". `price_df` must have columns
    [date, close] sorted ascending for ONE fx pair.
    """
    as_of_date = as_of_date or date.today()
    target_date = anchor_date + timedelta(weeks=horizon_weeks)
    if target_date > as_of_date:
        return None  # not matured yet -- do not guess

    start = _price_on_or_after(price_df, anchor_date)
    end = _price_on_or_after(price_df, target_date)
    if start is None or end is None:
        return None
    _, p0 = start
    _, p1 = end
    if p0 == 0:
        return None
    pair_return = (p1 / p0) - 1.0
    return float(currency_return(pd.Series([pair_return]), currency).iloc[0])


def add_forward_returns(
    market_states: pd.DataFrame,
    price_df: pd.DataFrame,
    currency: str,
    horizons_weeks: list[int],
    as_of_date: Optional[date] = None,
) -> pd.DataFrame:
    """
    market_states must have an `availability_date` column (date objects).
    Adds fwd_return_{h}w for each horizon -- the anchor is availability_date,
    NOT report_date, since availability_date is when the COT observation
    could actually have been acted upon (spec section 11's own example:
    "Price at availability/reference date -> price 4 weeks later").
    """
    df = market_states.copy()
    for h in horizons_weeks:
        df[f"fwd_return_{h}w"] = df["availability_date"].apply(
            lambda d: compute_forward_return(price_df, d, h, currency, as_of_date)
        )
    return df
