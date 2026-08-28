import unittest
from src.reporting.report import ReportInput, build_markdown, build_html


def _sample(is_synthetic=True):
    return ReportInput(
        market="EUR", pair_symbol="EURUSD", report_date="2026-08-18",
        availability_date="2026-08-21", availability_source="cftc_published_schedule",
        is_synthetic=is_synthetic, regime="Bullish Reversal",
        regime_reasons=["leveraged_funds_pct_52w < 10 (actual: 8)"],
        participant_rows=[{"participant": "Leveraged Funds", "net": -57716, "net_oi": -0.07,
                            "pct_52w": 8.0, "z_52w": -1.9, "chg_4w": 2800}],
        price_close=1.0842, price_changes={"4w": 0.011, "8w": -0.004, "12w": 0.02},
        n_analogs=37,
        top_analogs=[{"report_date": "2024-03-12", "similarity_score": 88.4, "distance": 0.41}],
        horizon_stats={
            8: {"n": 37, "win_rate": 0.68, "median_return": 0.0121, "base_rate": 0.53,
                "edge_pp": 15.0, "sample_quality": "Moderate",
                "bootstrap_ci_median": (0.002, 0.021), "binomial_p_value": 0.06,
                "permutation_p_value": 0.04, "cohens_d": 0.35},
            26: {"n": 6, "sample_quality": "Insufficient sample size"},
        },
        divergences=["Asset Managers vs Leveraged Funds"],
        contradictions=["Dealer positioning has not confirmed the move."],
        ai_analysis="CURRENT STATE\nEUR COT regime: Bullish Reversal",
    )


class TestReport(unittest.TestCase):
    def test_synthetic_warning_is_present_and_prominent(self):
        md = build_markdown(_sample(is_synthetic=True))
        self.assertIn("SYNTHETIC DATA", md)
        # must appear before any statistics
        self.assertLess(md.index("SYNTHETIC DATA"), md.index("Historical analogs"))

    def test_no_synthetic_warning_on_real_data(self):
        md = build_markdown(_sample(is_synthetic=False))
        self.assertNotIn("SYNTHETIC DATA", md)

    def test_both_dates_are_reported_with_their_source(self):
        md = build_markdown(_sample())
        self.assertIn("2026-08-18", md)
        self.assertIn("2026-08-21", md)
        self.assertIn("cftc_published_schedule", md)

    def test_insufficient_sample_horizon_shows_no_numbers(self):
        md = build_markdown(_sample())
        line = [l for l in md.split("\n") if l.startswith("| 26W")][0]
        self.assertIn("Insufficient sample size", line)
        self.assertNotIn("%", line)

    def test_base_rate_and_edge_always_accompany_win_rate(self):
        md = build_markdown(_sample())
        self.assertIn("Base rate", md)
        self.assertIn("Edge (pp)", md)

    def test_overlapping_observation_caveat_is_included(self):
        md = build_markdown(_sample())
        self.assertIn("overlap", md.lower())

    def test_closing_disclaimer_present(self):
        md = build_markdown(_sample())
        self.assertIn("not a trading signal", md)
        self.assertIn("does not establish causation", md)

    def test_multiple_testing_warning_only_past_threshold(self):
        data = _sample()
        data.hypotheses_tested = 5
        self.assertNotIn("multiple-testing bias", build_markdown(data))
        data.hypotheses_tested = 250
        self.assertIn("multiple-testing bias", build_markdown(data))

    def test_html_is_self_contained_and_escaped(self):
        data = _sample()
        data.contradictions = ["<script>alert(1)</script>"]
        out = build_html(data)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("http://", out)  # no external assets

    def test_html_renders_tables(self):
        out = build_html(_sample())
        self.assertIn("<table>", out)
        self.assertIn("</table>", out)


if __name__ == "__main__":
    unittest.main()
