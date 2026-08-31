"""
src/analogs/multiple_testing.py

Поправка на множественное тестирование и разделение режимов исследования.

Проблема простая и разрушительная: если перебрать 500 условий, штук 25
покажут p < 0.05 просто по случайности. Найденное так «преимущество»
существует только в том наборе данных, на котором его искали.

Отсюда два режима:

  РАЗВЕДКА (discovery)     — можно перебирать что угодно, но ни один
                             результат не считается подтверждённым.
  ПОДТВЕРЖДЕНИЕ            — гипотеза зафиксирована ДО того, как увидели
  (confirmatory)             результат, и проверяется на отложенных данных.

Переход между ними односторонний: увидев результат, нельзя задним числом
объявить гипотезу заранее заданной.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
import numpy as np


class ResearchMode(str, Enum):
    DISCOVERY = "discovery"
    CONFIRMATORY = "confirmatory"


MODE_RU = {
    ResearchMode.DISCOVERY: "Разведка",
    ResearchMode.CONFIRMATORY: "Подтверждение",
}


def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> dict:
    """
    Поправка Бенджамини-Хохберга: контролирует долю ложных открытий
    среди отвергнутых гипотез.

    Выбрана вместо Бонферрони потому, что при сотнях проверок Бонферрони
    настолько строг, что не пропускает и настоящий эффект. BH мягче и
    отвечает на практический вопрос: «какая доля моих находок — мусор».
    """
    clean = [(i, p) for i, p in enumerate(p_values) if p is not None and not np.isnan(p)]
    m = len(clean)
    if m == 0:
        return {"m": 0, "rejected": [], "threshold": None, "alpha": alpha}

    ordered = sorted(clean, key=lambda t: t[1])
    threshold_p = None
    k_max = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= alpha * rank / m:
            threshold_p, k_max = p, rank

    rejected = [i for i, p in ordered[:k_max]]
    return {"m": m, "rejected": sorted(rejected), "threshold": threshold_p,
            "alpha": alpha, "n_rejected": len(rejected)}


@dataclass
class Hypothesis:
    """Зафиксированная гипотеза. После заморозки пороги менять нельзя."""
    hid: str
    condition_text: str
    market: str
    horizon_weeks: int
    features: list = field(default_factory=list)
    frozen_at: str = ""
    train_end: Optional[str] = None      # данные до этой даты — обучение
    mode: str = ResearchMode.DISCOVERY.value
    prior_tests_when_created: int = 0
    note: str = ""

    def freeze(self, train_end: date, prior_tests: int) -> "Hypothesis":
        self.frozen_at = datetime.now(timezone.utc).isoformat()
        self.train_end = train_end.isoformat()
        self.mode = ResearchMode.CONFIRMATORY.value
        self.prior_tests_when_created = prior_tests
        return self


def snooping_warning(n_tests: int, best_p: Optional[float] = None) -> Optional[str]:
    """
    Предупреждение, привязанное к числу проверок, а не общая фраза.
    Считает, сколько «значимых» результатов ожидается на чистом шуме.
    """
    if n_tests <= 1:
        return None
    expected_false = n_tests * 0.05
    base = (f"Проверено гипотез: {n_tests}. На чистом шуме при пороге 0.05 "
            f"ожидается около {expected_false:.0f} «значимых» результатов просто "
            f"по случайности.")
    if n_tests > 20:
        base += (" Это уже территория подгонки: одиночное p-значение здесь почти "
                 "ничего не стоит без проверки на отложенных данных.")
    if best_p is not None and best_p > 0.05 / max(n_tests, 1):
        base += (f" Лучшее найденное p={best_p:.4f} не проходит даже грубый порог "
                 f"Бонферрони ({0.05/n_tests:.5f}).")
    return base


def assess_run(p_values: list[float], mode: ResearchMode, alpha: float = 0.05) -> dict:
    bh = benjamini_hochberg(p_values, alpha)
    valid = [p for p in p_values if p is not None and not np.isnan(p)]
    best = min(valid) if valid else None

    if mode is ResearchMode.DISCOVERY:
        verdict = ("Режим разведки. Ни один результат здесь не считается подтверждённым, "
                   "каким бы убедительным ни выглядел. Чтобы проверить находку, "
                   "зафиксируйте гипотезу и прогоните на отложенных данных.")
    else:
        verdict = ("Режим подтверждения: гипотеза зафиксирована до просмотра результата "
                   "и проверяется на данных, не участвовавших в её выборе.")

    return {
        "mode": mode.value, "mode_ru": MODE_RU[mode],
        "n_tests": len(p_values), "best_p": best,
        "bh": bh,
        "warning": snooping_warning(len(p_values), best),
        "verdict": verdict,
    }
