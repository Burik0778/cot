"""
src/analogs/validity.py

Spec section 17: statistics must be load-bearing, not decorative. This
module supplies:
  - bootstrap confidence interval for the median return of a sample
  - binomial test for win rate vs. a reference probability (e.g. base rate)
  - permutation test for mean return vs. an unconditional population
  - Cohen's d effect size between two samples

And the hard rule from the spec: N < MIN_SAMPLE_SIZE => everything downstream
must display "Insufficient sample size", not a confident-looking number. We
enforce this by having `assess` return that string directly instead of
statistics, rather than trusting every caller to remember to check N first.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from config.settings import MIN_SAMPLE_SIZE, BOOTSTRAP_ITERATIONS, BOOTSTRAP_CI, RANDOM_SEED


@dataclass
class ValidityAssessment:
    n: int
    sufficient: bool
    message: str
    bootstrap_ci_median: Optional[tuple[float, float]] = None
    binomial_p_value: Optional[float] = None
    permutation_p_value: Optional[float] = None
    effect_size_cohens_d: Optional[float] = None
    hypotheses_tested_this_session: Optional[int] = None
    multiple_testing_warning: Optional[str] = None


def bootstrap_ci_median(sample: pd.Series, iterations: int = BOOTSTRAP_ITERATIONS, ci: tuple[float, float] = BOOTSTRAP_CI, seed: int = RANDOM_SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = sample.dropna().to_numpy()
    boots = np.empty(iterations)
    n = len(values)
    for i in range(iterations):
        sample_i = values[rng.integers(0, n, size=n)]
        boots[i] = np.median(sample_i)
    lo, hi = np.percentile(boots, ci)
    return float(lo), float(hi)


def binomial_test_win_rate(n_wins: int, n_total: int, reference_p: float) -> float:
    """Two-sided p-value that the observed win rate differs from reference_p
    (e.g. the base rate) under a binomial null."""
    result = sp_stats.binomtest(n_wins, n_total, reference_p, alternative="two-sided")
    return float(result.pvalue)


def permutation_test_mean(sample_a: pd.Series, population_b: pd.Series, iterations: int = 2000, seed: int = RANDOM_SEED) -> float:
    """
    Empirical two-sided p-value for "sample_a's mean differs from a random
    same-size draw from population_b's mean", via random resampling from
    population_b (NOT a full label-shuffle permutation, since sample_a is a
    subset selected by a condition rather than a fixed-size partition of
    population_b -- this is the correct null for 'is this subset unusual
    relative to the population it was drawn from').
    """
    rng = np.random.default_rng(seed)
    a = sample_a.dropna().to_numpy()
    b = population_b.dropna().to_numpy()
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    observed = a.mean() - b.mean()
    null_diffs = np.empty(iterations)
    for i in range(iterations):
        draw = b[rng.integers(0, len(b), size=len(a))]
        null_diffs[i] = draw.mean() - b.mean()
    p_value = float(np.mean(np.abs(null_diffs) >= abs(observed)))
    return p_value


def cohens_d(sample_a: pd.Series, sample_b: pd.Series) -> Optional[float]:
    a, b = sample_a.dropna(), sample_b.dropna()
    if len(a) < 2 or len(b) < 2:
        return None
    pooled_std = np.sqrt(((len(a) - 1) * a.std(ddof=1) ** 2 + (len(b) - 1) * b.std(ddof=1) ** 2) / (len(a) + len(b) - 2))
    if pooled_std == 0:
        return None
    return float((a.mean() - b.mean()) / pooled_std)


def assess(
    analog_returns: pd.Series,
    base_population_returns: pd.Series,
    base_rate: Optional[float] = None,
    hypotheses_tested_this_session: Optional[int] = None,
) -> ValidityAssessment:
    r = analog_returns.dropna()
    n = len(r)

    if n < MIN_SAMPLE_SIZE:
        return ValidityAssessment(
            n=n, sufficient=False,
            message=f"Insufficient sample size (N={n}, minimum required is {MIN_SAMPLE_SIZE}). "
                    f"No statistical claim should be drawn from this many observations.",
            hypotheses_tested_this_session=hypotheses_tested_this_session,
        )

    ci = bootstrap_ci_median(r)
    binom_p = None
    if base_rate is not None:
        n_wins = int((r > 0).sum())
        binom_p = binomial_test_win_rate(n_wins, n, base_rate)
    perm_p = permutation_test_mean(r, base_population_returns)
    d = cohens_d(r, base_population_returns.dropna())

    mt_warning = None
    if hypotheses_tested_this_session and hypotheses_tested_this_session > 20:
        mt_warning = (
            f"You have tested {hypotheses_tested_this_session} conditions in this session. "
            f"With many conditions tested, some will look significant by chance alone "
            f"(potential multiple-testing / data-snooping bias) -- treat any single "
            f"p-value here as weaker evidence than it would be in isolation, and prefer "
            f"walk-forward / out-of-sample confirmation."
        )

    return ValidityAssessment(
        n=n, sufficient=True,
        message=f"N={n} ({_quality_label(n)}).",
        bootstrap_ci_median=ci,
        binomial_p_value=binom_p,
        permutation_p_value=perm_p,
        effect_size_cohens_d=d,
        hypotheses_tested_this_session=hypotheses_tested_this_session,
        multiple_testing_warning=mt_warning,
    )


def _quality_label(n: int) -> str:
    if n < 30:
        return "low confidence"
    if n < 50:
        return "moderate confidence"
    return "good sample size"
