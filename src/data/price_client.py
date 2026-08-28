"""
src/data/price_client.py

Котировки. Основной источник — FRED (публичный CSV, ключ не нужен).

Важно: цена есть НЕ у всех инструментов. У FRED нет дневных рядов для
NZD/USD, Russell 2000, металлов и облигаций. Вместо того чтобы выдумывать
код серии, для таких рынков цена просто отсутствует.

Последствие честное и задокументированное: без цены не считаются форвардные
доходности, исторические аналоги и базовая ставка. Позиционирование,
перцентили, z-score, режимы и графики позиций работают как обычно. В
интерфейсе такие рынки помечены отдельно.
"""
from __future__ import annotations
import io
import requests
import pandas as pd
from datetime import date
from typing import Optional

from config import settings
from config.markets import market

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"


class PriceApiError(RuntimeError):
    pass


class PriceSourceNotConfigured(RuntimeError):
    pass


def has_price(code: str) -> bool:
    return market(code).fred_series is not None


def fetch_price_series(code: str, start_date: Optional[date] = None) -> pd.DataFrame:
    """DataFrame [date, close]. Бросает исключение, а не гадает."""
    m = market(code)
    if m.fred_series is None:
        raise PriceSourceNotConfigured(
            f"Для {code} ({m.name}) не настроен источник цены — у FRED нет подходящего "
            f"дневного ряда. Позиционирование считается, форвардные доходности и "
            f"исторические аналоги для этого рынка недоступны."
        )

    url = FRED_CSV.format(series_id=m.fred_series)
    resp = requests.get(url, timeout=45)
    if resp.status_code != 200:
        raise PriceApiError(f"FRED вернул HTTP {resp.status_code} для {m.fred_series} ({code})")

    df = pd.read_csv(io.StringIO(resp.text))
    if df.shape[1] != 2:
        raise PriceApiError(f"Неожиданная структура CSV FRED для {m.fred_series}: {list(df.columns)}")
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["close"].astype(str).str.strip() != "."]   # FRED помечает пропуски точкой
    df["close"] = df["close"].astype(float)
    if start_date:
        df = df[df["date"] >= start_date]
    return df.reset_index(drop=True)
