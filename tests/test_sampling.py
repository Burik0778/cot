import unittest
import numpy as np
import pandas as pd
from src.analogs.sampling import (
    SamplingMode, non_overlapping_index, effective_n, block_bootstrap_ci,
    iid_bootstrap_ci, summarize, summarize_all_modes, quality_label,
)


def _returns(n=200, seed=0, autocorr=0.0):
    rng = np.random.default_rng(seed)
    v = rng.normal(0.005, 0.02, n)
    if autocorr:
        for i in range(1, n):
            v[i] = autocorr * v[i - 1] + (1 - autocorr) * v[i]
    return pd.Series(v)


class TestNonOverlapping(unittest.TestCase):
    def test_takes_every_hth_observation(self):
        idx = pd.RangeIndex(20)
        self.assertListEqual(list(non_overlapping_index(idx, 8)), [0, 8, 16])

    def test_horizon_one_keeps_everything(self):
        idx = pd.RangeIndex(10)
        self.assertEqual(len(non_overlapping_index(idx, 1)), 10)

    def test_reduces_sample_as_expected(self):
        r = _returns(160)
        s = summarize(r, 8, SamplingMode.NON_OVERLAP)
        self.assertEqual(s.raw_n, 160)
        self.assertEqual(s.used_n, 20)          # 160 / 8


class TestEffectiveN(unittest.TestCase):
    def test_divides_by_horizon(self):
        self.assertEqual(effective_n(160, 8), 20)

    def test_horizon_one_is_unchanged(self):
        self.assertEqual(effective_n(100, 1), 100)

    def test_never_below_one(self):
        self.assertEqual(effective_n(3, 26), 1)


class TestBootstrap(unittest.TestCase):
    def test_block_ci_is_wider_than_iid_on_autocorrelated_data(self):
        """Смысл блочного бутстрапа: на зависимых данных обычный даёт
        слишком узкий интервал. Если блочный не шире — он бесполезен."""
        r = _returns(400, seed=3, autocorr=0.85)
        iid = iid_bootstrap_ci(r, "median")
        blk = block_bootstrap_ci(r, 8, "median")
        self.assertIsNotNone(iid); self.assertIsNotNone(blk)
        self.assertGreater(blk[1] - blk[0], (iid[1] - iid[0]) * 0.95)

    def test_ci_brackets_the_point_estimate(self):
        r = _returns(300, seed=5)
        lo, hi = block_bootstrap_ci(r, 8, "median")
        self.assertLessEqual(lo, r.median())
        self.assertGreaterEqual(hi, r.median())

    def test_win_rate_ci_within_zero_one(self):
        r = _returns(300, seed=6)
        lo, hi = block_bootstrap_ci(r, 8, "win_rate")
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)

    def test_too_small_sample_returns_none(self):
        self.assertIsNone(block_bootstrap_ci(pd.Series([0.01, 0.02]), 8))

    def test_deterministic_with_fixed_seed(self):
        r = _returns(200, seed=7)
        self.assertEqual(block_bootstrap_ci(r, 8), block_bootstrap_ci(r, 8))


class TestSummaries(unittest.TestCase):
    def test_raw_mode_warns_about_overlap(self):
        s = summarize(_returns(200), 8, SamplingMode.RAW)
        self.assertIn("перекрываются", s.note)
        self.assertLess(s.effective_n, s.raw_n)

    def test_non_overlap_mode_has_equal_used_and_effective(self):
        s = summarize(_returns(200), 8, SamplingMode.NON_OVERLAP)
        self.assertEqual(s.used_n, 25)

    def test_block_mode_names_its_method(self):
        s = summarize(_returns(200), 8, SamplingMode.BLOCK)
        self.assertIn("Блочный", s.ci_method)

    def test_all_modes_agree_on_point_estimates(self):
        """Режимы отличаются только оценкой неопределённости; сама
        медиана в raw и block обязана совпадать."""
        r = _returns(200)
        a = summarize(r, 8, SamplingMode.RAW)
        b = summarize(r, 8, SamplingMode.BLOCK)
        self.assertAlmostEqual(a.median_return, b.median_return)

    def test_quality_uses_effective_not_raw(self):
        s = summarize(_returns(200), 26, SamplingMode.RAW)
        self.assertEqual(s.effective_n, 8)
        self.assertEqual(s.quality, "Недостаточно")   # хотя сырых 200

    def test_summarize_all_modes_returns_three(self):
        self.assertEqual(len(summarize_all_modes(_returns(200), 8)), 3)

    def test_empty_input_is_handled(self):
        s = summarize(pd.Series([], dtype=float), 8, SamplingMode.RAW)
        self.assertEqual(s.used_n, 0)
        self.assertEqual(s.quality, "Недостаточно")


class TestQualityLabels(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(quality_label(5), "Недостаточно")
        self.assertEqual(quality_label(15), "Слабая")
        self.assertEqual(quality_label(30), "Умеренная")
        self.assertEqual(quality_label(60), "Хорошая")
        self.assertEqual(quality_label(200), "Сильная")


if __name__ == "__main__":
    unittest.main()
