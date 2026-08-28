"""
src/cot/regime_history.py

Spec section 21: "Show all historical periods when the system determined
the same regime" + forward-return summary for those occurrences, compared
to base rate. Thin wrapper around outcomes.summarize_returns +
baserate.compare_to_base_rate, scoped to rows sharing the CURRENT regime.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from src.analogs.baserate import compare_to_base_rate, BaseRateComparison


@dataclass
class RegimeHistory:
    regime: str
    occurrences: int
    dates: list[str]
    median_duration_weeks: float | None
    comparisons: dict  # {horizon_weeks: BaseRateComparison}


def _episode_durations(is_regime: pd.Series) -> list[int]:
    """Length (in weeks) of each maximal consecutive run of True."""
    durations = []
    count = 0
    for v in is_regime:
        if v:
            count += 1
        elif count:
            durations.append(count)
            count = 0
    if count:
        durations.append(count)
    return durations


def compute_regime_history(market_states: pd.DataFrame, regime: str, horizons_weeks: list[int],
                            exclude_latest: bool = True, date_col: str = "report_date") -> RegimeHistory:
    df = market_states.sort_values(date_col).reset_index(drop=True)
    mask = df["regime"] == regime
    if exclude_latest and len(df) and mask.iloc[-1]:
        mask = mask.copy()
        mask.iloc[-1] = False  # current observation is not "history" relative to itself

    occurrence_dates = df.loc[mask, date_col].astype(str).tolist()
    durations = _episode_durations(mask)
    median_duration = float(pd.Series(durations).median()) if durations else None

    comparisons = {}
    for h in horizons_weeks:
        col = f"fwd_return_{h}w"
        if col not in df.columns:
            continue
        comparisons[h] = compare_to_base_rate(df.loc[mask, col], df, h, col)

    return RegimeHistory(
        regime=regime, occurrences=int(mask.sum()), dates=occurrence_dates,
        median_duration_weeks=median_duration, comparisons=comparisons,
    )
