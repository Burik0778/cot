import unittest
import numpy as np
import pandas as pd
from datetime import date

from src.analogs.similarity import fit, find_analogs, LookaheadError
from src.analogs.outcomes import summarize_returns, compute_excursion
from src.analogs.baserate import compare_to_base_rate
from src.analogs.validity import assess, bootstrap_ci_median, binomial_test_win_rate, cohens_d


def _pool(n=100, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-06", periods=n, freq="7D").date
    return pd.DataFrame({
        "report_date": dates,
        "availability_date": [d for d in dates],  # same-day for simplicity in these unit tests
        "feat_a": rng.normal(size=n),
        "feat_b": rng.normal(size=n),
        "fwd_return_4w": rng.normal(scale=0.01, size=n),
    })


class TestAnalogEngineGuards(unittest.TestCase):
    def test_refuses_forward_return_as_feature(self):
        pool = _pool()
        with self.assertRaises(LookaheadError):
            fit(pool, {"feat_a": 1.0, "fwd_return_4w": 1.0})

    def test_refuses_pool_with_future_availability(self):
        pool = _pool()
        fitted = fit(pool, {"feat_a": 1.0, "feat_b": 1.0})
        future_pool = pool.copy()
        future_pool.loc[0, "availability_date"] = date(2999, 1, 1)
        fitted_bad = fit(future_pool, {"feat_a": 1.0, "feat_b": 1.0})
        with self.assertRaises(LookaheadError):
            find_analogs(fitted_bad, pool.iloc[-1], as_of_date=date(2020, 1, 1))

    def test_valid_pool_does_not_raise(self):
        pool = _pool()
        fitted = fit(pool, {"feat_a": 1.0, "feat_b": 1.0})
        results = find_analogs(fitted, pool.iloc[-1], as_of_date=date(2030, 1, 1))
        self.assertGreater(len(results), 0)


class TestSimilarityMath(unittest.TestCase):
    def test_identical_row_is_the_closest_match(self):
        pool = _pool(n=200)
        fitted = fit(pool, {"feat_a": 1.0, "feat_b": 1.0})
        query = pool.iloc[50].copy()
        results = find_analogs(fitted, query, as_of_date=date(2030, 1, 1), max_analogs=5)
        self.assertEqual(results[0].index, 50)
        self.assertAlmostEqual(results[0].distance, 0.0, places=6)
        self.assertAlmostEqual(results[0].similarity_score, 100.0, places=3)

    def test_distance_ordering_matches_similarity_ordering(self):
        pool = _pool(n=200)
        fitted = fit(pool, {"feat_a": 1.0, "feat_b": 0.5})
        results = find_analogs(fitted, pool.iloc[100], as_of_date=date(2030, 1, 1), max_analogs=20)
        distances = [r.distance for r in results]
        similarities = [r.similarity_score for r in results]
        self.assertEqual(distances, sorted(distances))
        self.assertEqual(similarities, sorted(similarities, reverse=True))

    def test_feature_weight_of_zero_ignores_that_feature(self):
        pool = _pool(n=100)
        pool["feat_c_irrelevant"] = np.random.default_rng(1).normal(size=100) * 1000  # huge scale, weight 0
        fitted = fit(pool, {"feat_a": 1.0, "feat_c_irrelevant": 0.0})
        query = pool.iloc[10].copy()
        results = find_analogs(fitted, query, as_of_date=date(2030, 1, 1), max_analogs=1)
        self.assertEqual(results[0].index, 10)


class TestOutcomesAndBaseRate(unittest.TestCase):
    def test_summarize_returns_basic_stats(self):
        r = pd.Series([0.01, 0.02, -0.01, 0.03, np.nan])
        stats = summarize_returns(r, horizon_weeks=4)
        self.assertEqual(stats.n, 4)
        self.assertAlmostEqual(stats.win_rate, 0.75)
        self.assertAlmostEqual(stats.mean_return, np.mean([0.01, 0.02, -0.01, 0.03]))

    def test_insufficient_sample_is_labeled(self):
        r = pd.Series([0.01, 0.02])
        stats = summarize_returns(r, horizon_weeks=4)
        self.assertEqual(stats.sample_quality, "Insufficient sample size")

    def test_base_rate_diff_is_computed_correctly(self):
        all_states = pd.DataFrame({"fwd_return_8w": [0.01, -0.01, 0.02, -0.02, 0.0, 0.03] * 10})  # win rate 50%
        analog_returns = pd.Series([0.01, 0.02, 0.03, 0.01, -0.01])  # win rate 80%
        cmp = compare_to_base_rate(analog_returns, all_states, 8, "fwd_return_8w")
        self.assertAlmostEqual(cmp.analog_rate.win_rate, 0.8)
        self.assertAlmostEqual(cmp.win_rate_diff_pp, 30.0, places=3)

    def test_excursion_uses_daily_path_not_endpoints(self):
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=15, freq="D").date,
            "close": [100, 101, 99, 105, 98, 100, 100, 100, 100, 100, 100, 100, 100, 100, 103],
        })
        mfe, mae = compute_excursion(daily, date(2024, 1, 1), horizon_weeks=1, currency="EUR")
        self.assertAlmostEqual(mfe, 0.05)     # peak at 105 -> +5%
        self.assertAlmostEqual(mae, -0.02)    # trough at 98 -> -2%


