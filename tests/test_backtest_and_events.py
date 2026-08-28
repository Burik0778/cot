import unittest
import numpy as np
import pandas as pd

from src.backtest.conditions import evaluate_condition, UnsafeConditionError
from src.backtest.metrics import compute_performance
from src.backtest.walkforward import split_folds
from src.backtest.engine import run_backtest
from src.events.event_study import run_event_study


class TestConditions(unittest.TestCase):
    def test_simple_condition_matches_expected_rows(self):
        df = pd.DataFrame({"pct": [5, 50, 95], "chg": [1, -1, 1]})
        mask = evaluate_condition(df, "pct < 10 and chg > 0")
        self.assertListEqual(mask.tolist(), [True, False, False])

    def test_unknown_column_raises_value_error_not_silent_empty(self):
        df = pd.DataFrame({"pct": [5, 50, 95]})
        with self.assertRaises(ValueError):
            evaluate_condition(df, "nonexistent_column > 10")

    def test_forbidden_token_is_rejected(self):
        df = pd.DataFrame({"pct": [5]})
        with self.assertRaises(UnsafeConditionError):
            evaluate_condition(df, "__import__('os').system('echo hi')")


class TestPerformanceMetrics(unittest.TestCase):
    def test_all_winners_gives_zero_drawdown_and_infinite_profit_factor(self):
        r = pd.Series([0.01, 0.02, 0.01, 0.03])
        perf = compute_performance(r, holding_period_weeks=4)
        self.assertEqual(perf.n_trades, 4)
        self.assertEqual(perf.win_rate, 1.0)
        self.assertEqual(perf.max_drawdown, 0.0)
        self.assertEqual(perf.profit_factor, float("inf"))

    def test_expectancy_matches_mean(self):
        r = pd.Series([0.02, -0.01, 0.03, -0.02, 0.0])
        perf = compute_performance(r, holding_period_weeks=4)
        self.assertAlmostEqual(perf.expectancy, r.mean())

    def test_empty_series_does_not_crash(self):
        perf = compute_performance(pd.Series([], dtype=float), holding_period_weeks=4)
        self.assertEqual(perf.n_trades, 0)
        self.assertIsNone(perf.win_rate)


class TestWalkForward(unittest.TestCase):
    def test_flags_edge_that_disappears_in_latest_fold(self):
        dates = pd.date_range("2015-01-01", periods=40, freq="7D")
        returns = [0.02] * 30 + [-0.01] * 10  # great early, bad recently
        df = pd.DataFrame({"d": dates, "r": returns})
        result = split_folds(df, "d", "r", n_folds=4)
        self.assertIsNotNone(result.overfitting_warning)

    def test_consistent_edge_across_folds_gives_no_warning(self):
        dates = pd.date_range("2015-01-01", periods=40, freq="7D")
        rng = np.random.default_rng(0)
        returns = rng.normal(0.01, 0.001, size=40)
        df = pd.DataFrame({"d": dates, "r": returns})
        result = split_folds(df, "d", "r", n_folds=4)
        self.assertIsNone(result.overfitting_warning)

    def test_too_few_trades_is_labeled_not_silently_split(self):
        df = pd.DataFrame({"d": pd.date_range("2015-01-01", periods=5, freq="7D"), "r": [0.01] * 5})
        result = split_folds(df, "d", "r", n_folds=4)
        self.assertEqual(result.folds, [])
        self.assertIsNotNone(result.overfitting_warning)


class TestBacktestEngine(unittest.TestCase):
    def _states(self):
        n = 60
        dates = pd.date_range("2015-01-06", periods=n, freq="7D").date
        rng = np.random.default_rng(3)
        pct = rng.uniform(0, 100, n)
        fwd = np.where(pct < 10, rng.normal(0.02, 0.01, n), rng.normal(0.0, 0.01, n))
        df = pd.DataFrame({"report_date": dates, "leveraged_funds_pct_52w": pct, "fwd_return_4w": fwd})
        df.loc[n - 2:, "fwd_return_4w"] = np.nan  # last 2 signals "not matured yet"
        return df

    def test_backtest_separates_matured_from_open(self):
        states = self._states()
        result = run_backtest(states, "EUR", "leveraged_funds_pct_52w < 10", horizon_weeks=4)
        self.assertEqual(result.n_signals_total, (states["leveraged_funds_pct_52w"] < 10).sum())
        self.assertLessEqual(result.n_matured, result.n_signals_total)
        self.assertEqual(result.n_matured + result.n_still_open, result.n_signals_total)

    def test_short_currency_direction_flips_sign(self):
        states = pd.DataFrame({
            "report_date": pd.date_range("2015-01-06", periods=5, freq="7D").date,
            "cond": [True] * 5,
            "fwd_return_4w": [0.01, 0.02, -0.01, 0.03, -0.02],
        })
        long_r = run_backtest(states, "EUR", "cond == True", horizon_weeks=4, direction="long_currency")
        short_r = run_backtest(states, "EUR", "cond == True", horizon_weeks=4, direction="short_currency")
        self.assertAlmostEqual(long_r.performance.expectancy, -short_r.performance.expectancy)

    def test_transaction_cost_reduces_expectancy(self):
        states = pd.DataFrame({
            "report_date": pd.date_range("2015-01-06", periods=5, freq="7D").date,
            "cond": [True] * 5,
            "fwd_return_4w": [0.01, 0.02, 0.01, 0.03, 0.02],
        })
        free = run_backtest(states, "EUR", "cond == True", horizon_weeks=4, cost_bps=0)
        costly = run_backtest(states, "EUR", "cond == True", horizon_weeks=4, cost_bps=50)
        self.assertLess(costly.performance.expectancy, free.performance.expectancy)


class TestEventStudy(unittest.TestCase):
    def test_event_study_summarizes_only_matured_horizons(self):
        n = 20
        dates = pd.date_range("2015-01-06", periods=n, freq="7D").date
        df = pd.DataFrame({
            "report_date": dates,
            "flag": [True, False] * 10,
            "fwd_return_1w": np.linspace(0.01, 0.02, n),
            "fwd_return_4w": [np.nan] * n,  # nothing matured at this horizon
        })
        result = run_event_study(df, df["flag"], horizons_weeks=[1, 4])
        self.assertEqual(result.n_events, 10)
        self.assertIsNotNone(result.mean_cumulative_return[1])
        self.assertIsNone(result.mean_cumulative_return[4])


if __name__ == "__main__":
    unittest.main()
