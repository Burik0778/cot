"""
src/cot/regimes.py

Spec sections 8, 20, 41: rule-based, explainable, ordered regime
classification. No ML. Rules are plain (column, operator, threshold) tuples
from config.settings.REGIME_RULES, evaluated in order; the first rule whose
every condition holds is the "Overall Regime". This module also returns
WHY (the exact conditions that fired) for every row, so a UI "WHY?" button
(spec section 40) has something real to show, not a canned sentence.
"""
from __future__ import annotations
import operator
import pandas as pd

from config.settings import REGIME_RULES

_OPS = {
    ">": operator.gt, ">=": operator.ge,
    "<": operator.lt, "<=": operator.le,
    "==": operator.eq,
}


def _condition_holds(row: pd.Series, column: str, op: str, threshold: float) -> bool:
    value = row.get(column)
    if value is None or pd.isna(value):
        return False
    return _OPS[op](value, threshold)


def classify_row(row: pd.Series, rules: list[dict] | None = None) -> tuple[str, list[str]]:
    """
    Returns (regime_name, reasons). `reasons` lists the human-readable
    conditions that were satisfied for the winning rule -- this is exactly
    what the spec's "WHY?" button (section 40) should render.
    """
    for rule in (rules or REGIME_RULES):
        conditions = rule["conditions"]
        if all(_condition_holds(row, col, op, thr) for col, op, thr in conditions):
            reasons = [f"{col} {op} {thr} (actual: {row.get(col)})" for col, op, thr in conditions]
            if not reasons:
                reasons = [rule["description"]]
            return rule["name"], reasons
    return "Unclassified", ["No configured rule matched -- check REGIME_RULES has a fallback."]


def classify_dataframe(df: pd.DataFrame, rules: list[dict] | None = None) -> pd.DataFrame:
    df = df.copy()
    results = df.apply(lambda row: classify_row(row, rules), axis=1)
    df["regime"] = results.apply(lambda t: t[0])
    df["regime_reasons"] = results.apply(lambda t: t[1])
    return df


def compression_expansion_flag(std_now: float, std_prior: float, compression_ratio: float, expansion_ratio: float) -> str | None:
    """Spec section 8: Positioning Compression / Expansion, as an ADDITIONAL
    flag alongside (not instead of) the main regime -- a market can be e.g.
    'Bullish Positioning' AND 'Positioning Compression' at once."""
    if std_prior is None or std_prior == 0 or pd.isna(std_prior) or pd.isna(std_now):
        return None
    ratio = std_now / std_prior
    if ratio < compression_ratio:
        return "Positioning Compression"
    if ratio > expansion_ratio:
        return "Positioning Expansion"
    return None
