"""
src/backtest/engine.py

Spec sections 23, 43, 45. Ties together: condition evaluation (conditions.py),
maturity-aware forward returns (already computed in market_states by
src/price/returns.py -- never re-derived here), performance metrics
(metrics.py), walk-forward folds (walkforward.py), and the multiple-testing
hypothesis counter (src/data/db.py -- optional; pass a Database to log it).

Position sizing (spec section 43): fixed one-unit-per-signal only in this
version. Risk-based / volatility-scaled sizing is NOT implemented --
documented in BACKTESTING.md and LIMITATIONS.md rather than silently
assumed.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from config.settings import DEFAULT_TRANSACTION_COST_BPS
from src.backtest.conditions import evaluate_condition
from src.backtest.metrics import compute_performance, PerformanceMetrics
from src.backtest.walkforward import split_folds, WalkForwardResult
from src.price.quote_convention import currency_direction_sign


@dataclass
class BacktestResult:
    condition_text: str
    market: str
    horizon_weeks: int
    direction: str  # "long_currency" | "short_currency" | "auto_pair"
    n_signals_total: int
    n_matured: int
    n_still_open: int
    performance: PerformanceMetrics
    walk_forward: WalkForwardResult
    trade_dates: list[str] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)


def run_backtest(
    market_states: pd.DataFrame,
    market: str,
    condition_text: str,
    horizon_weeks: int,
    direction: str = "long_currency",
    cost_bps: float = DEFAULT_TRANSACTION_COST_BPS,
    date_col: str = "report_date",
) -> BacktestResult:
    if direction not in ("long_currency", "short_currency"):
        raise ValueError("direction must be 'long_currency' or 'short_currency'")

    mask = evaluate_condition(market_states, condition_text)
    signals = market_states[mask].copy()
    n_total = len(signals)

    return_col = f"fwd_return_{horizon_weeks}w"
    if return_col not in signals.columns:
        raise KeyError(f"market_states has no column {return_col}; compute forward returns for this horizon first.")

    matured = signals.dropna(subset=[return_col])
    n_matured = len(matured)
    n_open = n_total - n_matured

    direction_mult = 1 if direction == "long_currency" else -1
    cost = cost_bps / 10000.0
    trade_returns = matured[return_col] * direction_mult - cost

    perf = compute_performance(trade_returns, horizon_weeks)

    wf_input = matured[[date_col]].copy()
    wf_input["_trade_return"] = trade_returns.values
    wf = split_folds(wf_input, date_col, "_trade_return")

    equity = (1 + trade_returns.sort_index()).cumprod().tolist() if n_matured else []

    return BacktestResult(
        condition_text=condition_text, market=market, horizon_weeks=horizon_weeks,
        direction=direction, n_signals_total=n_total, n_matured=n_matured, n_still_open=n_open,
        performance=perf, walk_forward=wf,
        trade_dates=matured[date_col].astype(str).tolist(),
        equity_curve=equity,
    )
