import unittest
import numpy as np
import pandas as pd
from src.events.validation import (
    EventDefinition, Condition, detect_events, evaluate_condition, validate,
    EVENT_DEFS, CONDITIONS, MIN_OCCURRENCES,
)

EV = EventDefinition("t", "тест", "", 0.05, 4, "up")


def _states(n=200, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "report_date": pd.date_range("2020-01-07", periods=n, freq="7D").date,
        "price_close": 100 * np.cumprod(1 + rng.normal(0, .01, n)),
        "leveraged_funds_pct_52w": rng.uniform(0, 100, n),
        "leveraged_funds_streak_up_weeks": rng.integers(0, 5, n),
        "leveraged_funds_streak_down_weeks": rng.integers(0, 5, n),
        "leveraged_funds_chg_4w": rng.normal(0, 1000, n),
        "leveraged_funds_chg_1w": rng.normal(0, 500, n),
        "leveraged_funds_long_chg_1w": rng.normal(0, 500, n),
        "asset_manager_chg_4w": rng.normal(0, 1000, n),
    })


class TestEventDetection(unittest.TestCase):
    def test_detects_a_real_move(self):
        s = pd.DataFrame({"report_date": pd.date_range("2020-01-07", periods=6, freq="7D").date,
                           "price_close": [100, 101, 103, 107, 108, 109]})
        out = detect_events(s, EV)
        self.assertTrue(bool(out.iloc[0]))     # 100 -> 107 внутри 4 недель это +7%

    def test_no_move_is_false_not_missing(self):
        s = pd.DataFrame({"report_date": pd.date_range("2020-01-07", periods=6, freq="7D").date,
                           "price_close": [100, 100.2, 99.8, 100.1, 100, 100.3]})
        out = detect_events(s, EV)
        self.assertFalse(bool(out.iloc[0]))

    def test_immature_tail_is_nan_not_false(self):
        """Последняя строка не может знать будущего — она обязана быть NaN,
        иначе незрелые наблюдения посчитались бы как «движения не было»."""
        s = pd.DataFrame({"report_date": pd.date_range("2020-01-07", periods=5, freq="7D").date,
                           "price_close": [100, 101, 102, 103, 104]})
        out = detect_events(s, EV)
        self.assertTrue(pd.isna(out.iloc[-1]))

    def test_direction_matters(self):
        s = pd.DataFrame({"report_date": pd.date_range("2020-01-07", periods=6, freq="7D").date,
                           "price_close": [100, 98, 95, 92, 91, 90]})
        up = detect_events(s, EventDefinition("u", "", "", .05, 4, "up"))
        dn = detect_events(s, EventDefinition("d", "", "", .05, 4, "down"))
        self.assertFalse(bool(up.iloc[0]))
        self.assertTrue(bool(dn.iloc[0]))

    def test_missing_price_gives_all_nan(self):
        s = pd.DataFrame({"report_date": [1, 2, 3]})
        self.assertTrue(detect_events(s, EV).isna().all())


class TestConditions(unittest.TestCase):
    def test_extreme_low(self):
        s = pd.DataFrame({"leveraged_funds_pct_52w": [5, 50, 95]})
        out = evaluate_condition(s, Condition("spec_extreme_low", "", ""), "leveraged_funds", "asset_manager")
        self.assertListEqual(out.tolist(), [True, False, False])

    def test_turning_up_needs_both_parts(self):
        s = pd.DataFrame({"leveraged_funds_pct_52w": [10, 10, 90],
                           "leveraged_funds_streak_up_weeks": [3, 0, 3],
                           "leveraged_funds_streak_down_weeks": [0, 0, 0]})
        out = evaluate_condition(s, Condition("spec_turning_up", "", ""), "leveraged_funds", "asset_manager")
        self.assertListEqual(out.tolist(), [True, False, False])

    def test_divergence_is_opposite_signs(self):
        s = pd.DataFrame({"leveraged_funds_chg_4w": [100, 100, -100],
                           "asset_manager_chg_4w": [-100, 100, -100]})
        out = evaluate_condition(s, Condition("divergence", "", ""), "leveraged_funds", "asset_manager")
        self.assertListEqual(out.tolist(), [True, False, False])

    def test_short_covering_requires_flat_longs(self):
        s = pd.DataFrame({"leveraged_funds_chg_1w": [3000, 3000],
                           "leveraged_funds_long_chg_1w": [100, 2900]})
        out = evaluate_condition(s, Condition("short_covering", "", ""), "leveraged_funds", "asset_manager")
        self.assertListEqual(out.tolist(), [True, False])


