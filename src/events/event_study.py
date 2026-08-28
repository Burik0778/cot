"""
src/events/event_study.py

Spec section 22. The user supplies a boolean condition mask over
market_states (built via pandas .query() on a whitelist of columns -- see
src/backtest/engine.py for the shared, safety-checked condition evaluator).
This module aligns cumulative returns around each qualifying event date on
a common horizon axis and summarizes across all occurrences.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

from config.settings import EVENT_STUDY_HORIZONS_WEEKS


@dataclass
class EventStudyResult:
    n_events: int
    horizons_weeks: list[int]
    mean_cumulative_return: dict
    median_cumulative_return: dict
    p25: dict
    p75: dict
    event_dates: list[str]


def run_event_study(
    market_states: pd.DataFrame,
    event_mask: pd.Series,
    return_col_template: str = "fwd_return_{h}w",
    horizons_weeks: list[int] | None = None,
    date_col: str = "report_date",
) -> EventStudyResult:
    """
    For horizon h >= 0, uses the already-computed, maturity-aware
    fwd_return_{h}w column (never re-derives it here, so the same
    no-look-ahead guarantees from src/price/returns.py apply automatically).
    For h < 0 (pre-event), uses -h-week TRAILING change already present as
    chg_{-h}w-style columns if available; otherwise reports NaN rather than
    fabricating a lookback number from a column that doesn't exist.
    """
    horizons_weeks = horizons_weeks or EVENT_STUDY_HORIZONS_WEEKS
    events = market_states[event_mask.fillna(False)]
    n = len(events)

    mean_ret, median_ret, p25, p75 = {}, {}, {}, {}
    for h in horizons_weeks:
        if h >= 0:
            col = return_col_template.format(h=h)
        else:
            col = f"chg_{abs(h)}w_pct_return"  # optional, pre-event; usually absent -> NaN below
        if col in events.columns:
            r = events[col].dropna()
        else:
            r = pd.Series(dtype=float)
        mean_ret[h] = float(r.mean()) if len(r) else None
        median_ret[h] = float(r.median()) if len(r) else None
        p25[h] = float(r.quantile(0.25)) if len(r) else None
        p75[h] = float(r.quantile(0.75)) if len(r) else None

    return EventStudyResult(
        n_events=n,
        horizons_weeks=horizons_weeks,
        mean_cumulative_return=mean_ret,
        median_cumulative_return=median_ret,
        p25=p25, p75=p75,
        event_dates=events[date_col].astype(str).tolist(),
    )
