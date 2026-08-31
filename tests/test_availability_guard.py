import unittest
import pandas as pd
from datetime import date, datetime
from src.data.availability_guard import (
    DataAvailabilityGuard, Availability, Confidence, LookaheadError, to_date,
)

AS_OF = date(2026, 8, 21)


class TestToDate(unittest.TestCase):
    """Конверсия обязана работать на любой дате: pandas 2.x роняет
    datetime64[ns] после 2262-04-11, и именно из-за этого защита
    однажды не срабатывала."""

    def test_far_future_beyond_ns_bounds(self):
        self.assertEqual(to_date(date(2999, 1, 1)), date(2999, 1, 1))

    def test_string(self):
        self.assertEqual(to_date("2026-08-21"), date(2026, 8, 21))

    def test_datetime(self):
        self.assertEqual(to_date(datetime(2026, 8, 21, 15, 30)), date(2026, 8, 21))

    def test_timestamp(self):
        self.assertEqual(to_date(pd.Timestamp("2026-08-21")), date(2026, 8, 21))

    def test_none_and_nan(self):
        self.assertIsNone(to_date(None))
        self.assertIsNone(to_date(float("nan")))

    def test_garbage_string_is_none_not_crash(self):
        self.assertIsNone(to_date("не дата"))


class TestSingleCheck(unittest.TestCase):
    def test_available_passes(self):
        g = DataAvailabilityGuard(AS_OF)
        self.assertTrue(g.check(Availability(date(2026, 8, 21), Confidence.OFFICIAL), "COT"))

    def test_future_raises(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.check(Availability(date(2026, 8, 28), Confidence.OFFICIAL), "COT")

    def test_unknown_confidence_never_passes(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.check(Availability(date(2020, 1, 1), Confidence.UNKNOWN), "макро")

    def test_non_strict_collects_instead_of_raising(self):
        g = DataAvailabilityGuard(AS_OF, strict=False)
        self.assertFalse(g.check(Availability(date(2027, 1, 1), Confidence.OFFICIAL), "COT"))
        self.assertEqual(len(g.violations), 1)
        self.assertFalse(g.report()["clean"])


class TestFrameCheck(unittest.TestCase):
    def _df(self, dates):
        return pd.DataFrame({"availability_date": dates, "v": range(len(dates))})

    def test_clean_frame_passes(self):
        g = DataAvailabilityGuard(AS_OF)
        g.assert_frame_available(self._df([date(2026, 8, 7), date(2026, 8, 14)]), "cot")

    def test_future_row_raises(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.assert_frame_available(self._df([date(2026, 8, 7), date(2026, 9, 4)]), "cot")

    def test_far_future_row_raises_lookahead_not_pandas_error(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.assert_frame_available(self._df([date(2026, 8, 7), date(2500, 1, 1)]), "cot")

    def test_missing_date_raises(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.assert_frame_available(self._df([date(2026, 8, 7), None]), "cot")

    def test_filter_is_explicit_and_keeps_only_known(self):
        g = DataAvailabilityGuard(AS_OF)
        out = g.filter_available(self._df([date(2026, 8, 7), date(2026, 9, 4)]))
        self.assertEqual(len(out), 1)

    def test_guard_never_filters_silently_in_assert(self):
        """assert_* обязан кричать, а не чинить данные за вызывающего."""
        g = DataAvailabilityGuard(AS_OF, strict=False)
        df = self._df([date(2026, 8, 7), date(2026, 9, 4)])
        g.assert_frame_available(df, "cot")
        self.assertEqual(len(df), 2)          # исходный кадр не тронут
        self.assertTrue(g.violations)


class TestFeatureLeakage(unittest.TestCase):
    def test_forward_return_feature_raises(self):
        g = DataAvailabilityGuard(AS_OF)
        with self.assertRaises(LookaheadError):
            g.assert_features_are_not_outcomes(["net_oi", "fwd_return_8w"])

    def test_clean_features_pass(self):
        g = DataAvailabilityGuard(AS_OF)
        g.assert_features_are_not_outcomes(["net_oi", "pct_52w"])


if __name__ == "__main__":
    unittest.main()
