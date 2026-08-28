"""
src/price/quote_convention.py

Spec section 10: "Не допускай ошибок из-за направления котировки."

For EURUSD/GBPUSD/AUDUSD/NZDUSD, the currency of interest is the BASE
currency: a rising pair price means the currency strengthens.
For USDJPY/USDCAD/USDCHF/USDMXN, USD is the base and the currency of
interest is the QUOTE currency: a rising pair price means the currency
WEAKENS (USD strengthens).

`currency_return()` converts a raw pair return into the "how much did THIS
currency move" return, so that, e.g., a +1% EURUSD move and a -1% USDJPY
move are BOTH correctly recorded as the non-USD currency weakening by
being consistent about sign -- wait, precisely: +1% EURUSD move = EUR
strengthened 1%. A +1% USDJPY move = JPY WEAKENED ~1% (USD strengthened).
This module makes that sign flip explicit and tested, rather than left
implicit somewhere in a chart.
"""
from __future__ import annotations
import pandas as pd

from config.settings import FX_PAIRS


def currency_return(pair_return: pd.Series, currency: str) -> pd.Series:
    """Converts a raw FX pair return into the return of `currency` itself."""
    pair = FX_PAIRS[currency]
    return pair_return if pair.currency_is_base else -pair_return


def currency_direction_sign(currency: str) -> int:
    """+1 if a rising pair price means the currency strengthens, else -1."""
    return 1 if FX_PAIRS[currency].currency_is_base else -1
