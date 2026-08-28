"""
src/data/cftc_client.py

Real client for the CFTC Public Reporting Environment (Socrata Open Data
API), Traders in Financial Futures - Futures Only dataset.

Endpoint confirmed 2026-08-27 via CFTC's own site + independent OpenAPI
documentation (see config/settings.py comments for citations):
    GET https://publicreporting.cftc.gov/resource/gpe5-46if.json

IMPORTANT / HONESTY NOTE
-------------------------
This module has NOT been exercised against the live network. The sandbox
this project was built in has outbound network access restricted to a small
allow-list (npm/pypi/github/anthropic) and CFTC's domain returns
`403 host_not_allowed` from that sandbox's egress proxy -- confirmed by
direct curl test during development, see the chat transcript / README.
The code below is real, not pseudocode, and follows the documented Socrata
API exactly, but its first live execution will be on the user's machine.
`scripts/validate_date.py` exists specifically so that first live run is
also the first real validation against CFTC's published numbers (spec
section 52) -- run it and read what it prints before trusting anything
downstream.

Failure handling (spec sections 34, 57): this client never invents data.
If the API is unreachable, changes shape, or a configured market name is
not found in the live data, it raises a clear, specific exception instead
of returning partial or synthetic rows.
"""
from __future__ import annotations
import requests
from datetime import date, datetime
from typing import Optional

from config import settings
from src.data.availability import get_availability

# The exact columns the TFF Futures Only Socrata dataset is documented to
# expose for the fields this platform needs. If CFTC changes column names,
# `fetch_tff_futures_only` will raise CftcSchemaError naming exactly which
# expected column went missing, rather than silently producing zeros/NaNs.
REQUIRED_COLUMNS = [
    "report_date_as_yyyy_mm_dd",
    "market_and_exchange_names",
    "open_interest_all",
    "dealer_positions_long_all", "dealer_positions_short_all",
    "asset_mgr_positions_long", "asset_mgr_positions_short",
    "lev_money_positions_long", "lev_money_positions_short",
    "other_rept_positions_long", "other_rept_positions_short",
    "tot_rept_positions_long_all", "tot_rept_positions_short",
]

PARTICIPANT_COLUMN_MAP = {
    "dealer": ("dealer_positions_long_all", "dealer_positions_short_all"),
    "asset_manager": ("asset_mgr_positions_long", "asset_mgr_positions_short"),
    "leveraged_funds": ("lev_money_positions_long", "lev_money_positions_short"),
    "other_reportables": ("other_rept_positions_long", "other_rept_positions_short"),
}


class CftcApiError(RuntimeError):
    """Raised when the CFTC API cannot be reached at all."""


class CftcSchemaError(RuntimeError):
    """Raised when the live dataset's shape does not match REQUIRED_COLUMNS or a
    configured market name is not found -- i.e. 'schema changed', per spec
    section 34: never fail silently."""


def _get(base_url: str, params: dict, timeout: int = 30) -> list[dict]:
    url = f"{base_url}/{settings.CFTC_TFF_FUTURES_ONLY_RESOURCE_ID}.json"
    resp = requests.get(url, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise CftcApiError(f"CFTC API returned HTTP {resp.status_code} for {url}: {resp.text[:300]}")
    return resp.json()


def fetch_tff_futures_only(
    currency: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page_size: int = 5000,
) -> list[dict]:
    """
    Fetches raw TFF Futures Only rows for one currency from CFTC, validates
    the schema and the market name against the live data, and returns a list
    of per-participant dict rows ready for src/data/db.py.upsert_cot_raw.

    Tries each URL in settings.CFTC_API_BASE_URL_CANDIDATES in order and
    raises CftcApiError only if ALL of them fail.
    """
    if currency not in settings.CFTC_MARKET_NAMES:
        raise ValueError(f"Unsupported currency '{currency}'. Supported: {settings.CURRENCIES}")

    market_name = settings.CFTC_MARKET_NAMES[currency]
    where_clauses = [f"market_and_exchange_names='{market_name}'"]
    if start_date:
        where_clauses.append(f"report_date_as_yyyy_mm_dd >= '{start_date.isoformat()}T00:00:00.000'")
    if end_date:
        where_clauses.append(f"report_date_as_yyyy_mm_dd <= '{end_date.isoformat()}T00:00:00.000'")

    params = {
        "$where": " AND ".join(where_clauses),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": page_size,
    }

    last_error = None
    payload = None
    used_base = None
    for base_url in settings.CFTC_API_BASE_URL_CANDIDATES:
        try:
            payload = _get(base_url, params)
            used_base = base_url
            break
        except Exception as e:  # noqa: BLE001 -- deliberately broad: we try the next candidate host
            last_error = e
            continue

    if payload is None:
        raise CftcApiError(
            f"Could not reach any CFTC API host for currency={currency}. "
            f"Tried: {settings.CFTC_API_BASE_URL_CANDIDATES}. Last error: {last_error}"
        )

    if len(payload) == 0:
        raise CftcSchemaError(
            f"CFTC API at {used_base} returned zero rows for market_and_exchange_names="
            f"'{market_name}'. This name may no longer match the live dataset (CFTC "
            f"occasionally renames contracts) -- verify at "
            f"{used_base.replace('/resource','')}/d/{settings.CFTC_TFF_FUTURES_ONLY_RESOURCE_ID} "
            f"before assuming the currency has simply stopped trading."
        )

    sample_columns = set(payload[0].keys())
    missing = [c for c in REQUIRED_COLUMNS if c not in sample_columns]
    if missing:
        raise CftcSchemaError(
            f"CFTC dataset schema changed: expected columns missing: {missing}. "
            f"Refusing to guess -- update REQUIRED_COLUMNS / PARTICIPANT_COLUMN_MAP "
            f"in src/data/cftc_client.py after checking the live column list."
        )

    rows: list[dict] = []
    ingested_at = datetime.utcnow().isoformat()
    for record in payload:
        report_date = datetime.strptime(record["report_date_as_yyyy_mm_dd"][:10], "%Y-%m-%d").date()
        avail = get_availability(report_date)
        open_interest = int(float(record["open_interest_all"]))

        reportable_long_total = 0
        reportable_short_total = 0
        for participant, (long_col, short_col) in PARTICIPANT_COLUMN_MAP.items():
            long_v = int(float(record[long_col]))
            short_v = int(float(record[short_col]))
            reportable_long_total += long_v
            reportable_short_total += short_v
            rows.append({
                "market": currency, "participant": participant,
                "report_date": report_date.isoformat(),
                "availability_date": avail.availability_date.isoformat(),
                "availability_source": avail.source,
                "long": long_v, "short": short_v, "open_interest": open_interest,
                "source": "cftc_socrata", "ingested_at": ingested_at,
            })

        # Nonreportables: derived residual, per CFTC's own Explanatory Notes
        # (see config/settings.py NONREPORTABLES_IS_DERIVED) -- computed here
        # from the OTHER columns we already fetched, never trusted from a
        # separate vendor number.
        rows.append({
            "market": currency, "participant": "nonreportables",
            "report_date": report_date.isoformat(),
            "availability_date": avail.availability_date.isoformat(),
            "availability_source": avail.source,
            "long": open_interest - reportable_long_total,
            "short": open_interest - reportable_short_total,
            "open_interest": open_interest,
            "source": "cftc_socrata", "ingested_at": ingested_at,
        })

    return rows
