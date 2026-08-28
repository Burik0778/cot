"""
src/cot/divergence.py

Spec section 9: Participant Divergence engine. A divergence is flagged when
two signed quantities (participant net change, or participant vs price)
move in OPPOSITE directions over the same window, with each move's
magnitude past a noise-floor threshold (so two near-zero wiggles aren't
called a "divergence").

This returns FACTS (what moved which way, by how much, since when) --
never an interpretation like "this means a reversal is coming". That
judgment, if any, belongs to the AI layer, working from these facts (spec
section 60).
"""
from __future__ import annotations
import pandas as pd
from dataclasses import dataclass, field


@dataclass
class DivergenceEvent:
    kind: str                 # e.g. "asset_manager_vs_leveraged_funds" or "leveraged_funds_vs_price"
    start_report_date: str
    window_weeks: int
    a_name: str
    a_change: float
    b_name: str
    b_change: float
    magnitude: float          # min(|a_change|, |b_change|) -- the divergence can only be as strong as its weaker leg


def detect_pairwise_divergence(
    df: pd.DataFrame,
    a_col: str,
    b_col: str,
    a_label: str,
    b_label: str,
    window_weeks: int = 4,
    noise_floor: float = 0.0,
) -> pd.Series:
    """
    Returns a boolean Series aligned to df.index: True where the two
    `_col` series' `window_weeks`-week changes have opposite signs and both
    exceed `noise_floor` in absolute value.
    """
    a_chg = df[a_col].diff(window_weeks)
    b_chg = df[b_col].diff(window_weeks)
    opposite_sign = (a_chg * b_chg) < 0
    past_floor = (a_chg.abs() > noise_floor) & (b_chg.abs() > noise_floor)
    return (opposite_sign & past_floor).fillna(False)


def collect_divergence_events(
    df: pd.DataFrame,
    pairs: list[tuple[str, str, str, str]],
    window_weeks: int = 4,
    noise_floor: float = 0.0,
    date_col: str = "report_date",
) -> list[DivergenceEvent]:
    """
    `pairs` is a list of (a_col, b_col, a_label, b_label). Returns one
    DivergenceEvent per row where a divergence is flagged for that pair.
    """
    events: list[DivergenceEvent] = []
    for a_col, b_col, a_label, b_label in pairs:
        flags = detect_pairwise_divergence(df, a_col, b_col, a_label, b_label, window_weeks, noise_floor)
        a_chg = df[a_col].diff(window_weeks)
        b_chg = df[b_col].diff(window_weeks)
        for idx in df.index[flags]:
            events.append(DivergenceEvent(
                kind=f"{a_label}_vs_{b_label}",
                start_report_date=str(df.loc[idx, date_col]),
                window_weeks=window_weeks,
                a_name=a_label, a_change=float(a_chg.loc[idx]),
                b_name=b_label, b_change=float(b_chg.loc[idx]),
                magnitude=float(min(abs(a_chg.loc[idx]), abs(b_chg.loc[idx]))),
            ))
    return events
