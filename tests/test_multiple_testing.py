import unittest
import numpy as np
from datetime import date
from src.analogs.multiple_testing import (
    benjamini_hochberg, snooping_warning, assess_run, Hypothesis, ResearchMode,
)


class TestBenjaminiHochberg(unittest.TestCase):
    def test_no_rejections_on_uniform_noise(self):
        rng = np.random.default_rng(0)
        p = list(rng.uniform(0, 1, 500))
        self.assertLessEqual(benjamini_hochberg(p)["n_rejected"], 25)

    def test_strong_signals_are_rejected(self):
        p = [0.0001, 0.0002, 0.0003] + [0.6] * 50
        self.assertGreaterEqual(benjamini_hochberg(p)["n_rejected"], 3)

    def test_is_less_strict_than_bonferroni(self):
        p = [0.001] * 10 + [0.5] * 90
        bh = benjamini_hochberg(p)["n_rejected"]
        bonf = sum(1 for x in p if x <= 0.05 / 100)
        self.assertGreaterEqual(bh, bonf)

    def test_handles_empty_and_nan(self):
        self.assertEqual(benjamini_hochberg([])["m"], 0)
        self.assertEqual(benjamini_hochberg([float("nan"), None])["m"], 0)

    def test_returns_indices_into_original_list(self):
        p = [0.9, 0.0001, 0.8]
        self.assertIn(1, benjamini_hochberg(p)["rejected"])


class TestSnoopingWarning(unittest.TestCase):
    def test_single_test_no_warning(self):
        self.assertIsNone(snooping_warning(1))

    def test_counts_expected_false_positives(self):
        self.assertIn("100", snooping_warning(2000))

    def test_large_run_gets_stronger_language(self):
        self.assertIn("подгонки", snooping_warning(50))

    def test_mentions_bonferroni_when_best_p_fails_it(self):
        self.assertIn("Бонферрони", snooping_warning(100, best_p=0.04))


class TestResearchModes(unittest.TestCase):
    def test_discovery_never_confirms(self):
        r = assess_run([0.0001] * 5, ResearchMode.DISCOVERY)
        self.assertIn("не считается подтверждённым", r["verdict"])

    def test_confirmatory_states_prefixed_hypothesis(self):
        r = assess_run([0.01], ResearchMode.CONFIRMATORY)
        self.assertIn("зафиксирована до просмотра", r["verdict"])

    def test_freeze_records_train_end_and_switches_mode(self):
        h = Hypothesis("R-2026-001", "lf_pct < 10", "EUR", 8)
        self.assertEqual(h.mode, ResearchMode.DISCOVERY.value)
        h.freeze(date(2024, 1, 1), prior_tests=37)
        self.assertEqual(h.mode, ResearchMode.CONFIRMATORY.value)
        self.assertEqual(h.train_end, "2024-01-01")
        self.assertEqual(h.prior_tests_when_created, 37)
        self.assertTrue(h.frozen_at)

    def test_assess_run_reports_test_count(self):
        self.assertEqual(assess_run([0.1] * 42, ResearchMode.DISCOVERY)["n_tests"], 42)


if __name__ == "__main__":
    unittest.main()
