"""
src/analogs/sampling.py

Перекрывающиеся наблюдения — главная причина, по которой статистика в
COT-исследованиях выглядит убедительнее, чем есть.

Недельные наблюдения с горизонтом 8 недель делят между собой 7 недель из
8. Сорок таких наблюдений — это НЕ сорок независимых испытаний. Любой
обычный доверительный интервал и любое p-value, посчитанные на них,
слишком узкие и слишком уверенные.

Три режима выборки, между которыми можно переключаться:

  RAW          все недельные наблюдения. Максимум данных, минимум
               независимости. Годится посмотреть, не годится для выводов.

  NON_OVERLAP  каждое h-е наблюдение, где h — горизонт. Для 8 недель:
               1, 9, 17, ... Наблюдения не делят историю цены вовсе.
               Данных мало, зато они честные.

  BLOCK        все наблюдения, но интервалы строятся блочным бутстрапом
               с длиной блока, равной горизонту. Компромисс: сохраняет
               объём и учитывает зависимость.

Плюс оценка эффективного размера выборки: сколько независимых наблюдений
примерно соответствует имеющемуся набору.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import numpy as np
import pandas as pd


class SamplingMode(str, Enum):
    RAW = "raw"
    NON_OVERLAP = "non_overlap"
    BLOCK = "block"


MODE_RU = {
    SamplingMode.RAW: "Все недели (перекрываются)",
    SamplingMode.NON_OVERLAP: "Без перекрытия",
    SamplingMode.BLOCK: "Блочный бутстрап",
}


def non_overlapping_index(index: pd.Index, horizon_weeks: int) -> pd.Index:
    """Каждое h-е наблюдение: соседние не делят историю цены."""
    if horizon_weeks <= 1:
        return index
    return index[::horizon_weeks]


def effective_n(n: int, horizon_weeks: int) -> int:
    """
    Грубая оценка эффективного размера выборки для перекрывающихся
    наблюдений: n / h. Это стандартное приближение — при полном
    перекрытии h-недельных окон независимой оказывается примерно каждая
    h-я точка. Оценка сознательно консервативная: лучше недооценить
    уверенность, чем переоценить.
    """
    if horizon_weeks <= 1:
        return n
    return max(1, int(round(n / horizon_weeks)))


def block_bootstrap_ci(values: pd.Series, horizon_weeks: int, statistic="median",
                        iterations: int = 2000, ci: tuple = (2.5, 97.5),
                        seed: int = 42) -> Optional[tuple[float, float]]:
    """
    Блочный бутстрап: ресэмплируются не отдельные точки, а непрерывные
    блоки длиной с горизонт. Так сохраняется локальная зависимость,
    которую обычный бутстрап разрушает — и из-за чего он даёт слишком
    узкие интервалы.
    """
    v = values.dropna().to_numpy(dtype=float)
    n = len(v)
    if n < 10:
        return None
    block = max(1, min(horizon_weeks, n))
    n_blocks = max(1, int(np.ceil(n / block)))
    rng = np.random.default_rng(seed)
    fn = {"median": np.median, "mean": np.mean,
          "win_rate": lambda x: float((x > 0).mean())}[statistic]

    out = np.empty(iterations)
    max_start = n - block
    for i in range(iterations):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([v[s:s + block] for s in starts])[:n]
        out[i] = fn(sample)
    lo, hi = np.percentile(out, ci)
    return float(lo), float(hi)


def iid_bootstrap_ci(values: pd.Series, statistic="median", iterations: int = 2000,
                      ci: tuple = (2.5, 97.5), seed: int = 42) -> Optional[tuple[float, float]]:
    v = values.dropna().to_numpy(dtype=float)
    if len(v) < 10:
        return None
    rng = np.random.default_rng(seed)
    fn = {"median": np.median, "mean": np.mean,
          "win_rate": lambda x: float((x > 0).mean())}[statistic]
    out = np.empty(iterations)
    for i in range(iterations):
        out[i] = fn(v[rng.integers(0, len(v), size=len(v))])
    lo, hi = np.percentile(out, ci)
    return float(lo), float(hi)


@dataclass
class SampleSummary:
    mode: str
    mode_ru: str
    horizon_weeks: int
    raw_n: int
    used_n: int
    effective_n: int
    win_rate: Optional[float]
    median_return: Optional[float]
    mean_return: Optional[float]
    ci_method: str
    ci_median: Optional[tuple]
    ci_win_rate: Optional[tuple]
    quality: str
    note: str


QUALITY_THRESHOLDS = [(10, "Недостаточно"), (20, "Слабая"), (40, "Умеренная"), (80, "Хорошая")]


def quality_label(eff_n: int) -> str:
    """Качество оценивается по ЭФФЕКТИВНОМУ размеру, а не по сырому:
    сырой при перекрытии обманывает."""
    for threshold, label in QUALITY_THRESHOLDS:
        if eff_n < threshold:
            return label
    return "Сильная"


def summarize(returns: pd.Series, horizon_weeks: int, mode: SamplingMode) -> SampleSummary:
    raw = returns.dropna()
    raw_n = len(raw)

    if mode is SamplingMode.NON_OVERLAP:
        used = raw.loc[non_overlapping_index(raw.index, horizon_weeks)]
        eff = len(used)
        ci_method = "IID бутстрап по непересекающимся наблюдениям"
        ci_med = iid_bootstrap_ci(used, "median")
        ci_win = iid_bootstrap_ci(used, "win_rate")
        note = (f"Взято каждое {horizon_weeks}-е наблюдение, чтобы окна не пересекались. "
                f"Данных меньше ({len(used)} против {raw_n}), но они независимы.")
    elif mode is SamplingMode.BLOCK:
        used = raw
        eff = effective_n(raw_n, horizon_weeks)
        ci_method = f"Блочный бутстрап, длина блока {horizon_weeks} нед."
        ci_med = block_bootstrap_ci(used, horizon_weeks, "median")
        ci_win = block_bootstrap_ci(used, horizon_weeks, "win_rate")
        note = ("Использованы все наблюдения, но интервалы построены блоками — "
                "это учитывает, что соседние окна делят историю цены.")
    else:
        used = raw
        eff = effective_n(raw_n, horizon_weeks)
        ci_method = "IID бутстрап (не учитывает перекрытие)"
        ci_med = iid_bootstrap_ci(used, "median")
        ci_win = iid_bootstrap_ci(used, "win_rate")
        note = (f"Наблюдения перекрываются: соседние делят {horizon_weeks - 1} недель из "
                f"{horizon_weeks}. Интервал здесь заведомо слишком узкий — смотрите на "
                f"эффективный размер {eff}, а не на {raw_n}.")

    if len(used) == 0:
        return SampleSummary(mode.value, MODE_RU[mode], horizon_weeks, raw_n, 0, 0,
                              None, None, None, ci_method, None, None, "Недостаточно",
                              "Нет отработавших наблюдений.")

    return SampleSummary(
        mode=mode.value, mode_ru=MODE_RU[mode], horizon_weeks=horizon_weeks,
        raw_n=raw_n, used_n=len(used), effective_n=eff,
        win_rate=float((used > 0).mean()),
        median_return=float(used.median()),
        mean_return=float(used.mean()),
        ci_method=ci_method, ci_median=ci_med, ci_win_rate=ci_win,
        quality=quality_label(eff if mode is not SamplingMode.NON_OVERLAP else len(used)),
        note=note,
    )


def summarize_all_modes(returns: pd.Series, horizon_weeks: int) -> dict:
    return {m.value: summarize(returns, horizon_weeks, m) for m in SamplingMode}
