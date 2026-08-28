import unittest
from src.ai.briefing_ru import Flow, BriefingInput, build_facts, decompose, oi_context


def _f(label="Хедж-фонды", **kw):
    d = dict(label=label, net=-57716, net_oi=-0.072, chg_1w=2884, chg_4w=9500, chg_13w=-12000,
             long_chg_1w=744, short_chg_1w=-2140, long_chg_4w=3000, short_chg_4w=-6500,
             pct_52w=6.0, pct_156w=4.0, z_52w=-2.10, streak_up=3, streak_down=0,
             rank_156w=6, is_spec=True)
    d.update(kw)
    return Flow(**d)


def _b(**kw):
    d = dict(market_name="Евро", report_date="2026-08-18", flows=[_f()],
             open_interest=804940, oi_chg_1w=3056, oi_chg_4w=-12000, oi_pct_52w=72.0,
             price=1.1642, price_chg_4w=-0.011, price_chg_8w=-0.008)
    d.update(kw)
    return BriefingInput(**d)


class TestDecomposition(unittest.TestCase):
    """Главное: отличить приток покупателей от выбивания шортов."""

    def test_short_covering_is_named_as_such(self):
        out = decompose(long_chg=100, short_chg=-5000)
        self.assertIn("закрывали шорт", out)
        self.assertIn("не приток покупателей", out)

    def test_genuine_buying_is_named_as_buying(self):
        out = decompose(long_chg=5000, short_chg=100)
        self.assertIn("набирали лонг", out)
        self.assertNotIn("не приток покупателей", out)

    def test_both_sides_moving_is_flagged(self):
        out = decompose(long_chg=3000, short_chg=-3000)
        self.assertIn("с двух сторон", out)

    def test_new_shorts_distinguished_from_long_liquidation(self):
        self.assertIn("наращивали шорт", decompose(100, 5000))
        self.assertIn("сокращали лонг", decompose(-5000, 100))

    def test_missing_data_returns_none(self):
        self.assertIsNone(decompose(None, 100))


class TestOpenInterest(unittest.TestCase):
    def test_new_money_detected(self):
        self.assertIn("новые деньги", oi_context(5000, 3000))

    def test_closing_detected(self):
        self.assertIn("закрытие противоположных", oi_context(-5000, 3000))

    def test_exit_detected(self):
        self.assertIn("уходят с рынка", oi_context(-5000, -3000))


class TestFacts(unittest.TestCase):
    def test_weekly_block_states_contracts_and_action(self):
        blocks = build_facts(_b())
        wk = next(b for b in blocks if "за неделю" in b["title"])
        text = " ".join(wk["lines"])
        self.assertIn("2 884", text)          # изменение в контрактах
        self.assertIn("закрывали шорт", text)  # действие, а не только направление

    def test_open_interest_block_present(self):
        blocks = build_facts(_b())
        oi = next(b for b in blocks if b["title"] == "Активность на рынке")
        self.assertIn("804 940", " ".join(oi["lines"]))

    def test_streak_block_appears_only_with_a_streak(self):
        self.assertTrue(any(b["title"] == "Устойчивые серии" for b in build_facts(_b())))
        no_streak = _b(flows=[_f(streak_up=0, streak_down=0)])
        self.assertFalse(any(b["title"] == "Устойчивые серии" for b in build_facts(no_streak)))

    def test_history_block_uses_rank_not_only_percentile(self):
        blocks = build_facts(_b())
        h = next(b for b in blocks if b["title"] == "Насколько это необычно")
        self.assertIn("из 156", " ".join(h["lines"]))

    def test_price_divergence_is_called_out(self):
        # позиция растёт, цена падает -> расхождение
        blocks = build_facts(_b(price_chg_4w=-0.02, flows=[_f(chg_4w=9000)]))
        p = next(b for b in blocks if "Цена" in b["title"])
        self.assertIn("разошлись", " ".join(p["lines"]))

    def test_price_agreement_is_called_out(self):
        blocks = build_facts(_b(price_chg_4w=0.02, flows=[_f(chg_4w=9000)]))
        p = next(b for b in blocks if "Цена" in b["title"])
        self.assertIn("в одну сторону", " ".join(p["lines"]))

    def test_no_numbers_invented_when_data_missing(self):
        empty = _b(flows=[_f(chg_1w=None, chg_4w=None, long_chg_1w=None, short_chg_1w=None)],
                    open_interest=None, oi_chg_1w=None, oi_chg_4w=None, oi_pct_52w=None,
                    price=None, price_chg_4w=None, price_chg_8w=None)
        blocks = build_facts(empty)
        text = " ".join(l for b in blocks for l in b["lines"])
        self.assertNotIn("None", text)
        self.assertNotIn("nan", text.lower())

    def test_every_block_has_lines(self):
        for b in build_facts(_b()):
            self.assertTrue(b["lines"], f"пустой блок: {b['title']}")


if __name__ == "__main__":
    unittest.main()
