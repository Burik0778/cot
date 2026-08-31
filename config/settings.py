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
# Рынки, участники и котировки переехали в config/markets.py.
# Здесь их намеренно нет: два источника правды для одного и того же — верный
# способ получить расхождение между тем, что качается, и тем, что считается.
# ---------------------------------------------------------------------------

from config.markets import (  # noqa: F401 — реэкспорт для обратной совместимости
    RESOURCE_IDS, all_codes, market,
)

CFTC_TFF_FUTURES_ONLY_RESOURCE_ID: str = RESOURCE_IDS["tff"]
CFTC_API_BASE_URL_CANDIDATES: list = [
    "https://publicreporting.cftc.gov/resource",
    "https://publicreportinghub.cftc.gov/resource",
]

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

# Два набора признаков вместо одного. Смешивать их нельзя: пока цена
# сидит в признаках по умолчанию, невозможно ответить на вопрос «есть ли
# преимущество в самом COT» — оно может целиком идти от ценового тренда.
ANALOG_FEATURES_COT_ONLY: Dict[str, float] = {
    "leveraged_funds_net_oi": 1.0,
    "leveraged_funds_pct_52w": 1.0,
    "leveraged_funds_z_52w": 0.75,
    "leveraged_funds_chg_4w_z": 0.75,
    "asset_manager_net_oi": 0.75,
    "asset_manager_pct_52w": 0.5,
    "asset_manager_chg_4w_z": 0.5,
}

ANALOG_FEATURES_COT_PRICE: Dict[str, float] = {
    **ANALOG_FEATURES_COT_ONLY,
    "price_chg_8w_z": 0.5,
}

ANALOG_MODES = {
    "cot_only": ("Только COT", ANALOG_FEATURES_COT_ONLY),
    "cot_price": ("COT + цена", ANALOG_FEATURES_COT_PRICE),
}

# Оставлено для обратной совместимости; равно режиму COT + цена.
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
