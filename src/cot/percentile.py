"""
src/cot/percentile.py

Historical percentile (spec section 4), with the one rule the spec calls
"critically important": the CURRENT observation must NOT be part of the
distribution it is ranked against.

Method: for a window of size W, percentile(t) ranks value[t] against
value[t-W .. t-1] (W prior observations, NOT including t itself). This is
implemented with `series.rolling(window + 1)` so that the rolling frame
always has exactly one more element than the reference window -- the last
element (current) is sliced off before ranking. NaN until W prior
observations exist (no partial/fabricated percentile on short history).
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from scipy.stats import percentileofscore

from config.settings import PERCENTILE_WINDOWS_WEEKS, ZSCORE_WINDOWS_WEEKS


def rolling_percentile_excl_current(series: pd.Series, window: int) -> pd.Series:
    def _pct(w: np.ndarray) -> float:
        hist, current = w[:-1], w[-1]
        if len(hist) < window or np.isnan(hist).any():
            return np.nan
        return percentileofscore(hist, current, kind="mean")

    return series.rolling(window + 1).apply(_pct, raw=True)


def rolling_zscore_excl_current(series: pd.Series, window: int) -> pd.Series:
    """
    z[t] = (value[t] - mean(value[t-window:t])) / std(value[t-window:t]),
    i.e. mean/std computed over the window ending at t-1 (shift(1) before
    rolling), so t itself never contributes to its own mean/std. ddof=1
    (sample std) -- documented in STATISTICS.md.
    """
    shifted = series.shift(1)
    mean = shifted.rolling(window).mean()
    std = shifted.rolling(window).std(ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (series - mean) / std.replace(0, np.nan)
    return z


def add_percentiles(df: pd.DataFrame, value_col: str = "net_oi", windows: list[int] | None = None) -> pd.DataFrame:
    df = df.copy()
    for w in (windows or PERCENTILE_WINDOWS_WEEKS):
        df[f"pct_{w}w"] = rolling_percentile_excl_current(df[value_col], w)
    return df


def add_zscores(df: pd.DataFrame, value_col: str = "net_oi", windows: list[int] | None = None) -> pd.DataFrame:
    df = df.copy()
    for w in (windows or ZSCORE_WINDOWS_WEEKS):
        df[f"z_{w}w"] = rolling_zscore_excl_current(df[value_col], w)
    return df
