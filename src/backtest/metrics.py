"""
src/backtest/metrics.py

Spec section 44. Computed purely from a Series of realized (matured) trade
returns plus an entry-date-ordered equity curve. Documented simplification
(see BACKTESTING.md): the equity curve compounds trades in chronological
ENTRY order as if capital were fully sequential -- it does NOT model
overlapping concurrent positions when multiple signals fire in the same
holding window. This is a research tool, not a position-sizing/portfolio
simulator (spec section 43 explicitly separates "research" from "actual
trading strategy").
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class PerformanceMetrics:
    n_trades: int
    win_rate: Optional[float]
    avg_win: Optional[float]
    avg_loss: Optional[float]
    expectancy: Optional[float]
    profit_factor: Optional[float]
    sharpe: Optional[float]
    sortino: Optional[float]
    max_drawdown: Optional[float]
    calmar: Optional[float]
    avg_holding_period_weeks: Optional[float]


def compute_performance(trade_returns: pd.Series, holding_period_weeks: int, periods_per_year: float = 52.0) -> PerformanceMetrics:
    r = trade_returns.dropna()
    n = len(r)
    if n == 0:
        return PerformanceMetrics(0, None, None, None, None, None, None, None, None, None, None)

    wins = r[r > 0]
    losses = r[r <= 0]
    win_rate = len(wins) / n
    avg_win = float(wins.mean()) if len(wins) else 0.0
    avg_loss = float(losses.mean()) if len(losses) else 0.0
    expectancy = float(r.mean())

    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else None)

    # Annualization approximates each trade as an independent period sampled
    # every `holding_period_weeks` (a simplification given overlapping
    # trades are not modeled -- see module docstring).
    ann_factor = np.sqrt(periods_per_year / max(holding_period_weeks, 1e-9))
    std = r.std(ddof=1) if n > 1 else None
    sharpe = float((r.mean() / std) * ann_factor) if std and std > 0 else None

    downside = r[r < 0]
    downside_std = downside.std(ddof=1) if len(downside) > 1 else None
    sortino = float((r.mean() / downside_std) * ann_factor) if downside_std and downside_std > 0 else None

    equity = (1 + r).cumprod()
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_dd = float(drawdown.min()) if len(drawdown) else None

    total_return = float(equity.iloc[-1] - 1) if len(equity) else None
    calmar = (total_return / abs(max_dd)) if (max_dd and max_dd < 0 and total_return is not None) else None

    return PerformanceMetrics(
        n_trades=n, win_rate=win_rate, avg_win=avg_win, avg_loss=avg_loss,
        expectancy=expectancy, profit_factor=profit_factor, sharpe=sharpe,
        sortino=sortino, max_drawdown=max_dd, calmar=calmar,
        avg_holding_period_weeks=float(holding_period_weeks),
    )
