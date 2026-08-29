"""
src/data/price_client.py

Котировки. Два источника, пробуются по очереди:

  1. FRED (Federal Reserve, публичный CSV, ключ не нужен)
  2. Stooq (публичный CSV, ключ не нужен) — там есть металлы и индексы,
     которых у FRED нет дневными рядами

Для каждого рынка задаётся СПИСОК кандидатов, а не один код. Причина та же,
что и с названиями контрактов CFTC: коды рядов меняются и снимаются с
публикации, а жёстко зашитый единственный код превращается в тихо
отсутствующие данные. Здесь пробуются все варианты, и в лог пишется, какой
сработал.

Если не сработал ни один — рынок остаётся без цены. Это честная деградация:
позиционирование, перцентили и режимы считаются, а форвардные доходности,
аналоги и проверка на истории для него недоступны.
"""
from __future__ import annotations
import io
import requests
import pandas as pd
from datetime import date
from typing import Optional

from config.markets import market

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
STOOQ_CSV = "https://stooq.com/q/d/l/?s={sym}&i=d"


class PriceApiError(RuntimeError):
    pass


class PriceSourceNotConfigured(RuntimeError):
    pass


def _fred(series_id: str, timeout: int = 45) -> pd.DataFrame:
    r = requests.get(FRED_CSV.format(sid=series_id), timeout=timeout)
    if r.status_code != 200:
        raise PriceApiError(f"FRED HTTP {r.status_code} для {series_id}")
    df = pd.read_csv(io.StringIO(r.text))
    if df.shape[1] != 2:
        raise PriceApiError(f"Неожиданная структура FRED CSV для {series_id}: {list(df.columns)}")
    df.columns = ["date", "close"]
    df = df[df["close"].astype(str).str.strip() != "."]      # FRED помечает пропуски точкой
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["close"] = df["close"].astype(float)
    return df.reset_index(drop=True)


def _stooq(symbol: str, timeout: int = 45) -> pd.DataFrame:
    r = requests.get(STOOQ_CSV.format(sym=symbol), timeout=timeout)
    if r.status_code != 200:
        raise PriceApiError(f"Stooq HTTP {r.status_code} для {symbol}")
    text = r.text.strip()
    if not text or text.lower().startswith("no data"):
        raise PriceApiError(f"Stooq не отдал данных для {symbol}")
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower(): c for c in df.columns}
    if "date" not in cols or "close" not in cols:
        raise PriceApiError(f"В ответе Stooq нет нужных колонок для {symbol}: {list(df.columns)}")
    out = df[[cols["date"], cols["close"]]].copy()
    out.columns = ["date", "close"]
    out["date"] = pd.to_datetime(out["date"]).dt.date
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["close"])
    if out.empty:
        raise PriceApiError(f"Stooq вернул пустой ряд для {symbol}")
    return out.sort_values("date").reset_index(drop=True)


def has_price(code: str) -> bool:
    m = market(code)
    return bool(m.fred_series or getattr(m, "stooq_symbol", None))


def fetch_price_series(code: str, start_date: Optional[date] = None,
                        verbose: bool = True) -> pd.DataFrame:
    """
    DataFrame [date, close]. Перебирает кандидатов, возвращает первый
    успешный. Бросает PriceSourceNotConfigured, если ни один не сработал.
    """
    m = market(code)
    attempts: list[tuple[str, str]] = []
    fred = m.fred_series
    if fred:
        for sid in (fred.split("|") if isinstance(fred, str) else fred):
            attempts.append(("fred", sid.strip()))
    stooq = getattr(m, "stooq_symbol", None)
    if stooq:
        for sym in (stooq.split("|") if isinstance(stooq, str) else stooq):
            attempts.append(("stooq", sym.strip()))

    if not attempts:
        raise PriceSourceNotConfigured(
            f"Для {code} ({m.name}) не задан ни один источник цены.")

    errors = []
    for kind, ident in attempts:
        try:
            df = _fred(ident) if kind == "fred" else _stooq(ident)
            if len(df) < 100:
                raise PriceApiError(f"слишком короткий ряд ({len(df)} точек)")
            if verbose:
                print(f"    цена {code}: {kind}:{ident} — {len(df)} точек, "
                      f"с {df['date'].iloc[0]} по {df['date'].iloc[-1]}")
            if start_date:
                df = df[df["date"] >= start_date].reset_index(drop=True)
            return df
        except Exception as e:  # noqa: BLE001 — пробуем следующего кандидата
            errors.append(f"{kind}:{ident} — {e}")

    raise PriceSourceNotConfigured(
        f"Ни один источник цены не сработал для {code} ({m.name}). Попытки: " + " | ".join(errors))
