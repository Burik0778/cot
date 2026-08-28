"""
src/scanner/scanner.py

Spec section 24: at-a-glance table across all currencies. Deliberately
thin -- it reuses the regime-history machinery rather than inventing a
separate "opportunity score", per the spec's own instruction not to call
these "opportunities" (trading signals) but "Strongest Historical Setups"
(section 27): the "edge" column is exactly the base-rate-relative forward
return difference from src.analogs.baserate, nothing more.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from src.cot.regime_history import compute_regime_history


@dataclass
class ScannerRow:
    currency: str
    regime: str
    leveraged_funds_net_oi: Optional[float]
    leveraged_funds_pct_52w: Optional[float]
    asset_manager_net_oi: Optional[float]
    asset_manager_pct_52w: Optional[float]
    momentum_chg_4w: Optional[float]
    regime_occurrences: int
    horizon_weeks: int
    edge_pp: Optional[float]
    sample_quality: str


def scan(market_states_by_currency: dict[str, pd.DataFrame], horizon_weeks: int = 8) -> list[ScannerRow]:
    rows = []
    for currency, states in market_states_by_currency.items():
        if states.empty:
            continue
        latest = states.sort_values("report_date").iloc[-1]
        regime = latest["regime"]
        hist = compute_regime_history(states, regime, [horizon_weeks])
        cmp = hist.comparisons.get(horizon_weeks)
        edge = cmp.win_rate_diff_pp if cmp else None
        quality = cmp.analog_rate.sample_quality if cmp else "Insufficient sample size"

        rows.append(ScannerRow(
            currency=currency,
            regime=regime,
            leveraged_funds_net_oi=latest.get("leveraged_funds_net_oi"),
            leveraged_funds_pct_52w=latest.get("leveraged_funds_pct_52w"),
            asset_manager_net_oi=latest.get("asset_manager_net_oi"),
            asset_manager_pct_52w=latest.get("asset_manager_pct_52w"),
            momentum_chg_4w=latest.get("leveraged_funds_chg_4w"),
            regime_occurrences=hist.occurrences,
            horizon_weeks=horizon_weeks,
            edge_pp=edge,
            sample_quality=quality,
        ))
    return rows


def scanner_to_dataframe(rows: list[ScannerRow]) -> pd.DataFrame:
    df = pd.DataFrame([r.__dict__ for r in rows])
    if not df.empty:
        df = df.sort_values("edge_pp", ascending=False, na_position="last")
    return df
