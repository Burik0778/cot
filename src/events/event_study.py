"""
src/events/event_study.py

Событийный анализ с корректными до- и после-событийными окнами.

Что было не так раньше: отрицательные горизонты обращались к колонкам,
которых не существует, и молча возвращали NaN. То есть предсобытийная
часть просто отсутствовала, хотя в интерфейсе выглядела как реализованная.

Два принципиальных момента.

1. Точка 0 — это момент события, а не доходность за неделю события.
   Кумулятивная доходность в нуле равна нулю по определению. Смешивать
   «доходность на дате события» и «форвардную доходность» нельзя: это
   разные величины, и путаница между ними сдвигает всю кривую на шаг.

2. Отрицательные горизонты считаются по ПРОШЕДШЕЙ цене (trailing), а не
   по несуществующим колонкам. −4W означает: какой была цена за 4 недели
   до события относительно цены в момент события.

Плюс эпизоды: если условие держится десять недель подряд, это одно
событие, а не десять независимых. Считать их по отдельности —
самый простой способ раздуть выборку в десять раз.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd

DEFAULT_HORIZONS = [-8, -4, -2, -1, 0, 1, 2, 4, 8, 12]


@dataclass
class Episode:
    episode_id: int
    start_date: str
    end_date: str
    duration_weeks: int
    anchor_index: object          # индекс первой недели эпизода


def build_episodes(mask: pd.Series, dates: pd.Series, gap_tolerance: int = 0) -> list[Episode]:
    """
    Склеивает подряд идущие срабатывания в эпизоды.

    gap_tolerance — сколько недель разрыва ещё считать тем же эпизодом.
    По умолчанию 0: любой перерыв начинает новый.
    """
    flags = mask.fillna(False).astype(bool)
    episodes: list[Episode] = []
    start_pos = None
    last_true = None

    positions = list(range(len(flags)))
    for pos in positions:
        if flags.iloc[pos]:
            if start_pos is None:
                start_pos = pos
            last_true = pos
        else:
            if start_pos is not None and last_true is not None:
                if pos - last_true > gap_tolerance:
                    episodes.append(Episode(
                        len(episodes) + 1, str(dates.iloc[start_pos]), str(dates.iloc[last_true]),
                        last_true - start_pos + 1, mask.index[start_pos]))
                    start_pos, last_true = None, None
    if start_pos is not None and last_true is not None:
        episodes.append(Episode(
            len(episodes) + 1, str(dates.iloc[start_pos]), str(dates.iloc[last_true]),
            last_true - start_pos + 1, mask.index[start_pos]))
    return episodes


def _trailing_return(price: pd.Series, weeks: int) -> pd.Series:
    """Доходность за прошедшие `weeks` недель к текущему моменту."""
    return price / price.shift(weeks) - 1.0


def _forward_return(price: pd.Series, weeks: int) -> pd.Series:
    """Доходность вперёд. Хвост, где горизонт не отработал, остаётся NaN."""
    return price.shift(-weeks) / price - 1.0


@dataclass
class EventStudyResult:
    n_events: int
    n_episodes: int
    unit: str                       # "weeks" | "episodes"
    horizons: list
    mean: dict = field(default_factory=dict)
    median: dict = field(default_factory=dict)
    p25: dict = field(default_factory=dict)
    p75: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    event_dates: list = field(default_factory=list)
    episodes: list = field(default_factory=list)
    note: str = ""


def run_event_study(states: pd.DataFrame, event_mask: pd.Series,
                     horizons: Optional[list] = None, price_col: str = "price_close",
                     date_col: str = "report_date", use_episodes: bool = True,
                     gap_tolerance: int = 0) -> EventStudyResult:
    """
    Кумулятивная доходность вокруг события, от −8 до +12 недель.

    use_episodes=True — одно срабатывание на эпизод (по первой неделе).
    use_episodes=False — каждая неделя считается отдельным событием.
    """
    horizons = horizons or DEFAULT_HORIZONS
    states = states.reset_index(drop=True)
    mask = event_mask.reset_index(drop=True)

    if price_col not in states.columns:
        return EventStudyResult(0, 0, "weeks", horizons,
                                 note="Нет ценового ряда — событийный анализ невозможен.")

    price = states[price_col].astype(float)
    dates = states[date_col]

    episodes = build_episodes(mask, dates, gap_tolerance)
    if use_episodes:
        anchor_positions = [states.index.get_loc(e.anchor_index) for e in episodes]
        unit, note = "episodes", (
            f"Считаются эпизоды, а не недели: подряд идущие срабатывания склеены в одно "
            f"событие. Иначе {int(mask.fillna(False).sum())} недель выглядели бы как "
            f"{int(mask.fillna(False).sum())} независимых наблюдений, хотя это "
            f"{len(episodes)} эпизодов.")
    else:
        anchor_positions = [i for i in range(len(mask)) if bool(mask.fillna(False).iloc[i])]
        unit, note = "weeks", "Каждая неделя срабатывания считается отдельным событием."

    series_by_h = {}
    for h in horizons:
        if h == 0:
            # Точка отсчёта: кумулятивная доходность в момент события
            # равна нулю по определению.
            series_by_h[h] = pd.Series(0.0, index=states.index)
        elif h < 0:
            series_by_h[h] = -_trailing_return(price, -h)
        else:
            series_by_h[h] = _forward_return(price, h)

    mean, median, p25, p75, counts = {}, {}, {}, {}, {}
    for h in horizons:
        vals = series_by_h[h].iloc[anchor_positions].dropna() if anchor_positions else pd.Series(dtype=float)
        counts[h] = int(len(vals))
        mean[h] = float(vals.mean()) if len(vals) else None
        median[h] = float(vals.median()) if len(vals) else None
        p25[h] = float(vals.quantile(0.25)) if len(vals) else None
        p75[h] = float(vals.quantile(0.75)) if len(vals) else None

    return EventStudyResult(
        n_events=len(anchor_positions), n_episodes=len(episodes), unit=unit,
        horizons=horizons, mean=mean, median=median, p25=p25, p75=p75, counts=counts,
        event_dates=[str(dates.iloc[i]) for i in anchor_positions],
        episodes=[e.__dict__ for e in episodes], note=note,
    )
