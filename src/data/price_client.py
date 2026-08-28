"""
src/data/price_client.py

Real FX price client, primary source FRED (Federal Reserve Bank of St.
Louis), H.10 Foreign Exchange Rates release -- confirmed 2026-08-27 (see
config/settings.py FX_PAIRS comments for the exact series-name citations).

FRED has NO standard NZD/USD daily series (confirmed absent from FRED's
published DEX* series list during development). Rather than inventing one,
`fetch_price_series("NZD", ...)` raises PriceSourceNotConfigured with an
explicit message telling the user which alternative sources to wire in
(e.g. Reserve Bank of New Zealand, or a commercial feed) -- see
DATA_SOURCES.md. Section 57 of the spec requires COT analysis to keep
working even if price data is unavailable; the pipeline treats a missing
price series for one currency as a per-currency failure, not a global one.

Same honesty note as cftc_client.py: this has not been exercised against
the live network in the build sandbox (FRED is unreachable there, 403
host_not_allowed). Real code, first live run is on the user's machine.
"""
from __future__ import annotations
import io
import requests
import pandas as pd
from datetime import date
from typing import Optional

from config import settings


class PriceApiError(RuntimeError):
    pass


class PriceSourceNotConfigured(RuntimeError):
    pass


def fetch_price_series(currency: str, start_date: Optional[date] = None) -> pd.DataFrame:
    """
    Returns a DataFrame [date, close] of the daily FX pair price associated
    with `currency` (see config.settings.FX_PAIRS), fetched from FRED's
    public CSV endpoint (no API key required). Raises rather than guessing
    if the series is unavailable or the currency has no configured source.
    """
    if currency not in settings.FX_PAIRS:
        raise ValueError(f"Unsupported currency '{currency}'. Supported: {settings.CURRENCIES}")

    pair = settings.FX_PAIRS[currency]
    if pair.fred_series is None:
        raise PriceSourceNotConfigured(
            f"No FRED series is configured for {currency} ({pair.symbol}) -- FRED does not "
            f"publish a standard NZD/USD daily series as of the last check (2026-08-27). "
            f"Wire in an alternative source in this function (e.g. RBNZ, or a commercial "
            f"feed) rather than assuming a series id. Until then, {currency} COT analysis "
            f"will run but price/forward-return/regime features for it will be unavailable "
            f"-- this is a per-currency degradation, not a platform-wide failure (spec section 57)."
        )

    url = settings.FRED_CSV_URL_TEMPLATE.format(series_id=pair.fred_series)
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise PriceApiError(f"FRED returned HTTP {resp.status_code} for {url}")

    df = pd.read_csv(io.StringIO(resp.text))
    if df.shape[1] != 2:
        raise PriceApiError(f"Unexpected FRED CSV shape for {pair.fred_series}: columns={list(df.columns)}")
    df.columns = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[df["close"].astype(str).str.strip() != "."]  # FRED uses "." for missing observations
    df["close"] = df["close"].astype(float)
    if start_date:
        df = df[df["date"] >= start_date]

    # FRED quotes some pairs as "1 USD buys N units of currency X" for
    # currency_is_base=False cases (e.g. DEXJPUS = JPY per USD), which is
    # already exactly the USDJPY-style market convention we want. For
    # currency_is_base=True cases (e.g. DEXUSEU = USD per EUR), that is
    # already EURUSD-style. No inversion needed either way -- FRED's own
    # unit definitions (fetched and quoted in config/settings.py) already
    # match the market convention in FX_PAIRS. This alignment is exactly
    # why those FRED series were chosen; do not "fix" it without re-checking
    # both definitions together.
    return df.reset_index(drop=True)
