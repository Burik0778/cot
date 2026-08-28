import unittest
import pandas as pd
import numpy as np
from datetime import date
from src.data.data_quality import check_missing_weeks, check_duplicates, check_unexpected_jumps, check_freshness, check_schema_signature
from src.data.export import to_csv_bytes, to_json_bytes, to_excel_bytes


class TestDataQuality(unittest.TestCase):
    def test_missing_weeks_detected(self):
        dates = pd.date_range("2020-01-07", periods=5, freq="7D").tolist()
        dates.pop(2)  # remove one week -> creates a 14-day gap
        df = pd.DataFrame({"report_date": dates})
        finding = check_missing_weeks(df)
        self.assertEqual(finding.status, "warning")

    def test_no_missing_weeks_is_ok(self):
        dates = pd.date_range("2020-01-07", periods=10, freq="7D").tolist()
        df = pd.DataFrame({"report_date": dates})
        finding = check_missing_weeks(df)
        self.assertEqual(finding.status, "ok")

    def test_duplicates_detected(self):
        df = pd.DataFrame({"market": ["EUR", "EUR"], "participant": ["dealer", "dealer"],
                            "report_date": ["2020-01-07", "2020-01-07"], "source": ["x", "x"]})
        finding = check_duplicates(df, ["market", "participant", "report_date", "source"])
        self.assertEqual(finding.status, "error")

    def test_unexpected_jump_detected(self):
        values = [1000 + i for i in range(30)] + [50000]  # one huge jump
        df = pd.DataFrame({"open_interest": values})
        finding = check_unexpected_jumps(df, "open_interest")
        self.assertEqual(finding.status, "warning")

    def test_freshness_stale(self):
        finding = check_freshness(date(2020, 1, 1), as_of=date(2020, 6, 1), stale_after_days=14)
        self.assertEqual(finding.status, "warning")

    def test_freshness_fresh(self):
        finding = check_freshness(date(2020, 1, 1), as_of=date(2020, 1, 3), stale_after_days=14)
        self.assertEqual(finding.status, "ok")

    def test_schema_change_detected(self):
        finding, sig = check_schema_signature(["a", "b", "c"], "a,b")
        self.assertEqual(finding.status, "error")
        self.assertEqual(sig, "a,b,c")

    def test_schema_unchanged(self):
        finding, sig = check_schema_signature(["a", "b"], "a,b")
        self.assertEqual(finding.status, "ok")

    def test_accounting_identity_holds_on_valid_data(self):
        from src.data.data_quality import check_accounting_identity
        df = pd.DataFrame({
            "report_date": ["2026-08-18"] * 3,
            "long": [50, 30, 20], "short": [40, 40, 20], "open_interest": [100, 100, 100],
        })
        self.assertEqual(check_accounting_identity(df).status, "ok")

    def test_accounting_identity_catches_a_dropped_category(self):
        # Simulates CFTC renaming a column so one category silently reads zero.
        from src.data.data_quality import check_accounting_identity
        df = pd.DataFrame({
            "report_date": ["2026-08-18"] * 3,
            "long": [50, 30, 0], "short": [40, 40, 0], "open_interest": [100, 100, 100],
        })
        finding = check_accounting_identity(df)
        self.assertEqual(finding.status, "error")
        self.assertIn("2026-08-18", finding.detail)


class TestExport(unittest.TestCase):
    def _df(self):
        return pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    def test_csv_roundtrip(self):
        raw = to_csv_bytes(self._df())
        back = pd.read_csv(pd.io.common.BytesIO(raw))
        self.assertEqual(back["a"].tolist(), [1, 2, 3])

    def test_json_roundtrip(self):
        raw = to_json_bytes(self._df())
        import json
        parsed = json.loads(raw)
        self.assertEqual(len(parsed), 3)

    def test_excel_produces_nonempty_bytes(self):
        raw = to_excel_bytes(self._df())
        self.assertGreater(len(raw), 0)
        back = pd.read_excel(pd.io.common.BytesIO(raw))
        self.assertEqual(back["a"].tolist(), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
