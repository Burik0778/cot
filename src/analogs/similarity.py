"""
src/analogs/similarity.py

Historical Analog Engine (spec sections 12-14) -- the central function of
the platform.

Method (documented, not a black box):
1. Features are standardized (z-scored) using ONLY the reference pool the
   caller supplies (see `fit`) -- never re-standardized per-query in a way
   that would leak the query's own value into the scale.
2. Distance between the current state and each historical row is a
   WEIGHTED EUCLIDEAN distance over those standardized features.
3. That raw distance is reported directly (`distance`) -- this is the
   honest, always-defensible number.
4. A bounded "similarity score" in [0, 100] is ALSO reported, as a
   documented, reproducible monotonic transform of distance:
       similarity = 100 * exp(-distance / scale)
   `scale` is the RMS distance across the whole reference pool, so the
   transform is self-calibrating to how spread out history actually is,
   and is written into every result so it can be checked. This is a
   heuristic presentation layer on top of (3), not a probability -- see
   METHODOLOGY.md. We do NOT claim 94.2%-style spurious precision without
   this documented method behind it (spec section 14).

No-look-ahead guards enforced HERE, not left to the caller:
- The reference pool passed to `find_analogs` must already be restricted to
  rows with availability_date <= as_of_date (raises if it detects a
  violation).
- Forward-return / outcome columns are refused as similarity features --
  matching analogs partly on their own future outcome is a subtler form of
  look-ahead (label leakage) than a plain date violation, and the spec's
  "no look-ahead" principle (section 19) covers this too.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
import numpy as np
import pandas as pd


FORBIDDEN_FEATURE_PREFIXES = ("fwd_return_",)


class LookaheadError(RuntimeError):
    pass


def _assert_features_are_not_outcomes(feature_names: list[str]) -> None:
    bad = [f for f in feature_names if f.startswith(FORBIDDEN_FEATURE_PREFIXES)]
    if bad:
        raise LookaheadError(
            f"Refusing to use forward-return columns as analog-matching features "
            f"(this leaks the outcome into the match): {bad}"
        )


def _assert_pool_is_available(pool: pd.DataFrame, as_of_date: date, availability_col: str = "availability_date") -> None:
    if availability_col not in pool.columns:
        return
    future_rows = pool[pd.to_datetime(pool[availability_col]).dt.date > as_of_date]
    if len(future_rows) > 0:
        raise LookaheadError(
            f"Reference pool contains {len(future_rows)} row(s) with availability_date "
            f"after as_of_date={as_of_date}. The caller must filter these out before "
            f"calling find_analogs -- the analog engine refuses to silently drop them "
            f"for you, since that filtering is exactly the kind of thing that must be "
            f"visible and auditable, not implicit."
        )


@dataclass
class AnalogFit:
    feature_names: list[str]
    weights: np.ndarray
    means: pd.Series
    stds: pd.Series
    pool: pd.DataFrame
    rms_distance: float


@dataclass
class AnalogResult:
    index: object
    report_date: str
    distance: float
    similarity_score: float
    per_feature_distance: dict = field(default_factory=dict)


def fit(pool: pd.DataFrame, feature_weights: dict[str, float]) -> AnalogFit:
    """
    `pool` is the full eligible historical reference set (already
    availability-filtered by the caller). Standardizes each feature using
    this pool's own mean/std.
    """
    feature_names = list(feature_weights.keys())
    _assert_features_are_not_outcomes(feature_names)
    missing = [f for f in feature_names if f not in pool.columns]
    if missing:
        raise KeyError(f"Requested analog features not present in pool: {missing}")

    means = pool[feature_names].astype(float).mean()
    stds = pool[feature_names].astype(float).std(ddof=1).replace(0, np.nan)
    weights = np.array([feature_weights[f] for f in feature_names])

    standardized = (pool[feature_names].astype(float) - means) / stds
    weighted_sq = (standardized ** 2) * (weights ** 2)
    valid_rows = standardized.dropna().index
    rms_distance = float(np.sqrt(weighted_sq.loc[valid_rows].sum(axis=1).mean())) if len(valid_rows) else 1.0
    rms_distance = rms_distance or 1.0

    return AnalogFit(feature_names, weights, means, stds, pool, rms_distance)


def find_analogs(
    fitted: AnalogFit,
    current_state: pd.Series,
    as_of_date: date,
    max_analogs: int = 40,
    exclude_index: object = None,
) -> list[AnalogResult]:
    """
    Ranks `fitted.pool` by weighted standardized distance to `current_state`.
    Enforces no-lookahead on the pool (see module docstring) before doing
    anything else.
    """
    _assert_pool_is_available(fitted.pool, as_of_date)

    x = (current_state[fitted.feature_names].astype(float) - fitted.means) / fitted.stds
    pool_std = (fitted.pool[fitted.feature_names].astype(float) - fitted.means) / fitted.stds

    diff_sq = (pool_std - x) ** 2
    weighted = diff_sq * (fitted.weights ** 2)
    total_sq = weighted.sum(axis=1, skipna=False)
    distances = np.sqrt(total_sq)

    results = []
    for idx in fitted.pool.index:
        if idx == exclude_index:
            continue
        d = distances.loc[idx]
        if pd.isna(d):
            continue
        similarity = 100.0 * np.exp(-d / fitted.rms_distance)
        per_feat = {f: float(weighted.loc[idx, f]) ** 0.5 for f in fitted.feature_names if not pd.isna(weighted.loc[idx, f])}
        results.append(AnalogResult(
            index=idx,
            report_date=str(fitted.pool.loc[idx].get("report_date", idx)),
            distance=float(d),
            similarity_score=float(similarity),
            per_feature_distance=per_feat,
        ))

    results.sort(key=lambda r: r.distance)
    return results[:max_analogs]
