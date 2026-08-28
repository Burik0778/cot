import unittest
from src.ai.analyst import AnalysisInput, generate_analysis, assert_no_fabricated_numbers

FORBIDDEN_PHRASES = [
    "buy eur", "sell eur", "buy gbp", "sell gbp", "cot predicts", "will rise", "will fall",
    "proves", "guarantees", "ai thinks",
]


class TestAiAnalyst(unittest.TestCase):
    def _sample_input(self):
        return AnalysisInput(
            market="EUR",
            regime="Bullish Reversal",
            regime_reasons=["leveraged_funds_pct_52w < 10 (actual: 8)", "asset_manager_chg_4w >= 0 (actual: 1200)"],
            horizon_stats={
                4: {"n": 37, "win_rate": 0.62, "median_return": 0.011, "base_rate": 0.51, "edge_pp": 11.0, "sample_quality": "Good"},
                8: {"n": 37, "win_rate": 0.68, "median_return": 0.0121, "base_rate": 0.53, "edge_pp": 15.0, "sample_quality": "Good"},
                26: {"n": 8, "win_rate": None, "median_return": None, "base_rate": None, "edge_pp": None, "sample_quality": "Insufficient sample size"},
            },
            contradictions=["Dealer positioning has not confirmed the move."],
            divergences=["Asset Managers net up 4W while Leveraged Funds net down 4W."],
        )

    def test_no_fabricated_numbers(self):
        data = self._sample_input()
        text = generate_analysis(data)
        untraceable = assert_no_fabricated_numbers(text, data)
        self.assertEqual(untraceable, [], f"Found numbers not traceable to input stats: {untraceable}")

    def test_insufficient_sample_horizon_gets_no_strong_claim(self):
        data = self._sample_input()
        text = generate_analysis(data)
        self.assertIn("Insufficient sample size", text)

    def test_never_uses_forbidden_signal_language(self):
        data = self._sample_input()
        text = generate_analysis(data).lower()
        for phrase in FORBIDDEN_PHRASES:
            self.assertNotIn(phrase, text)

    def test_contains_hedged_language_not_directive(self):
        data = self._sample_input()
        text = generate_analysis(data)
        self.assertIn("not a price", text.lower() if False else text)  # conclusion disclaimer present
        self.assertTrue("Historical evidence" in text or "does not establish" in text)

    def test_regime_and_reasons_appear_verbatim(self):
        data = self._sample_input()
        text = generate_analysis(data)
        self.assertIn("Bullish Reversal", text)
        for reason in data.regime_reasons:
            self.assertIn(reason, text)

    def test_fabricated_number_is_actually_detected_by_the_checker(self):
        # Sanity check on the checker itself: inject a number that is NOT
        # in the input and confirm it gets flagged.
        data = self._sample_input()
        text = generate_analysis(data) + "\nSecretly the true win rate is 99.9%."
        untraceable = assert_no_fabricated_numbers(text, data)
        self.assertIn("99.9", untraceable)


if __name__ == "__main__":
    unittest.main()
