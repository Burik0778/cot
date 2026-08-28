"""
config/settings.py

Central, explicit configuration for the COT Research Platform.

Design principle (per project spec, section 1 and section 56/60): no hidden
assumptions. Every threshold, window, weight, and mapping used anywhere in
the engine lives here, in one place, visible and overridable — not buried
inside a function.

Sources for the constants below are cited inline. Where CFTC's own data does
not give us something (e.g. an exact historical publication timestamp), we
say so explicitly rather than inventing a number — see src/data/availability.py.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

CURRENCIES: List[str] = ["EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "MXN"]

# Worked examples per spec section 2 ("Основной рабочий пример: GBP/USD и EUR/USD")
PRIMARY_EXAMPLES: List[str] = ["EUR", "GBP"]

PARTICIPANTS: List[str] = [
    "dealer",
    "asset_manager",
    "leveraged_funds",
    "other_reportables",
    "nonreportables",
]

PARTICIPANT_LABELS: Dict[str, str] = {
    "dealer": "Dealer/Intermediary",
    "asset_manager": "Asset Manager/Institutional",
    "leveraged_funds": "Leveraged Funds",
    "other_reportables": "Other Reportables",
    "nonreportables": "Non-Reportables",
}

# "Non-Reportables" is NOT an independently reported category. Per CFTC's own
# Explanatory Notes (https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm,
# fetched 2026-08-27): "The long and short open interest shown as
# 'Nonreportable Positions' is derived by subtracting total long and short
# 'Reportable Positions' from the total open interest." Our loader computes
# it the same way rather than trusting a vendor's number for it.
NONREPORTABLES_IS_DERIVED: bool = True

# CFTC "market_and_exchange_names" values for each currency's TFF futures
# contract, used to filter the raw Socrata rows. These are standard, long
# stable CFTC contract names, but the loader (src/data/cftc_client.py)
# VALIDATES each one against the live dataset's distinct values at fetch
# time and raises a clear, loud error if a name is not found -- it never
# silently matches zero rows or substitutes a guess (spec section 34/57).
CFTC_MARKET_NAMES: Dict[str, str] = {
    "EUR": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "GBP": "BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE",
    "JPY": "JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE",
    "AUD": "AUSTRALIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CAD": "CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "CHF": "SWISS FRANC - CHICAGO MERCANTILE EXCHANGE",
    "NZD": "NEW ZEALAND DOLLAR - CHICAGO MERCANTILE EXCHANGE",
    "MXN": "MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE",
}

# CFTC Public Reporting Environment (Socrata). Confirmed 2026-08-27 via
# CFTC's own site (cftc.gov/MarketReports .../ExplanatoryNotes links here)
# and independent OpenAPI documentation (apis.io) that both cite the same
# resource id the user supplied (gpe5-46if) under the *non*-"hub" host.
# NOTE: the user's original brief pointed at
#   https://publicreportinghub.cftc.gov/Commitments-of-Traders/TFF-Futures-Only/gpe5-46if/explore
# which is reachable (valid *.cftc.gov TLS cert) and is almost certainly the
# newer human-browsing UI for the *same* dataset. The programmatic Socrata
# API documented by CFTC and third parties lives on the host below. The
# connector accepts either host via CFTC_API_BASE_URL_CANDIDATES and will
# try them in order -- verify which resolves in YOUR network before relying
# on it (see DATA_SOURCES.md).
CFTC_API_BASE_URL_CANDIDATES: List[str] = [
    "https://publicreporting.cftc.gov/resource",
    "https://publicreportinghub.cftc.gov/resource",
]
CFTC_TFF_FUTURES_ONLY_RESOURCE_ID: str = "gpe5-46if"


@dataclass(frozen=True)
class FxPair:
    symbol: str
    currency_is_base: bool  # True: pair-up == currency strengthens. False: pair-up == currency weakens (USD is base).
    fred_series: Optional[str]  # FRED series id, confirmed 2026-08-27, or None if FRED has no standard series.


# Quote convention per spec section 10. Verified against FRED series
# definitions (fred.stlouisfed.org), fetched 2026-08-27:
#   DEXUSEU = "U.S. Dollars to One Euro"            -> EURUSD convention (EUR is base)
#   DEXUSUK = "U.S. Dollars to One British Pound"    -> GBPUSD convention (GBP is base)
#   DEXUSAL = "U.S. Dollars to One Australian Dollar"-> AUDUSD convention (AUD is base)
#   DEXJPUS = "Japanese Yen to One U.S. Dollar"      -> USDJPY convention (USD is base)
#   DEXCAUS = "Canadian Dollars to One U.S. Dollar"  -> USDCAD convention (USD is base)
#   DEXSZUS = "Switzerland Francs to One U.S. Dollar"-> USDCHF convention (USD is base)
#   DEXMXUS = "Mexican Pesos to One U.S. Dollar"     -> USDMXN convention (USD is base)
# FRED has NO standard NZD/USD series (confirmed by its absence from FRED's
# H.10-derived DEX* series list) -- NZD price must come from price_client's
# fallback source. We do not invent a FRED code for it.
FX_PAIRS: Dict[str, FxPair] = {
    "EUR": FxPair("EURUSD", True, "DEXUSEU"),
    "GBP": FxPair("GBPUSD", True, "DEXUSUK"),
    "AUD": FxPair("AUDUSD", True, "DEXUSAL"),
    "NZD": FxPair("NZDUSD", True, None),
    "JPY": FxPair("USDJPY", False, "DEXJPUS"),
    "CAD": FxPair("USDCAD", False, "DEXCAUS"),
    "CHF": FxPair("USDCHF", False, "DEXSZUS"),
    "MXN": FxPair("USDMXN", False, "DEXMXUS"),
}

FRED_CSV_URL_TEMPLATE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"

# ---------------------------------------------------------------------------
# Statistics windows (weekly frequency -- COT reports are weekly)
# ---------------------------------------------------------------------------

CHANGE_WINDOWS_WEEKS: List[int] = [1, 4, 8, 13, 26, 52]
PERCENTILE_WINDOWS_WEEKS: List[int] = [13, 26, 52, 156, 260]
ZSCORE_WINDOWS_WEEKS: List[int] = [13, 26, 52, 156, 260]
FORWARD_HORIZONS_WEEKS: List[int] = [1, 2, 4, 8, 12, 26]

MIN_SAMPLE_SIZE: int = 20          # below this: "Insufficient sample size", no strong claims (spec 17)
LOW_CONFIDENCE_SAMPLE_SIZE: int = 30
GOOD_SAMPLE_SIZE: int = 50

BOOTSTRAP_ITERATIONS: int = 2000
BOOTSTRAP_CI: Tuple[float, float] = (2.5, 97.5)
RANDOM_SEED: int = 42

# ---------------------------------------------------------------------------
# Regime engine (spec section 8/20) -- rules are evaluated IN ORDER, first
# full match wins. This ordering is itself part of the documented method
# (METHODOLOGY.md) specifically so "Overall Regime" is never a black box.
# Conditions are ANDed tuples: (column, operator, threshold).
# ---------------------------------------------------------------------------

REGIME_RULES: List[dict] = [
    {
        "name": "Bullish Reversal",
        "description": "Leveraged funds deeply short but turning up for 2+ weeks; asset managers not deteriorating.",
        "conditions": [
            ("leveraged_funds_pct_52w", "<", 10),
            ("leveraged_funds_streak_up_weeks", ">=", 2),
            ("leveraged_funds_chg_4w", ">", 0),
            ("asset_manager_chg_4w", ">=", 0),
        ],
    },
    {
        "name": "Bearish Reversal",
        "description": "Leveraged funds deeply long but turning down for 2+ weeks; asset managers not improving.",
        "conditions": [
            ("leveraged_funds_pct_52w", ">", 90),
            ("leveraged_funds_streak_down_weeks", ">=", 2),
            ("leveraged_funds_chg_4w", "<", 0),
            ("asset_manager_chg_4w", "<=", 0),
        ],
    },
    {
        "name": "Extreme Long",
        "description": "Leveraged funds positioning at/near the top of its historical range.",
        "conditions": [("leveraged_funds_pct_52w", ">=", 95)],
    },
    {
        "name": "Extreme Short",
        "description": "Leveraged funds positioning at/near the bottom of its historical range.",
        "conditions": [("leveraged_funds_pct_52w", "<=", 5)],
    },
    {
        "name": "Accumulation",
        "description": "Leveraged funds net position rising for 4+ consecutive weeks, not yet an extreme.",
        "conditions": [
            ("leveraged_funds_streak_up_weeks", ">=", 4),
            ("leveraged_funds_pct_52w", "<", 95),
        ],
    },
    {
        "name": "Distribution",
        "description": "Leveraged funds net position falling for 4+ consecutive weeks, not yet an extreme.",
        "conditions": [
            ("leveraged_funds_streak_down_weeks", ">=", 4),
            ("leveraged_funds_pct_52w", ">", 5),
        ],
    },
    {
        "name": "Bullish Positioning",
        "description": "Leveraged funds moderately net long -- above the midpoint of the historical range.",
        "conditions": [("leveraged_funds_pct_52w", ">=", 60)],
    },
    {
        "name": "Bearish Positioning",
        "description": "Leveraged funds moderately net short -- below the midpoint of the historical range.",
        "conditions": [("leveraged_funds_pct_52w", "<=", 40)],
    },
    {
        "name": "Neutral",
        "description": "No directional or extreme condition met.",
        "conditions": [],  # fallback, always true
    },
]

COMPRESSION_LOOKBACK_WEEKS: int = 8
COMPRESSION_RATIO_THRESHOLD: float = 0.5   # std(now) < 0.5 * std(prior window) => compression
EXPANSION_RATIO_THRESHOLD: float = 1.5     # std(now) > 1.5 * std(prior window) => expansion

# ---------------------------------------------------------------------------
# Analog engine defaults (spec sections 12-14)
# ---------------------------------------------------------------------------

DEFAULT_ANALOG_FEATURES: Dict[str, float] = {
    "leveraged_funds_net_oi": 1.0,
    "leveraged_funds_pct_52w": 1.0,
    "leveraged_funds_z_52w": 0.75,
    "leveraged_funds_chg_4w_z": 0.75,
    "asset_manager_net_oi": 0.75,
    "asset_manager_pct_52w": 0.5,
    "asset_manager_chg_4w_z": 0.5,
    "price_chg_8w_z": 0.5,
}
DEFAULT_MAX_ANALOGS: int = 40
ANALOG_MIN_AVAILABILITY_LAG_WEEKS: int = 0  # analogs must have availability_date <= as-of date; see analogs/similarity.py

# ---------------------------------------------------------------------------
# Backtest / event-study defaults (spec sections 18, 22, 43-46)
# ---------------------------------------------------------------------------

DEFAULT_TRANSACTION_COST_BPS: float = 0.0   # 0 = no cost data wired by default; user-supplied, documented in BACKTESTING.md
WALK_FORWARD_FOLDS: int = 4
EVENT_STUDY_HORIZONS_WEEKS: List[int] = [-1, 0, 1, 2, 4, 8, 12]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DB_PATH: str = "data/cot_research.db"
