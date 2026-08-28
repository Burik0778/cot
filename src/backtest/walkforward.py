"""
src/backtest/walkforward.py

Spec sections 18, 46. This is NOT a parameter-optimization walk-forward
(the platform does not auto-tune regime/analog thresholds against
history) -- it is a simpler, honestly-scoped check: split a condition's
matured trade history into K chronological folds, and see whether the
edge is consistent across folds or concentrated in one early period. A
big drop from the earliest fold(s) to the latest fold is exactly the
in-sample-much-better-than-out-of-sample pattern the spec's overfitting
warning is about.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

from config.settings import WALK_FORWARD_FOLDS


@dataclass
class FoldResult:
    fold_index: int
    n: int
    win_rate: float | None
    mean_return: float | None
    start_date: str
    end_date: str


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    overfitting_warning: str | None


def split_folds(trades: pd.DataFrame, date_col: str, return_col: str, n_folds: int = WALK_FORWARD_FOLDS) -> WalkForwardResult:
    df = trades.dropna(subset=[return_col]).sort_values(date_col).reset_index(drop=True)
    if len(df) < n_folds * 5:
        return WalkForwardResult(folds=[], overfitting_warning="Too few matured trades to split into meaningful walk-forward folds.")

    fold_edges = np.array_split(df.index, n_folds)
    folds = []
    for i, idx in enumerate(fold_edges):
        sub = df.loc[idx]
        r = sub[return_col]
        folds.append(FoldResult(
            fold_index=i + 1, n=len(sub),
            win_rate=float((r > 0).mean()) if len(r) else None,
            mean_return=float(r.mean()) if len(r) else None,
            start_date=str(sub[date_col].iloc[0]), end_date=str(sub[date_col].iloc[-1]),
        ))

    warning = None
    first, last = folds[0], folds[-1]
    if first.mean_return is not None and last.mean_return is not None:
        if first.mean_return > 0 and last.mean_return <= 0:
            warning = (
                f"Fold 1 ({first.start_date}..{first.end_date}) mean return "
                f"{first.mean_return:.4%} vs fold {last.fold_index} "
                f"({last.start_date}..{last.end_date}) mean return {last.mean_return:.4%}: "
                f"the edge does not persist into the most recent fold. Treat the "
                f"full-sample result as likely overfit to the earlier period."
            )
    return WalkForwardResult(folds=folds, overfitting_warning=warning)
