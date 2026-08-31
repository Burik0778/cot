import unittest
import numpy as np
import pandas as pd
from src.events.event_study import (
    run_event_study, build_episodes, DEFAULT_HORIZONS,
)


def _states(n=120, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "report_date": pd.date_range("2020-01-07", periods=n, freq="7D").date,
        "price_close": 100 * np.cumprod(1 + rng.normal(0.001, .01, n)),
    })


class TestEpisodes(unittest.TestCase):
    def test_consecutive_weeks_become_one_episode(self):
        mask = pd.Series([False, True, True, True, False, False, True, False])
        dates = pd.Series(pd.date_range("2020-01-07", periods=8, freq="7D").date)
        eps = build_episodes(mask, dates)
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0].duration_weeks, 3)
        self.assertEqual(eps[1].duration_weeks, 1)

    def test_gap_tolerance_merges_near_runs(self):
        mask = pd.Series([True, False, True, False, False, False])
        dates = pd.Series(pd.date_range("2020-01-07", periods=6, freq="7D").date)
        self.assertEqual(len(build_episodes(mask, dates, gap_tolerance=0)), 2)
        self.assertEqual(len(build_episodes(mask, dates, gap_tolerance=1)), 1)

    def test_trailing_run_is_closed(self):
        mask = pd.Series([False, True, True])
        dates = pd.Series(pd.date_range("2020-01-07", periods=3, freq="7D").date)
        self.assertEqual(len(build_episodes(mask, dates)), 1)

    def test_no_events_gives_no_episodes(self):
        mask = pd.Series([False] * 5)
        dates = pd.Series(pd.date_range("2020-01-07", periods=5, freq="7D").date)
        self.assertEqual(build_episodes(mask, dates), [])


class TestHorizons(unittest.TestCase):
    def test_zero_horizon_is_exactly_zero(self):
        """Точка события — начало отсчёта, а не доходность за её неделю."""
        s = _states()
        mask = pd.Series([False] * 40 + [True] + [False] * (len(s) - 41))
        r = run_event_study(s, mask)
        self.assertEqual(r.mean[0], 0.0)

    def test_negative_horizons_are_computed_not_nan(self):
        """Раньше предсобытийная часть молча возвращала NaN."""
        s = _states()
        mask = pd.Series([False] * 40 + [True] + [False] * (len(s) - 41))
        r = run_event_study(s, mask)
        for h in (-8, -4, -2, -1):
            self.assertIsNotNone(r.mean[h], f"горизонт {h} не посчитан")
            self.assertGreater(r.counts[h], 0)

    def test_negative_horizon_matches_hand_calculation(self):
        s = pd.DataFrame({
            "report_date": pd.date_range("2020-01-07", periods=5, freq="7D").date,
            "price_close": [100, 100, 100, 100, 110],
        })
        mask = pd.Series([False, False, False, False, True])
        r = run_event_study(s, mask, horizons=[-4, 0])
        # цена была 100, стала 110 -> -4W = -(110/100 - 1) = -0.10
        self.assertAlmostEqual(r.mean[-4], -0.10, places=6)

    def test_forward_horizon_matches_hand_calculation(self):
        s = pd.DataFrame({
            "report_date": pd.date_range("2020-01-07", periods=5, freq="7D").date,
            "price_close": [100, 105, 110, 115, 120],
        })
        mask = pd.Series([True, False, False, False, False])
        r = run_event_study(s, mask, horizons=[0, 2])
        self.assertAlmostEqual(r.mean[2], 0.10, places=6)

    def test_immature_forward_horizon_is_excluded(self):
        s = _states(30)
        mask = pd.Series([False] * 28 + [True, False])
        r = run_event_study(s, mask, horizons=[0, 12])
        self.assertEqual(r.counts[12], 0)


class TestEpisodeVsWeekly(unittest.TestCase):
    def test_episode_mode_reduces_event_count(self):
        s = _states()
        mask = pd.Series([False] * 20 + [True] * 10 + [False] * (len(s) - 30))
        weekly = run_event_study(s, mask, use_episodes=False)
        episodic = run_event_study(s, mask, use_episodes=True)
        self.assertEqual(weekly.n_events, 10)
        self.assertEqual(episodic.n_events, 1)
        self.assertEqual(episodic.n_episodes, 1)

    def test_episode_note_explains_the_difference(self):
        s = _states()
        mask = pd.Series([False] * 20 + [True] * 10 + [False] * (len(s) - 30))
        self.assertIn("эпизод", run_event_study(s, mask).note.lower())

    def test_missing_price_is_reported_not_crashed(self):
        s = pd.DataFrame({"report_date": [1, 2, 3]})
        r = run_event_study(s, pd.Series([True, False, False]))
        self.assertEqual(r.n_events, 0)
        self.assertIn("Нет ценового ряда", r.note)


if __name__ == "__main__":
    unittest.main()
