import unittest
import pandas as pd
from src.cot.regimes import classify_row, classify_dataframe
from src.cot.divergence import detect_pairwise_divergence, collect_divergence_events


class TestRegimeEngine(unittest.TestCase):
    def test_bullish_reversal_fires_exactly_on_matching_row(self):
        row = pd.Series({
            "leveraged_funds_pct_52w": 8,
            "leveraged_funds_streak_up_weeks": 3,
            "leveraged_funds_chg_4w": 500,
            "asset_manager_chg_4w": 100,
        })
        name, reasons = classify_row(row)
        self.assertEqual(name, "Bullish Reversal")
        self.assertTrue(len(reasons) >= 1)

    def test_bullish_reversal_does_not_fire_if_one_condition_fails(self):
        row = pd.Series({
            "leveraged_funds_pct_52w": 8,
            "leveraged_funds_streak_up_weeks": 1,  # needs >= 2
            "leveraged_funds_chg_4w": 500,
            "asset_manager_chg_4w": 100,
        })
        name, _ = classify_row(row)
        self.assertNotEqual(name, "Bullish Reversal")

    def test_missing_columns_do_not_crash_and_do_not_falsely_match(self):
        row = pd.Series({"leveraged_funds_pct_52w": 8})  # missing everything else
        name, reasons = classify_row(row)
        self.assertNotEqual(name, "Bullish Reversal")

    def test_fallback_neutral_always_matches_something(self):
        row = pd.Series({"leveraged_funds_pct_52w": 50})
        name, _ = classify_row(row)
        self.assertIsNotNone(name)
        self.assertNotEqual(name, "Unclassified")

    def test_priority_order_extreme_short_beats_bearish_positioning(self):
        # A row satisfying BOTH "Extreme Short" (pct<=5) and, if evaluated in
        # isolation, "Bearish Positioning" (pct<=40) must resolve to the
        # earlier-listed, more specific rule.
        row = pd.Series({"leveraged_funds_pct_52w": 3})
        name, _ = classify_row(row)
        self.assertEqual(name, "Extreme Short")

    def test_classify_dataframe_adds_columns(self):
        df = pd.DataFrame([{"leveraged_funds_pct_52w": 3}, {"leveraged_funds_pct_52w": 50}])
        out = classify_dataframe(df)
        self.assertIn("regime", out.columns)
        self.assertIn("regime_reasons", out.columns)
        self.assertEqual(out["regime"].iloc[0], "Extreme Short")


class TestDivergence(unittest.TestCase):
    def test_opposite_direction_move_is_flagged(self):
        df = pd.DataFrame({
            "am_net": [0, 0, 0, 0, 100],     # asset managers: +100 over 4w
            "lev_net": [0, 0, 0, 0, -100],   # leveraged funds: -100 over 4w
        })
        flags = detect_pairwise_divergence(df, "am_net", "lev_net", "AM", "LEV", window_weeks=4)
        self.assertTrue(flags.iloc[4])
        self.assertFalse(flags.iloc[:4].any())

    def test_same_direction_move_is_not_flagged(self):
        df = pd.DataFrame({
            "am_net": [0, 0, 0, 0, 100],
            "lev_net": [0, 0, 0, 0, 100],
        })
        flags = detect_pairwise_divergence(df, "am_net", "lev_net", "AM", "LEV", window_weeks=4)
        self.assertFalse(flags.any())

    def test_noise_floor_suppresses_tiny_moves(self):
        df = pd.DataFrame({
            "am_net": [0, 0, 0, 0, 1],
            "lev_net": [0, 0, 0, 0, -1],
        })
        flags = detect_pairwise_divergence(df, "am_net", "lev_net", "AM", "LEV", window_weeks=4, noise_floor=10)
        self.assertFalse(flags.any())

    def test_collect_events_reports_correct_magnitude(self):
        df = pd.DataFrame({
            "report_date": ["2024-01-02", "2024-01-09", "2024-01-16", "2024-01-23", "2024-01-30"],
            "am_net": [0, 0, 0, 0, 100],
            "lev_net": [0, 0, 0, 0, -40],
        })
        events = collect_divergence_events(df, [("am_net", "lev_net", "AM", "LEV")], window_weeks=4)
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0].magnitude, 40)  # min(|100|, |-40|)
        self.assertEqual(events[0].start_report_date, "2024-01-30")


if __name__ == "__main__":
    unittest.main()