class TestValidity(unittest.TestCase):
    def test_below_min_sample_returns_insufficient_message_not_stats(self):
        result = assess(pd.Series([0.01, 0.02, 0.03]), pd.Series(np.random.normal(size=200)))
        self.assertFalse(result.sufficient)
        self.assertIn("Insufficient sample size", result.message)
        self.assertIsNone(result.bootstrap_ci_median)

    def test_sufficient_sample_produces_ci_and_tests(self):
        rng = np.random.default_rng(1)
        analogs = pd.Series(rng.normal(0.02, 0.01, size=40))
        base = pd.Series(rng.normal(0.0, 0.01, size=500))
        result = assess(analogs, base, base_rate=0.5, hypotheses_tested_this_session=3)
        self.assertTrue(result.sufficient)
        self.assertIsNotNone(result.bootstrap_ci_median)
        self.assertLess(result.bootstrap_ci_median[0], result.bootstrap_ci_median[1])
        self.assertIsNotNone(result.effect_size_cohens_d)
        self.assertIsNone(result.multiple_testing_warning)  # only 3 tested

    def test_many_hypotheses_triggers_multiple_testing_warning(self):
        rng = np.random.default_rng(1)
        analogs = pd.Series(rng.normal(0.0, 0.01, size=40))
        base = pd.Series(rng.normal(0.0, 0.01, size=500))
        result = assess(analogs, base, hypotheses_tested_this_session=250)
        self.assertIsNotNone(result.multiple_testing_warning)

    def test_bootstrap_ci_contains_true_median_with_clean_data(self):
        sample = pd.Series(np.full(500, 0.02))
        lo, hi = bootstrap_ci_median(sample)
        self.assertAlmostEqual(lo, 0.02)
        self.assertAlmostEqual(hi, 0.02)

    def test_binomial_test_matches_scipy_directly(self):
        from scipy import stats as sp_stats
        expected = sp_stats.binomtest(30, 40, 0.5, alternative="two-sided").pvalue
        got = binomial_test_win_rate(30, 40, 0.5)
        self.assertAlmostEqual(expected, got)

    def test_cohens_d_zero_for_identical_distributions_shape(self):
        rng = np.random.default_rng(2)
        a = pd.Series(rng.normal(0, 1, 1000))
        b = pd.Series(rng.normal(0, 1, 1000))
        d = cohens_d(a, b)
        self.assertLess(abs(d), 0.2)  # should be small, not exactly 0 due to sampling


if __name__ == "__main__":
    unittest.main()
