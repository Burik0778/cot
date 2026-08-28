"""
src/backtest/conditions.py

Spec section 23: USER-DEFINED CONDITIONS, e.g.
    "leveraged_funds_pct_52w < 10 and asset_manager_net_oi > 0.20 and leveraged_funds_chg_4w > 0"

Uses pandas.DataFrame.query() rather than raw eval() -- query() only
understands column-name/comparison/boolean-logic expressions, not arbitrary
statements, attribute access, or function calls, which is the right level
of restriction for a local single-user research tool. A short token
blocklist is added as defense-in-depth against obviously-wrong input (e.g.
someone pasting a stray "import os"), not as a security boundary against a
determined attacker with equal privileges to the process itself -- see
BACKTESTING.md for the honest scope of this restriction.
"""
from __future__ import annotations
import pandas as pd

FORBIDDEN_TOKENS = ["__", "import", "exec", "eval", "os.", "sys.", "open(", "lambda", ".pipe", ".apply", ".to_"]


class UnsafeConditionError(ValueError):
    pass


def validate_condition_text(condition_text: str) -> None:
    lowered = condition_text.lower()
    for tok in FORBIDDEN_TOKENS:
        if tok in lowered:
            raise UnsafeConditionError(f"Condition contains a disallowed token: '{tok}'")


def evaluate_condition(df: pd.DataFrame, condition_text: str) -> pd.Series:
    """Returns a boolean Series aligned to df.index, True where the row
    satisfies condition_text. Raises ValueError with the original pandas
    error message on a malformed condition (unknown column, syntax error)
    rather than silently returning an empty/all-False mask."""
    validate_condition_text(condition_text)
    try:
        matched_index = df.query(condition_text, engine="python").index
    except Exception as e:  # noqa: BLE001 -- re-raised with context immediately below
        raise ValueError(f"Could not evaluate condition '{condition_text}': {e}") from e
    return df.index.to_series().isin(matched_index)
