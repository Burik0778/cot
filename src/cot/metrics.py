"""
src/cot/metrics.py

Basic positioning metrics (spec sections 3-4). All computed from raw
long/short/open_interest -- never trusted pre-computed from a vendor.
"""
from __future__ import annotations
import pandas as pd
import numpy as np

from config.settings import CHANGE_WINDOWS_WEEKS


def compute_net(long: pd.Series, short: pd.Series) -> pd.Series:
    return long - short


def compute_ratio(numerator: pd.Series, open_interest: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        result = numerator / open_interest.replace(0, np.nan)
    return result


def add_basic_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    df must be sorted by report_date ascending and contain one participant's
    time series for one market: columns long, short, open_interest.
    Adds: net, net_oi, long_oi, short_oi.
    """
    df = df.copy()
    df["net"] = compute_net(df["long"], df["short"])
    df["net_oi"] = compute_ratio(df["net"], df["open_interest"])
    df["long_oi"] = compute_ratio(df["long"], df["open_interest"])
    df["short_oi"] = compute_ratio(df["short"], df["open_interest"])
    return df


def add_changes(df: pd.DataFrame, value_col: str = "net", windows: list[int] | None = None) -> pd.DataFrame:
    """
    Adds chg_{w}w columns = value[t] - value[t-w]. NaN when fewer than w
    prior observations exist (pandas .diff() semantics, which is exactly
    that -- no fabricated 0s for missing history).
    """
    df = df.copy()
    windows = windows or CHANGE_WINDOWS_WEEKS
    for w in windows:
        df[f"chg_{w}w"] = df[value_col].diff(w)
    return df


def add_streaks(df: pd.DataFrame, value_col: str = "net") -> pd.DataFrame:
    """
    streak_up_weeks[t]  = number of consecutive weeks (ending at t, inclusive)
                           that value_col strictly increased week-over-week.
    streak_down_weeks[t] = mirror, for strict decreases.
    A flat (unchanged) week resets both to 0 for that row.
    """
    df = df.copy()
    diff = df[value_col].diff()
    up = diff > 0
    down = diff < 0

    def _streak(mask: pd.Series) -> pd.Series:
        # `grp` only increments at a False position, so every run of
        # consecutive Trues shares one group with the False right before
        # it. Taking the CUMULATIVE SUM of the boolean mask within each
        # group (not cumcount) then naturally yields 0 at that leading
        # False and 1, 2, 3, ... at each subsequent True in the run.
        grp = (~mask).cumsum()
        streak = mask.groupby(grp).cumsum()
        return streak.astype(int)

    df["streak_up_weeks"] = _streak(up)
    df["streak_down_weeks"] = _streak(down)
    return df
