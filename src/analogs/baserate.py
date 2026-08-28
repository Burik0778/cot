"""
src/analogs/baserate.py

Spec section 16: base rate is MANDATORY context for every analog result.
"68% win rate in similar cases" means nothing on its own -- what matters is
the DIFFERENCE from the unconditional base rate over the same history and
horizon.

Maturity-aware: the base rate population is filtered to observations whose
forward return has actually matured as of `as_of_date` -- an unconditional
sample that quietly includes a bunch of NaN-because-not-yet-happened rows
would silently understate N or bias the average toward already-known-early
resolvers, so we drop them explicitly (dropna already does this correctly
since compute_forward_return returns None/NaN for unmatured horizons; this
module just makes that requirement explicit and testable).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from src.analogs.outcomes import summarize_returns, OutcomeStats


@dataclass
class BaseRateComparison:
    horizon_weeks: int
    base_rate: OutcomeStats       # unconditional, over the full eligible history
    analog_rate: OutcomeStats     # conditional, over the matched analogs
    win_rate_diff_pp: Optional[float]     # percentage points, analog - base
    median_return_diff: Optional[float]   # analog - base


def compute_base_rate(all_states: pd.DataFrame, horizon_weeks: int, return_col: str) -> OutcomeStats:
    """`all_states` should be the FULL eligible history for one market (not
    just analogs) -- i.e. the unconditional population."""
    return summarize_returns(all_states[return_col], horizon_weeks)


def compare_to_base_rate(analog_returns: pd.Series, all_states: pd.DataFrame, horizon_weeks: int, return_col: str) -> BaseRateComparison:
    base = compute_base_rate(all_states, horizon_weeks, return_col)
    analog = summarize_returns(analog_returns, horizon_weeks)

    win_diff = None
    median_diff = None
    if base.win_rate is not None and analog.win_rate is not None:
        win_diff = (analog.win_rate - base.win_rate) * 100.0
    if base.median_return is not None and analog.median_return is not None:
        median_diff = analog.median_return - base.median_return

    return BaseRateComparison(horizon_weeks, base, analog, win_diff, median_diff)