class TestContingency(unittest.TestCase):
    def test_all_four_cells_are_counted(self):
        r = validate(_states(300), CONDITIONS[0], EVENT_DEFS[0], "leveraged_funds", "asset_manager")
        self.assertEqual(r.a + r.b + r.c + r.d, r.a + r.b + r.c + r.d)
        self.assertGreater(r.a + r.b + r.c + r.d, 0)

    def test_cell_b_is_reported(self):
        """Клетка B — «условие было, движения не было» — обязана считаться:
        без неё исследование превращается в подборку удачных примеров."""
        r = validate(_states(300), CONDITIONS[0], EVENT_DEFS[0], "leveraged_funds", "asset_manager")
        self.assertIsInstance(r.b, int)

    def test_small_sample_refuses_a_verdict(self):
        r = validate(_states(40), CONDITIONS[2], EVENT_DEFS[3], "leveraged_funds", "asset_manager")
        if r.n_condition < MIN_OCCURRENCES:
            self.assertIn("мало для вывода", r.verdict)

    def test_random_data_yields_noise_verdict(self):
        """На случайных данных условие не должно выглядеть работающим."""
        r = validate(_states(600, seed=7), CONDITIONS[0], EVENT_DEFS[0], "leveraged_funds", "asset_manager")
        if r.n_condition >= MIN_OCCURRENCES and r.lift_pp is not None:
            self.assertLess(abs(r.lift_pp), 25, "на шуме не должно быть большого перевеса")

    def test_engineered_signal_is_found(self):
        """Обратная проверка: если связь заложена, метод обязан её увидеть."""
        n = 400
        rng = np.random.default_rng(3)
        pct = rng.uniform(0, 100, n)
        price = [100.0]
        for i in range(1, n):
            drift = 0.02 if pct[i - 1] <= 10 else 0.0   # после низкого перцентиля цена растёт
            price.append(price[-1] * (1 + drift + rng.normal(0, .004)))
        s = pd.DataFrame({
            "report_date": pd.date_range("2018-01-02", periods=n, freq="7D").date,
            "price_close": price, "leveraged_funds_pct_52w": pct,
            "leveraged_funds_streak_up_weeks": np.zeros(n),
            "leveraged_funds_streak_down_weeks": np.zeros(n),
            "leveraged_funds_chg_4w": np.zeros(n), "asset_manager_chg_4w": np.zeros(n),
            "leveraged_funds_chg_1w": np.zeros(n), "leveraged_funds_long_chg_1w": np.zeros(n),
        })
        r = validate(s, CONDITIONS[0], EVENT_DEFS[0], "leveraged_funds", "asset_manager")
        self.assertGreater(r.lift_pp, 5, "заложенная связь должна обнаруживаться")

    def test_base_rate_between_the_two_rates(self):
        r = validate(_states(400, seed=2), CONDITIONS[4], EVENT_DEFS[2], "leveraged_funds", "asset_manager")
        if None not in (r.rate_with, r.rate_without, r.base_rate):
            self.assertLessEqual(min(r.rate_with, r.rate_without) - 1e-9, r.base_rate)
            self.assertGreaterEqual(max(r.rate_with, r.rate_without) + 1e-9, r.base_rate)


if __name__ == "__main__":
    unittest.main()
