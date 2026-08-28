import unittest
import numpy as np
import pandas as pd
from src.cot.percentile import rolling_percentile_excl_current, rolling_zscore_excl_current


class TestPercentileExcludesCurrent(unittest.TestCase):
    def test_hand_computed_example(self):
        # window=3, values: [1,2,3,10]. At t=3 (value=10), history is [1,2,3]
        # (t=0..2), NOT including 10 itself. percentileofscore(kind='mean')
        # of 10 vs [1,2,3] = 100 (strictly greater than all 3).
        s = pd.Series([1, 2, 3, 10])
        out = rolling_percentile_excl_current(s, window=3)
        self.assertTrue(pd.isna(out.iloc[0]))
        self.assertTrue(pd.isna(out.iloc[1]))
        self.assertTrue(pd.isna(out.iloc[2]))
        self.assertAlmostEqual(out.iloc[3], 100.0)

    def test_current_extreme_value_cannot_suppress_its_own_percentile(self):
        # If the current value were (incorrectly) included in its own
        # reference set, an extreme value could never reach the 100th
        # percentile (it would always be compared against itself too).
        # With correct exclusion, a new all-time-high MUST be able to hit
        # exactly 100.
        window = 52
        history = np.zeros(window)
        s = pd.Series(np.concatenate([history, [999.0]]))
        out = rolling_percentile_excl_current(s, window=window)
        self.assertEqual(out.iloc[-1], 100.0)

    def test_percentile_bounded_0_100(self):
        rng = np.random.default_rng(0)
        s = pd.Series(rng.normal(size=300))
        out = rolling_percentile_excl_current(s, window=52).dropna()
        self.assertTrue((out >= 0).all() and (out <= 100).all())

    def test_insufficient_history_is_nan_not_fabricated(self):
        s = pd.Series([1, 2, 3])
        out = rolling_percentile_excl_current(s, window=52)
        self.assertTrue(out.isna().all())


class TestZScoreExcludesCurrent(unittest.TestCase):
    def test_hand_computed_example(self):
        # window=3: mean/std computed over the 3 values BEFORE t, not
        # including t. values: [1,2,3,100]. At t=3: mean([1,2,3])=2,
        # std([1,2,3], ddof=1)=1. z = (100-2)/1 = 98.
        s = pd.Series([1, 2, 3, 100])
        out = rolling_zscore_excl_current(s, window=3)
        self.assertTrue(pd.isna(out.iloc[2]))  # only 2 prior obs, need 3
        self.assertAlmostEqual(out.iloc[3], 98.0)

    def test_zero_variance_window_gives_nan_not_divide_error(self):
        s = pd.Series([5, 5, 5, 5, 9])
        out = rolling_zscore_excl_current(s, window=4)
        self.assertTrue(pd.isna(out.iloc[4]))


if __name__ == "__main__":
    unittest.main()
