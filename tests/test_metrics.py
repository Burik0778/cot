import unittest
import pandas as pd
from src.cot.metrics import add_basic_metrics, add_changes, add_streaks


class TestBasicMetrics(unittest.TestCase):
    def test_net_and_ratios(self):
        df = pd.DataFrame({"long": [100, 50], "short": [40, 70], "open_interest": [200, 200]})
        out = add_basic_metrics(df)
        self.assertListEqual(list(out["net"]), [60, -20])
        self.assertAlmostEqual(out["net_oi"].iloc[0], 0.30)
        self.assertAlmostEqual(out["net_oi"].iloc[1], -0.10)
        self.assertAlmostEqual(out["long_oi"].iloc[0], 0.50)
        self.assertAlmostEqual(out["short_oi"].iloc[1], 0.35)

    def test_zero_open_interest_gives_nan_not_error(self):
        df = pd.DataFrame({"long": [10], "short": [5], "open_interest": [0]})
        out = add_basic_metrics(df)
        self.assertTrue(pd.isna(out["net_oi"].iloc[0]))


class TestChanges(unittest.TestCase):
    def test_changes_are_plain_differences(self):
        df = pd.DataFrame({"net": [10, 12, 15, 11, 20]})
        out = add_changes(df, "net", windows=[1, 4])
        self.assertTrue(pd.isna(out["chg_1w"].iloc[0]))
        self.assertListEqual(out["chg_1w"].iloc[1:].tolist(), [2, 3, -4, 9])
        # chg_4w[4] = net[4]-net[0] = 20-10 = 10; first 4 rows NaN (insufficient history)
        self.assertTrue(out["chg_4w"].iloc[:4].isna().all())
        self.assertEqual(out["chg_4w"].iloc[4], 10)


class TestStreaks(unittest.TestCase):
    def test_streak_up_and_down(self):
        # net: 10, 12(up1), 15(up2), 11(down1), 9(down2), 9(flat->0), 20(up1)
        df = pd.DataFrame({"net": [10, 12, 15, 11, 9, 9, 20]})
        out = add_streaks(df, "net")
        self.assertListEqual(out["streak_up_weeks"].tolist(), [0, 1, 2, 0, 0, 0, 1])
        self.assertListEqual(out["streak_down_weeks"].tolist(), [0, 0, 0, 1, 2, 0, 0])


if __name__ == "__main__":
    unittest.main()
