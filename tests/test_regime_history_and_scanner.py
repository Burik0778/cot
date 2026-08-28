import unittest
import numpy as np
import pandas as pd
from src.cot.regime_history import compute_regime_history
from src.scanner.scanner import scan, scanner_to_dataframe


def _states(n=200, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-06", periods=n, freq="7D").date
    regimes = rng.choice(["Bullish Positioning", "Bearish Positioning", "Neutral"], size=n, p=[0.3, 0.3, 0.4])
    fwd = rng.normal(0.0, 0.01, n)
    fwd[regimes == "Bullish Positioning"] += 0.01  # engineered edge for testing
    df = pd.DataFrame({
        "report_date": dates, "regime": regimes, "fwd_return_8w": fwd,
        "leveraged_funds_net_oi": rng.normal(0, 0.2, n),
        "leveraged_funds_pct_52w": rng.uniform(0, 100, n),
        "leveraged_funds_chg_4w": rng.normal(0, 100, n),
        "asset_manager_net_oi": rng.normal(0, 0.2, n),
        "asset_manager_pct_52w": rng.uniform(0, 100, n),
    })
    df.loc[n - 3:, "fwd_return_8w"] = np.nan
    return df


class TestRegimeHistory(unittest.TestCase):
    def test_excludes_current_row_from_its_own_history(self):
        df = _states()
        df.loc[df.index[-1], "regime"] = "Neutral"
        hist = compute_regime_history(df, "Neutral", [8])
        # the current (last) row must not count itself
        self.assertNotIn(str(df["report_date"].iloc[-1]), []) # sanity no-op
        all_neutral = (df["regime"] == "Neutral").sum()
        self.assertEqual(hist.occurrences, all_neutral - 1)

    def test_finds_engineered_edge_for_bullish_positioning(self):
        df = _states(n=2000)
        hist = compute_regime_history(df, "Bullish Positioning", [8])
        cmp = hist.comparisons[8]
        self.assertGreater(cmp.win_rate_diff_pp, 0)

    def test_episode_durations_computed_correctly(self):
        df = pd.DataFrame({
            "report_date": pd.date_range("2015-01-06", periods=7, freq="7D").date,
            "regime": ["A", "A", "B", "A", "A", "A", "B"],
            "fwd_return_4w": [0.01] * 7,
        })
        hist = compute_regime_history(df, "A", [4], exclude_latest=False)
        # runs of A: length 2, then length 3 -> median duration 2.5
        self.assertAlmostEqual(hist.median_duration_weeks, 2.5)


class TestScanner(unittest.TestCase):
    def test_scan_produces_one_row_per_currency(self):
        data = {"EUR": _states(seed=1), "GBP": _states(seed=2)}
        rows = scan(data, horizon_weeks=8)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r.currency for r in rows}, {"EUR", "GBP"})

    def test_scanner_dataframe_sorted_by_edge(self):
        data = {"EUR": _states(seed=1), "GBP": _states(seed=2)}
        rows = scan(data, horizon_weeks=8)
        df = scanner_to_dataframe(rows)
        edges = df["edge_pp"].dropna().tolist()
        self.assertEqual(edges, sorted(edges, reverse=True))

    def test_empty_states_are_skipped_not_crashing(self):
        data = {"EUR": _states(), "GBP": pd.DataFrame()}
        rows = scan(data, horizon_weeks=8)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
