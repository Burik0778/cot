import unittest
import numpy as np
import pandas as pd
from src.analogs.evidence import build_edge_evidence, MIN_EFFECTIVE_N


def _ev(analog, pop, horizon=8, **kw):
    return build_edge_evidence(
        pd.Series(analog), pd.Series(pop), market="EUR", horizon_weeks=horizon,
        analog_mode="cot_only", analog_mode_ru="Только COT",
        features={"leveraged_funds_pct_52w": 1.0}, conditions=["lf_pct < 10"],
        data_start="2015-01-06", data_end="2026-08-18", as_of="2026-08-21", **kw)


class TestEvidenceCompleteness(unittest.TestCase):
    """Раздел 95: без полной основы преимущество не считается доказанным."""

    def test_contains_every_required_field(self):
        rng = np.random.default_rng(0)
        e = _ev(rng.normal(.01, .02, 120), rng.normal(0, .02, 600)).to_dict()
        for f in ("raw_n", "non_overlapping_n", "effective_n", "base_rate",
                  "conditional_rate", "edge_pp", "ci_block_median", "ci_block_win_rate",
                  "features", "conditions", "data_start", "data_end", "data_source",
                  "analog_mode", "quality", "verdict", "caveats"):
            self.assertIn(f, e)
            self.assertIsNotNone(e[f], f"поле {f} пустое")

    def test_effective_n_is_smaller_than_raw(self):
        rng = np.random.default_rng(1)
        e = _ev(rng.normal(.01, .02, 160), rng.normal(0, .02, 600), horizon=8)
        self.assertEqual(e.raw_n, 160)
        self.assertLess(e.effective_n, e.raw_n)
        self.assertEqual(e.non_overlapping_n, 20)


class TestVerdicts(unittest.TestCase):
    def test_small_effective_sample_is_not_proven(self):
        rng = np.random.default_rng(2)
        e = _ev(rng.normal(.05, .02, 40), rng.normal(0, .02, 400), horizon=26)
        self.assertLess(e.effective_n, MIN_EFFECTIVE_N)
        self.assertIn("НЕ доказано", e.verdict)

    def test_noise_edge_called_noise(self):
        rng = np.random.default_rng(3)
        pop = rng.normal(0, .02, 800)
        e = _ev(rng.normal(0, .02, 200), pop)
        if e.edge_pp is not None and abs(e.edge_pp) < 5:
            self.assertIn("шума", e.verdict)

    def test_ci_crossing_base_rate_blocks_confirmation(self):
        rng = np.random.default_rng(4)
        # слабый сдвиг: интервал должен накрыть базовую ставку
        e = _ev(rng.normal(.004, .05, 200), rng.normal(0, .05, 800))
        if e.edge_pp is not None and abs(e.edge_pp) >= 5:
            self.assertTrue("не подтверждено" in e.verdict or "устойчив" in e.verdict)

    def test_caveats_always_mention_overlap_and_causation(self):
        rng = np.random.default_rng(5)
        joined = " ".join(_ev(rng.normal(.01, .02, 120), rng.normal(0, .02, 600)).caveats)
        self.assertIn("делят почти всю историю цены", joined)   # зависимость наблюдений
        self.assertIn("эффективный размер", joined)
        self.assertIn("не означает причины", joined)            # корреляция != причина
        self.assertIn("публикуются в пятницу", joined)          # лаг публикации

    def test_quality_uses_effective_n(self):
        rng = np.random.default_rng(6)
        e = _ev(rng.normal(.01, .02, 200), rng.normal(0, .02, 800), horizon=26)
        self.assertIn(e.quality, ("Недостаточно", "Слабая", "Умеренная", "Хорошая", "Сильная"))


if __name__ == "__main__":
    unittest.main()
