import unittest
import math
from src.ai.analysis_ru import (
    AnalysisContext, ParticipantSnapshot, AnalogCase,
    describe_configuration, describe_analogs, describe_statistics,
    describe_confirmation, describe_extremes, build_full_analysis,
)


def _p(key, net_oi, pct52=50.0, pct156=50.0, chg4=0.0, up=0, down=0, net=1000):
    return ParticipantSnapshot(key=key, net=net, net_oi=net_oi, pct_52w=pct52,
                                pct_156w=pct156, chg_4w=chg4, streak_up=up, streak_down=down)


def _ctx(lf_oi=-0.07, am_oi=0.30, lf_pct=8.0, analogs=None, stats=None):
    return AnalysisContext(
        currency="EUR", pair_symbol="EURUSD", regime="Разворот вверх",
        participants={
            "leveraged_funds": _p("leveraged_funds", lf_oi, lf_pct, 3.0, 2800, up=3),
            "asset_manager": _p("asset_manager", am_oi, 82.0, 88.0, 1200, up=5),
            "dealer": _p("dealer", -0.28, 12.0, 8.0, -900, down=2),
        },
        analogs=analogs if analogs is not None else [
            AnalogCase("2021-12-07", 69.0, {8: 0.035}),
            AnalogCase("2021-10-05", 67.0, {8: 0.011}),
        ],
        horizon_stats=stats if stats is not None else {
            8: {"n": 36, "win_rate": 0.64, "base_rate": 0.54, "edge_pp": 10.0,
                "median_return": 0.0099, "sample_quality": "Moderate"},
        },
    )


class TestConfiguration(unittest.TestCase):
    def test_slow_long_fast_short_is_named_as_divergence(self):
        name, text = describe_configuration(_ctx(lf_oi=-0.07, am_oi=0.30))
        self.assertIn("Медленные деньги в лонге, быстрые в шорте", name)
        self.assertIn("неразрешённым", text)

    def test_both_short_is_named_consensus(self):
        name, text = describe_configuration(_ctx(lf_oi=-0.10, am_oi=-0.15))
        self.assertIn("консенсус вниз", name)
        self.assertIn("шорт-сквиз", text)

    def test_both_long_is_named_consensus_up(self):
        name, _ = describe_configuration(_ctx(lf_oi=0.10, am_oi=0.15))
        self.assertIn("консенсус вверх", name)

    def test_flat_positioning_is_called_mixed(self):
        name, _ = describe_configuration(_ctx(lf_oi=0.001, am_oi=0.001))
        self.assertIn("Смешанная", name)


class TestAnalogs(unittest.TestCase):
    def test_unmatured_analog_is_never_shown_as_nan(self):
        # Реальный баг, найденный при прогоне интерфейса: незрелый аналог
        # выводился как «снизилась на nan%».
        analogs = [
            AnalogCase("2026-08-11", 66.0, {8: float("nan")}),
            AnalogCase("2021-12-07", 69.0, {8: 0.035}),
        ]
        out = describe_analogs(_ctx(analogs=analogs), 8)
        self.assertNotIn("nan", out.lower())
        self.assertNotIn("2026-08-11", out)
        self.assertIn("2021-12-07", out)

    def test_none_return_is_also_skipped(self):
        analogs = [AnalogCase("2026-08-11", 66.0, {8: None}),
                    AnalogCase("2021-12-07", 69.0, {8: 0.02})]
        out = describe_analogs(_ctx(analogs=analogs), 8)
        self.assertNotIn("2026-08-11", out)

    def test_all_unmatured_says_so_plainly(self):
        analogs = [AnalogCase("2026-08-11", 66.0, {8: float("nan")})]
        out = describe_analogs(_ctx(analogs=analogs), 8)
        self.assertIn("ещё не отработал", out)

    def test_insufficient_sample_blocks_the_list(self):
        stats = {8: {"n": 4, "sample_quality": "Insufficient sample size"}}
        out = describe_analogs(_ctx(stats=stats), 8)
        self.assertIn("слишком мало", out)

    def test_at_most_five_analogs_listed(self):
        analogs = [AnalogCase(f"2020-01-{d:02d}", 60.0, {8: 0.01}) for d in range(1, 12)]
        out = describe_analogs(_ctx(analogs=analogs), 8)
        self.assertEqual(out.count("совпадение"), 5)


class TestStatistics(unittest.TestCase):
    def test_small_edge_called_noise(self):
        stats = {8: {"n": 40, "win_rate": 0.55, "base_rate": 0.53, "edge_pp": 2.0,
                      "median_return": 0.001, "sample_quality": "Moderate"}}
        self.assertIn("в пределах шума", describe_statistics(_ctx(stats=stats), 8))

    def test_large_edge_called_substantial(self):
        stats = {8: {"n": 40, "win_rate": 0.72, "base_rate": 0.52, "edge_pp": 20.0,
                      "median_return": 0.02, "sample_quality": "Good"}}
        self.assertIn("Существенный перевес", describe_statistics(_ctx(stats=stats), 8))

    def test_insufficient_makes_no_claim(self):
        stats = {8: {"n": 3, "sample_quality": "Insufficient sample size"}}
        self.assertIn("вывод не делается", describe_statistics(_ctx(stats=stats), 8))


class TestConfirmation(unittest.TestCase):
    def test_crowded_short_gives_specific_confirm_and_invalidate(self):
        confirm, invalidate = describe_confirmation(_ctx(lf_pct=8.0))
        self.assertTrue(any("сокращать шорт" in c for c in confirm))
        self.assertTrue(any("наращивают шорт" in c for c in invalidate))

    def test_middle_of_range_says_no_signal(self):
        confirm, invalidate = describe_confirmation(_ctx(lf_pct=50.0))
        self.assertTrue(any("сейчас его нет" in c for c in confirm))


class TestExtremes(unittest.TestCase):
    def test_only_extreme_groups_are_listed(self):
        lines = describe_extremes(_ctx(lf_pct=8.0))
        self.assertTrue(any("Хедж-фонды" in l for l in lines))

    def test_nothing_extreme_returns_empty(self):
        ctx = _ctx(lf_pct=50.0)
        ctx.participants["asset_manager"].pct_52w = 50.0
        ctx.participants["dealer"].pct_52w = 50.0
        self.assertEqual(describe_extremes(ctx), [])


class TestFullAssembly(unittest.TestCase):
    def test_all_sections_present(self):
        out = build_full_analysis(_ctx(), 8)
        for key in ["configuration_name", "configuration_text", "extremes",
                    "analogs", "statistics", "confirm", "invalidate", "caveats"]:
            self.assertIn(key, out)

    def test_caveats_always_include_lag_and_overlap(self):
        out = build_full_analysis(_ctx(), 8)
        joined = " ".join(out["caveats"])
        self.assertIn("вторник", joined)
        self.assertIn("перекрываются", joined)


if __name__ == "__main__":
    unittest.main()
