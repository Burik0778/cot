import unittest
from config.markets import (
    MARKETS, all_codes, market, spec_key, slow_key, slow_is_contrarian,
    PARTICIPANTS_BY_REPORT, PARTICIPANT_RU, PARTICIPANT_ROLE_RU, SECTORS_RU, TFF, DISAGGREGATED,
)


class TestRegistryIntegrity(unittest.TestCase):
    """Реестр правился скриптом, и однажды замена попала не в то поле —
    код рынка стал строкой поиска контракта. Эти проверки ловят такое."""

    def test_codes_are_clean_identifiers(self):
        for c in all_codes():
            self.assertNotIn("|", c, f"код рынка {c!r} содержит разделитель вариантов")
            self.assertNotIn(" ", c, f"код рынка {c!r} содержит пробел")
            self.assertTrue(c.isupper(), f"код рынка {c!r} не в верхнем регистре")
            self.assertLessEqual(len(c), 10, f"код рынка {c!r} подозрительно длинный")

    def test_codes_unique(self):
        codes = all_codes()
        self.assertEqual(len(codes), len(set(codes)))

    def test_every_market_has_a_search_pattern(self):
        for m in MARKETS:
            self.assertTrue(m.cftc_match.strip(), f"{m.code}: пустая строка поиска")

    def test_search_pattern_is_not_the_code(self):
        # Симптом той самой порчи: поле поиска совпало с кодом
        for m in MARKETS:
            if m.code in ("COPPER", "PLATINUM", "BITCOIN"):
                continue
            self.assertNotEqual(m.cftc_match, m.code, f"{m.code}: строка поиска равна коду")

    def test_sectors_are_known(self):
        for m in MARKETS:
            self.assertIn(m.sector, SECTORS_RU, f"{m.code}: неизвестный сектор {m.sector}")

    def test_reports_are_known(self):
        for m in MARKETS:
            self.assertIn(m.report, (TFF, DISAGGREGATED))


class TestRoles(unittest.TestCase):
    def test_roles_exist_in_their_report_participants(self):
        for m in MARKETS:
            parts = PARTICIPANTS_BY_REPORT[m.report]
            self.assertIn(spec_key(m.code), parts, f"{m.code}: spec не в списке групп")
            self.assertIn(slow_key(m.code), parts, f"{m.code}: slow не в списке групп")

    def test_every_participant_has_russian_label_and_role(self):
        for parts in PARTICIPANTS_BY_REPORT.values():
            for p in parts:
                self.assertIn(p, PARTICIPANT_RU)
                self.assertIn(p, PARTICIPANT_ROLE_RU)

    def test_only_commodities_use_hedger_logic(self):
        for m in MARKETS:
            self.assertEqual(slow_is_contrarian(m.code), m.report == DISAGGREGATED,
                              f"{m.code}: неверный флаг хеджеров")

    def test_metals_are_disaggregated(self):
        for m in MARKETS:
            if m.sector == "METALS":
                self.assertEqual(m.report, DISAGGREGATED, f"{m.code}: металл должен быть в Disaggregated")

    def test_fx_indices_crypto_rates_are_tff(self):
        for m in MARKETS:
            if m.sector in ("FX", "INDICES", "CRYPTO", "RATES"):
                self.assertEqual(m.report, TFF, f"{m.code}: должен быть в TFF")


class TestQuoteDirection(unittest.TestCase):
    def test_usd_base_pairs_are_inverse(self):
        for code in ("JPY", "CAD", "CHF", "MXN"):
            self.assertTrue(market(code).price_is_inverse, f"{code}: должен быть перевёрнут")

    def test_other_markets_are_not_inverse(self):
        for code in ("EUR", "GBP", "AUD", "NZD", "SP500", "BTC", "GOLD"):
            self.assertFalse(market(code).price_is_inverse, f"{code}: не должен быть перевёрнут")


if __name__ == "__main__":
    unittest.main()
