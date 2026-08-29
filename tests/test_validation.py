import unittest
import numpy as np
import pandas as pd
from src.events.validation import (
    EventDefinition, Condition, detect_events, event_threshold, evaluate_condition,
    validate, precursor_profile, EVENT_DEFS, CONDITIONS, MIN_OCCURRENCES,
)

EV = EventDefinition("t", "тест", "", 0.80, 4, "up")
SPEC, SLOW = "leveraged_funds", "asset_manager"


def _states(n=300, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "report_date": pd.date_range("2018-01-02", periods=n, freq="7D").date,
        "price_close": 100 * np.cumprod(1 + rng.normal(0, .01, n)),
        f"{SPEC}_net": np.cumsum(rng.normal(0, 2000, n)),
        f"{SPEC}_pct_52w": rng.uniform(0, 100, n),
        f"{SPEC}_streak_up_weeks": rng.integers(0, 5, n),
        f"{SPEC}_streak_down_weeks": rng.integers(0, 5, n),
        f"{SPEC}_chg_1w": rng.normal(0, 3000, n),
        f"{SPEC}_chg_4w": rng.normal(0, 6000, n),
        f"{SPEC}_long_chg_1w": rng.normal(0, 2000, n),
        f"{SPEC}_oi_chg_1w": rng.normal(0, 5000, n),
        f"{SPEC}_oi_chg_4w": rng.normal(0, 9000, n),
        f"{SLOW}_chg_1w": rng.normal(0, 3000, n),
        f"{SLOW}_chg_4w": rng.normal(0, 6000, n),
    })


class TestSelfScalingThreshold(unittest.TestCase):
    """Порог должен подстраиваться под инструмент. Одинаковые проценты для
    евро и золота — та самая ошибка, из-за которой выборка вырождалась."""

    def test_threshold_differs_between_calm_and_volatile_markets(self):
        calm = _states(seed=1)
        calm["price_close"] = 100 * np.cumprod(1 + np.random.default_rng(1).normal(0, .002, len(calm)))
        wild = _states(seed=1)
        wild["price_close"] = 100 * np.cumprod(1 + np.random.default_rng(1).normal(0, .04, len(wild)))
        self.assertLess(event_threshold(calm, EV), event_threshold(wild, EV))

    def test_threshold_selects_roughly_the_intended_share(self):
        s = _states(600, seed=3)
        flags, thr = detect_events(s, EV)
        share = flags.dropna().mean()
        self.assertGreater(share, 0.10)
        self.assertLess(share, 0.32)   # целимся в верхние ~20%

    def test_no_price_gives_no_threshold(self):
        self.assertIsNone(event_threshold(pd.DataFrame({"report_date": [1, 2, 3]}), EV))

    def test_immature_tail_is_nan(self):
        s = _states(200)
        flags, _ = detect_events(s, EV)
        self.assertTrue(pd.isna(flags.iloc[-1]))


class TestEventConditions(unittest.TestCase):
    """Признаки должны быть СОБЫТИЯМИ, а не уровнями."""

    def test_net_flip_up_detects_crossing_zero(self):
        s = pd.DataFrame({f"{SPEC}_net": [-500, -100, 200, 400]})
        out = evaluate_condition(s, Condition("net_flip_up", "", ""), SPEC, SLOW)
        self.assertListEqual(out.tolist()[1:], [False, True, False])

    def test_net_flip_down_detects_crossing_zero(self):
        s = pd.DataFrame({f"{SPEC}_net": [500, 100, -200, -400]})
        out = evaluate_condition(s, Condition("net_flip_down", "", ""), SPEC, SLOW)
        self.assertListEqual(out.tolist()[1:], [False, True, False])

    def test_flow_spike_flags_only_the_tail(self):
        s = _states(400, seed=5)
        out = evaluate_condition(s, Condition("flow_spike_up", "", ""), SPEC, SLOW)
        share = out.dropna().mean()
        self.assertLess(share, 0.25)
        self.assertGreater(share, 0.05)

    def test_divergence_closing_needs_apart_then_together(self):
        s = pd.DataFrame({
            f"{SPEC}_chg_4w": [1000, 1000], f"{SLOW}_chg_4w": [-1000, -1000],
            f"{SPEC}_chg_1w": [500, -500],  f"{SLOW}_chg_1w": [500, 500],
        })
        out = evaluate_condition(s, Condition("divergence_closing", "", ""), SPEC, SLOW)
        self.assertTrue(bool(out.iloc[0]))    # расходились, теперь вместе
        self.assertFalse(bool(out.iloc[1]))   # всё ещё врозь

    def test_short_squeeze_requires_flat_longs(self):
        s = pd.DataFrame({f"{SPEC}_chg_1w": [3000, 3000], f"{SPEC}_long_chg_1w": [100, 2900]})
        out = evaluate_condition(s, Condition("short_squeeze", "", ""), SPEC, SLOW)
        self.assertListEqual(out.tolist(), [True, False])


