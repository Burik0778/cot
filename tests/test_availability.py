import unittest
from datetime import date
from src.data.availability import get_availability, derive_availability_date


class TestAvailability(unittest.TestCase):
    def test_availability_is_never_before_report_date(self):
        for d in [date(2018, 3, 6), date(2020, 1, 7), date(2023, 11, 21), date(2026, 8, 18)]:
            a = get_availability(d)
            self.assertGreater(a.availability_date, a.report_date)

    def test_availability_is_always_a_friday_in_the_fallback_rule(self):
        for d in [date(2018, 3, 6), date(2020, 1, 7), date(2023, 11, 21), date(2024, 7, 2)]:
            a = derive_availability_date(d)
            self.assertEqual(a.availability_date.isoweekday(), 5, f"{a.availability_date} is not a Friday")

    def test_2026_dates_use_the_published_schedule(self):
        a = get_availability(date(2026, 8, 18))
        self.assertEqual(a.source, "cftc_published_schedule")
        self.assertEqual(a.availability_date, date(2026, 8, 21))

    def test_non_2026_dates_use_the_derived_rule_and_say_so(self):
        a = get_availability(date(2019, 5, 7))
        self.assertEqual(a.source, "derived_rule")

    def test_shutdown_window_is_flagged_not_silently_trusted(self):
        a = derive_availability_date(date(2025, 10, 7))
        self.assertIsNotNone(a.warning)
        self.assertIn("shutdown", a.warning.lower())

    def test_holiday_shift_moves_forward_not_backward(self):
        # July 4, 2025 is a Friday (a real federal holiday on that exact date);
        # the report_date 3 days earlier is Tuesday July 1, 2025.
        a = derive_availability_date(date(2025, 7, 1))
        self.assertNotEqual(a.availability_date, date(2025, 7, 4))
        self.assertGreater(a.availability_date, date(2025, 7, 4))


if __name__ == "__main__":
    unittest.main()
