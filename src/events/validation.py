"""
src/events/validation.py

Проверка на истории: «были ли подсказки в отчётах перед крупными движениями».

Главная ловушка такого исследования — искать только там, где движение
случилось. Если взять график, найти разворот и посмотреть, что говорил COT
перед ним, что-нибудь найдётся почти всегда: позиционирование постоянно
где-то в крайности. Такой поиск подтверждает любую гипотезу.

Правильный ответ даёт таблица сопряжённости 2×2:

                        | движение было | движения не было
    условие выполнялось |       A       |        B
    условие не выполн.  |       C       |        D

Если B сильно больше A, то условие не предупреждает ни о чём, сколько бы
красивых отдельных примеров ни нашлось. Именно это и надо увидеть, а не
подборку удачных случаев.

Отсюда два обязательных требования к методу:
  1. Событие определяется ФОРМУЛОЙ до того, как посмотрели на COT.
     Иначе критерий бессознательно подгоняется под случаи, где сработало.
  2. Считаются все четыре клетки, а не только A.

Look-ahead: условие проверяется на данных, доступных НА дату наблюдения
(availability_date), а событие ищется строго ПОСЛЕ неё.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class EventDefinition:
    """Механическое определение «крупного движения»."""
    key: str
    name: str
    description: str
    threshold: float       # порог движения, доля (0.05 = 5%)
    horizon_weeks: int     # за сколько недель движение должно произойти
    direction: str         # "up" | "down" | "any"


EVENT_DEFS: list[EventDefinition] = [
    EventDefinition("up5_8w", "Рост 5%+ за 8 недель",
                     "Цена инструмента выросла минимум на 5% в течение 8 недель после наблюдения.",
                     0.05, 8, "up"),
    EventDefinition("down5_8w", "Падение 5%+ за 8 недель",
                     "Цена инструмента упала минимум на 5% в течение 8 недель после наблюдения.",
                     0.05, 8, "down"),
    EventDefinition("move8_12w", "Движение 8%+ за 12 недель",
                     "Цена прошла минимум 8% в любую сторону в течение 12 недель.",
                     0.08, 12, "any"),
    EventDefinition("up10_26w", "Рост 10%+ за 26 недель",
                     "Крупное среднесрочное движение вверх в течение полугода.",
                     0.10, 26, "up"),
    EventDefinition("down10_26w", "Падение 10%+ за 26 недель",
                     "Крупное среднесрочное движение вниз в течение полугода.",
                     0.10, 26, "down"),
]


@dataclass
class Condition:
    """Признак в отчёте, который проверяем как «подсказку»."""
    key: str
    name: str
    description: str


CONDITIONS: list[Condition] = [
    Condition("spec_extreme_low", "Спекулянты у нижней границы",
              "Чистая позиция быстрых денег в нижних 10% своего годового диапазона."),
    Condition("spec_extreme_high", "Спекулянты у верхней границы",
              "Чистая позиция быстрых денег в верхних 10% своего годового диапазона."),
    Condition("spec_turning_up", "Разворот вверх с низов",
              "Позиция в нижних 20% диапазона И растёт две недели подряд. "
              "Не сам экстремум, а начало выхода из него."),
    Condition("spec_turning_down", "Разворот вниз с верхов",
              "Позиция в верхних 20% диапазона И падает две недели подряд."),
    Condition("divergence", "Расхождение медленных и быстрых",
              "Быстрые и медленные деньги двигались за 4 недели в противоположные стороны."),
    Condition("short_covering", "Рост нетто за счёт закрытия шортов",
              "Чистая позиция выросла, но лонг почти не менялся — растёт за счёт выбивания шортов, "
              "а не притока покупателей."),
]


def _price_forward_extremes(price_weekly: pd.Series, horizon: int) -> tuple[pd.Series, pd.Series]:
    """Максимальный рост и максимальное падение в течение horizon недель вперёд."""
    n = len(price_weekly)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    vals = price_weekly.to_numpy(dtype=float)
    for i in range(n):
        end = min(i + horizon + 1, n)
        if end - i < 2:
            continue
        window = vals[i + 1:end]
        window = window[~np.isnan(window)]
        if not len(window) or np.isnan(vals[i]) or vals[i] == 0:
            continue
        up[i] = window.max() / vals[i] - 1.0
        dn[i] = window.min() / vals[i] - 1.0
    return pd.Series(up, index=price_weekly.index), pd.Series(dn, index=price_weekly.index)


def detect_events(states: pd.DataFrame, ev: EventDefinition,
                   price_col: str = "price_close") -> pd.Series:
    """
    Булев ряд: произошло ли событие ПОСЛЕ каждого наблюдения.
    NaN там, где горизонт ещё не отработал — такие строки в статистику не
    попадают, иначе незрелые наблюдения считались бы за «события не было».
    """
    if price_col not in states.columns:
        return pd.Series([np.nan] * len(states), index=states.index)
    up, dn = _price_forward_extremes(states[price_col], ev.horizon_weeks)
    if ev.direction == "up":
        out = up >= ev.threshold
    elif ev.direction == "down":
        out = dn <= -ev.threshold
    else:
        out = (up >= ev.threshold) | (dn <= -ev.threshold)
    immature = up.isna() & dn.isna()
    return out.where(~immature, other=np.nan)


def evaluate_condition(states: pd.DataFrame, cond: Condition, spec: str, slow: str) -> pd.Series:
    """Булев ряд: выполнялось ли условие на дату наблюдения."""
    g = lambda c: states[c] if c in states.columns else pd.Series([np.nan] * len(states), index=states.index)
    pct = g(f"{spec}_pct_52w")
    up_streak = g(f"{spec}_streak_up_weeks")
    dn_streak = g(f"{spec}_streak_down_weeks")

    if cond.key == "spec_extreme_low":
        return pct <= 10
    if cond.key == "spec_extreme_high":
        return pct >= 90
    if cond.key == "spec_turning_up":
        return (pct <= 20) & (up_streak >= 2)
    if cond.key == "spec_turning_down":
        return (pct >= 80) & (dn_streak >= 2)
    if cond.key == "divergence":
        a, b = g(f"{spec}_chg_4w"), g(f"{slow}_chg_4w")
        return (a * b) < 0
    if cond.key == "short_covering":
        net_chg, long_chg = g(f"{spec}_chg_1w"), g(f"{spec}_long_chg_1w")
        # нетто заметно вырос, а лонг дал меньше трети прироста
        return (net_chg > 0) & (long_chg.abs() < net_chg.abs() / 3)
    return pd.Series([np.nan] * len(states), index=states.index)


@dataclass
class ValidationResult:
    condition: str
    condition_desc: str
    event: str
    event_desc: str
    a: int          # условие есть, движение было
    b: int          # условие есть, движения не было
    c: int          # условия нет, движение было
    d: int          # условия нет, движения не было
    rate_with: Optional[float]      # A / (A+B)
    rate_without: Optional[float]   # C / (C+D)
    base_rate: Optional[float]      # (A+C) / всего
    lift_pp: Optional[float]        # (rate_with - base_rate) в п.п.
    n_condition: int
    verdict: str
    dates: list[str] = field(default_factory=list)


MIN_OCCURRENCES = 20


def validate(states: pd.DataFrame, cond: Condition, ev: EventDefinition,
             spec: str, slow: str, date_col: str = "report_date") -> ValidationResult:
    happened = detect_events(states, ev)
    holds = evaluate_condition(states, cond, spec, slow)

    usable = happened.notna() & holds.notna()
    h = happened[usable].astype(bool)
    c_ = holds[usable].astype(bool)

    a = int((c_ & h).sum())
    b = int((c_ & ~h).sum())
    cc = int((~c_ & h).sum())
    d = int((~c_ & ~h).sum())
    n_cond = a + b
    total = a + b + cc + d

    rate_with = a / n_cond if n_cond else None
    rate_without = cc / (cc + d) if (cc + d) else None
    base = (a + cc) / total if total else None
    lift = (rate_with - base) * 100 if (rate_with is not None and base is not None) else None

    if n_cond < MIN_OCCURRENCES:
        verdict = (f"Условие встречалось всего {n_cond} раз — этого мало для вывода. "
                   f"Ни подтвердить, ни опровергнуть на такой выборке нельзя.")
    elif lift is None:
        verdict = "Недостаточно данных для сравнения."
    elif abs(lift) < 5:
        verdict = (f"Разница с обычной вероятностью {lift:+.1f} п.п. — это шум. "
                   f"Условие не даёт предупреждения: движение случалось примерно так же часто "
                   f"и без него.")
    elif lift > 0:
        verdict = (f"После этого условия движение случалось в {rate_with * 100:.0f}% случаев "
                   f"против обычных {base * 100:.0f}%. Перевес {lift:+.1f} п.п. "
                   f"Но обратите внимание на клетку B: в {b} случаях условие выполнялось, "
                   f"а движения не было.")
    else:
        verdict = (f"После этого условия движение случалось РЕЖЕ обычного: "
                   f"{rate_with * 100:.0f}% против {base * 100:.0f}%, {lift:+.1f} п.п.")

    dates = states.loc[usable & holds.fillna(False).astype(bool), date_col].astype(str).tolist()

    return ValidationResult(
        condition=cond.name, condition_desc=cond.description,
        event=ev.name, event_desc=ev.description,
        a=a, b=b, c=cc, d=d,
        rate_with=rate_with, rate_without=rate_without, base_rate=base, lift_pp=lift,
        n_condition=n_cond, verdict=verdict, dates=dates[-40:],
    )


def validate_all(states: pd.DataFrame, spec: str, slow: str) -> list[dict]:
    """Все сочетания условие × событие для одного рынка."""
    out = []
    for cond in CONDITIONS:
        for ev in EVENT_DEFS:
            r = validate(states, cond, ev, spec, slow)
            out.append({
                "cond_key": cond.key, "cond": r.condition, "cond_desc": r.condition_desc,
                "ev_key": ev.key, "ev": r.event, "ev_desc": r.event_desc,
                "a": r.a, "b": r.b, "c": r.c, "d": r.d,
                "rate_with": r.rate_with, "rate_without": r.rate_without,
                "base_rate": r.base_rate, "lift_pp": r.lift_pp,
                "n": r.n_condition, "verdict": r.verdict, "dates": r.dates,
            })
    return out