class TestContingency(unittest.TestCase):
    def test_returns_all_four_cells(self):
        r = validate(_states(400), CONDITIONS[0], EVENT_DEFS[0], SPEC, SLOW)
        for k in ("a", "b", "c", "d", "rate_with", "base_rate", "lift_pp", "n"):
            self.assertIn(k, r)

    def test_threshold_reported_in_points(self):
        r = validate(_states(400), CONDITIONS[0], EVENT_DEFS[0], SPEC, SLOW, pip=0.0001, unit="пп")
        self.assertIsNotNone(r["threshold_pts"])
        self.assertEqual(r["unit"], "пп")

    def test_small_sample_refuses_verdict(self):
        r = validate(_states(120), CONDITIONS[2], EVENT_DEFS[3], SPEC, SLOW)
        if r["n"] < MIN_OCCURRENCES:
            self.assertIn("мало для вывода", r["verdict"])

    def test_noise_does_not_produce_large_edge(self):
        r = validate(_states(700, seed=11), CONDITIONS[0], EVENT_DEFS[0], SPEC, SLOW)
        if r["n"] >= MIN_OCCURRENCES and r["lift_pp"] is not None:
            self.assertLess(abs(r["lift_pp"]), 30)

    def test_engineered_link_is_detected(self):
        n = 500
        rng = np.random.default_rng(4)
        chg = rng.normal(0, 3000, n)
        price = [100.0]
        for i in range(1, n):
            drift = 0.012 if chg[i - 1] > 4000 else 0.0
            price.append(price[-1] * (1 + drift + rng.normal(0, .004)))
        s = _states(n, seed=4)
        s["price_close"] = price
        s[f"{SPEC}_chg_1w"] = chg
        r = validate(s, Condition("flow_spike_up", "", ""), EVENT_DEFS[0], SPEC, SLOW)
        self.assertGreater(r["lift_pp"], 5)


class TestPrecursors(unittest.TestCase):
    """Обратный взгляд: от движения назад к отчётам."""

    def test_profile_compares_against_normal_weeks(self):
        p = precursor_profile(_states(400), EVENT_DEFS[0], SPEC, SLOW)
        self.assertTrue(p["available"])
        for row in p["metrics"]:
            self.assertIn("before", row)
            self.assertIn("always", row)   # без базы сравнения профиль обманывает

    def test_no_price_is_reported_not_crashed(self):
        p = precursor_profile(pd.DataFrame({"report_date": [1, 2]}), EVENT_DEFS[0], SPEC, SLOW)
        self.assertFalse(p["available"])

    def test_condition_shares_are_probabilities(self):
        p = precursor_profile(_states(400), EVENT_DEFS[0], SPEC, SLOW)
        for c in p["conditions"]:
            self.assertGreaterEqual(c["share_before"], 0)
            self.assertLessEqual(c["share_before"], 1)
            self.assertGreaterEqual(c["base_share"], 0)
            self.assertLessEqual(c["base_share"], 1)

    def test_dates_are_returned_for_inspection(self):
        p = precursor_profile(_states(400), EVENT_DEFS[0], SPEC, SLOW)
        self.assertEqual(len(p["dates"]), p["n_moves"])


if __name__ == "__main__":
    unittest.main()
