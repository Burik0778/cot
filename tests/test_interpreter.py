import unittest
from src.ai.interpreter import InterpretationInput, interpret, _level_label


def _base(**kw):
    defaults = dict(
        market="EUR", pair_symbol="EURUSD", participant="leveraged_funds",
        net=-57716, net_oi=-0.07, pct_52w=8.0, pct_156w=3.0,
        chg_1w=800, chg_4w=2800, streak_up_weeks=3, streak_down_weeks=0,
        horizon_weeks=8, n_analogs=37, analog_win_rate=0.64, base_rate=0.53,
        edge_pp=11.0, sample_quality="Moderate", contradictions=[],
    )
    defaults.update(kw)
    return InterpretationInput(**defaults)


class TestLevelLabels(unittest.TestCase):
    def test_extremes_and_middle(self):
        self.assertEqual(_level_label(2), "экстремальный шорт")
        self.assertEqual(_level_label(12), "сильный шорт")
        self.assertEqual(_level_label(50), "нейтрально")
        self.assertEqual(_level_label(85), "сильный лонг")
        self.assertEqual(_level_label(98), "экстремальный лонг")

    def test_missing_percentile_is_not_guessed(self):
        self.assertEqual(_level_label(None), "неизвестно")


class TestInterpreter(unittest.TestCase):
    def test_all_five_sections_present(self):
        out = interpret(_base())
        for section in ["ФАКТ", "ЧТО ЭТО ЗНАЧИТ", "ЧЕГО ЭТО НЕ ЗНАЧИТ", "ИСТОРИЯ", "ПРОТИВ ЭТОГО ВЫВОДА"]:
            self.assertIn(section, out)

    def test_crowded_short_is_described_as_crowded(self):
        out = interpret(_base(pct_52w=8.0, net_oi=-0.07))
        self.assertIn("переполнена вниз", out)
        self.assertIn("шорт-сквиз", out)

    def test_crowded_long_is_described_correctly(self):
        out = interpret(_base(pct_52w=96.0, net_oi=0.30, streak_up_weeks=0, streak_down_weeks=3, chg_4w=-2000))
        self.assertIn("переполнена вверх", out)

    def test_neutral_positioning_says_it_means_little(self):
        out = interpret(_base(pct_52w=50.0))
        self.assertIn("говорит мало", out)

    def test_turning_from_extreme_is_highlighted(self):
        out = interpret(_base(pct_52w=8.0, streak_up_weeks=3, chg_4w=2800))
        self.assertIn("разворачиваться вверх", out)

    def test_insufficient_sample_blocks_statistics(self):
        out = interpret(_base(n_analogs=5, sample_quality="Insufficient sample size"))
        self.assertIn("мало для любого вывода", out)
        self.assertNotIn("Перевес над обычной", out)

    def test_small_edge_is_called_noise(self):
        out = interpret(_base(edge_pp=2.0))
        self.assertIn("в пределах шума", out)

    def test_lag_caveat_always_present(self):
        out = interpret(_base())
        self.assertIn("вторник", out)
        self.assertIn("пятницу", out)

    def test_overlap_caveat_always_present(self):
        out = interpret(_base())
        self.assertIn("перекрываются", out)

    def test_never_calls_itself_a_signal(self):
        out = interpret(_base())
        self.assertIn("не сигнал на вход", out.replace("Не значит, что это сигнал на вход", "не сигнал на вход"))

    def test_no_number_appears_that_was_not_supplied(self):
        # Every long digit-run in the output must trace to an input value.
        import re
        data = _base()
        out = interpret(data)
        allowed = set()
        for v in [data.net, data.net_oi, data.pct_52w, data.pct_156w, data.chg_4w,
                  data.streak_up_weeks, data.horizon_weeks, data.n_analogs,
                  data.analog_win_rate, data.base_rate, data.edge_pp]:
            if v is None:
                continue
            allowed.update({str(abs(v)), f"{abs(v):.0f}", f"{abs(v):.1f}",
                            f"{abs(v) * 100:.0f}", f"{abs(v) * 100:.1f}",
                            f"{abs(v):,.0f}".replace(",", " ")})
        # Digits belonging to fixed domain constants in the caveat/wording
        # text rather than to data: the 3-10 day publication lag, and the "4"
        # in "за 4 недели" (the window name of the chg_4w field itself).
        allowed.update({"3", "10", "4"})
        # Sample-quality labels embed their own threshold counts ("30-49
        # наблюдений"). Derive those from the label table rather than
        # hardcoding them, so the test keeps working if thresholds change.
        from src.ai.interpreter import SAMPLE_QUALITY_RU
        for label in SAMPLE_QUALITY_RU.values():
            allowed.update(re.findall(r"\d+", label))
        found = re.findall(r"\d+(?:[ .]\d+)*", out)
        untraceable = [f for f in found if f not in allowed]
        self.assertEqual(untraceable, [], f"Числа без источника: {untraceable}")

    def test_contradictions_are_included(self):
        out = interpret(_base(contradictions=["Дилеры не подтверждают разворот."]))
        self.assertIn("Дилеры не подтверждают разворот.", out)


if __name__ == "__main__":
    unittest.main()


class TestTranslations(unittest.TestCase):
    def test_divergence_labels_are_translated_and_explained(self):
        from src.ai.interpreter import translate_divergence
        out = translate_divergence("Asset Managers vs Leveraged Funds")
        self.assertNotEqual(out, "Asset Managers vs Leveraged Funds")
        self.assertIn("медленные и быстрые деньги", out)

    def test_unknown_divergence_label_passes_through_unchanged(self):
        from src.ai.interpreter import translate_divergence
        self.assertEqual(translate_divergence("Something New"), "Something New")

    def test_sample_quality_is_shown_in_russian(self):
        out = interpret(_base(sample_quality="Moderate"))
        self.assertIn("среднее", out)
        self.assertNotIn("Moderate", out)
