import unittest
import pandas as pd
from datetime import date
from src.price.quote_convention import currency_return, currency_direction_sign
from src.price.returns import compute_forward_return, add_forward_returns


class TestQuoteConvention(unittest.TestCase):
    def test_base_currency_pairs_keep_sign(self):
        # EUR is base in EURUSD -> pair up == EUR up
        r = currency_return(pd.Series([0.01, -0.02]), "EUR")
        self.assertListEqual(list(r), [0.01, -0.02])
        self.assertEqual(currency_direction_sign("EUR"), 1)

    def test_quote_currency_pairs_flip_sign(self):
        # JPY is quote in USDJPY -> pair up == JPY DOWN
        r = currency_return(pd.Series([0.01, -0.02]), "JPY")
        self.assertListEqual(list(r), [-0.01, 0.02])
        self.assertEqual(currency_direction_sign("JPY"), -1)

    def test_all_quote_currencies_flip(self):
        for ccy in ["JPY", "CAD", "CHF", "MXN"]:
            self.assertEqual(currency_direction_sign(ccy), -1, ccy)
        for ccy in ["EUR", "GBP", "AUD", "NZD"]:
            self.assertEqual(currency_direction_sign(ccy), 1, ccy)


class TestForwardReturns(unittest.TestCase):
    def _price_df(self):
        dates = pd.date_range("2024-01-01", periods=20, freq="7D").date
        closes = [100 + i for i in range(20)]  # steadily rising pair price
        return pd.DataFrame({"date": dates, "close": closes})

    def test_matured_return_is_computed_for_base_currency(self):
        df = self._price_df()
        r = compute_forward_return(df, date(2024, 1, 1), horizon_weeks=4, currency="EUR",
                                    as_of_date=date(2024, 3, 1))
        # price[0]=100, price at +4 weeks (index4)=104 -> +4% pair return == +4% EUR return
        self.assertAlmostEqual(r, 0.04)

    def test_matured_return_flips_sign_for_quote_currency(self):
        df = self._price_df()
        r = compute_forward_return(df, date(2024, 1, 1), horizon_weeks=4, currency="JPY",
                                    as_of_date=date(2024, 3, 1))
        self.assertAlmostEqual(r, -0.04)

    def test_unmatured_horizon_returns_none_not_zero(self):
        df = self._price_df()
        # as_of_date is BEFORE the target date -> must be None, not 0 or a guess
        r = compute_forward_return(df, date(2024, 1, 1), horizon_weeks=26, currency="EUR",
                                    as_of_date=date(2024, 2, 1))
        self.assertIsNone(r)

    def test_add_forward_returns_leaves_unmatured_rows_as_nan(self):
        price_df = self._price_df()
        states = pd.DataFrame({
            "availability_date": [date(2024, 1, 1), date(2024, 2, 26)],
        })
        out = add_forward_returns(states, price_df, "EUR", horizons_weeks=[4], as_of_date=date(2024, 3, 1))
        self.assertAlmostEqual(out["fwd_return_4w"].iloc[0], 0.04)
        self.assertTrue(pd.isna(out["fwd_return_4w"].iloc[1]))  # 2024-02-26 + 4w > as_of


if __name__ == "__main__":
    unittest.main()
