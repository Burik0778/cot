"""
src/price/quote_convention.py

Направление котировки.

Для EURUSD, GBPUSD, AUDUSD, NZDUSD рост пары = укрепление инструмента.
Для USDJPY, USDCAD, USDCHF, USDMXN в базе стоит доллар, поэтому рост пары =
ОСЛАБЛЕНИЕ инструмента, и знак надо перевернуть.

Для индексов, крипты и металлов переворот не нужен: рост цены = рост
инструмента.

Ошибка здесь переворачивает вывод по половине рынков, поэтому флаг задан
явно в реестре (config/markets.py, price_is_inverse) и покрыт тестами.
"""
from __future__ import annotations
import pandas as pd

from config.markets import market


def currency_return(pair_return: pd.Series, code: str) -> pd.Series:
    return -pair_return if market(code).price_is_inverse else pair_return


def currency_direction_sign(code: str) -> int:
    return -1 if market(code).price_is_inverse else 1
