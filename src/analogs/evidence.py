"""
src/analogs/evidence.py

Доказательная база под каждым утверждением о преимуществе.

Требование простое: увидев «Historical Edge +14 pp», пользователь должен
нажать ПОЧЕМУ и получить всё, на чём этот вывод стоит — N, базовую
ставку, размер выборки без перекрытия, блочный доверительный интервал,
условия, признаки, период и источник данных.

Если чего-то из этого нет, преимущество не считается доказанным. Это не
украшение интерфейса, а критерий: утверждение без предъявленной основы
не должно выглядеть как результат.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Optional
import pandas as pd

from src.analogs.sampling import SamplingMode, summarize, summarize_all_modes


@dataclass
class EdgeEvidence:
    """Всё, на чём стоит утверждение о преимуществе."""
    market: str
    horizon_weeks: int
    analog_mode: str                # cot_only | cot_price
    analog_mode_ru: str

    # Основные цифры
    conditional_rate: Optional[float]
    base_rate: Optional[float]
    edge_pp: Optional[float]
    median_return: Optional[float]
    base_median_return: Optional[float]

    # Размеры выборки
    raw_n: int
    non_overlapping_n: int
    effective_n: int

    # Неопределённость
    ci_block_median: Optional[tuple]
    ci_block_win_rate: Optional[tuple]
    ci_iid_median: Optional[tuple]
    ci_method_note: str

    # Происхождение
    features: dict = field(default_factory=dict)
    conditions: list = field(default_factory=list)
    data_start: Optional[str] = None
    data_end: Optional[str] = None
    data_source: str = ""
    as_of: Optional[str] = None

    # Итог
    quality: str = ""
    verdict: str = ""
    caveats: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


MIN_EFFECTIVE_N = 10


def build_edge_evidence(
    analog_returns: pd.Series,
    population_returns: pd.Series,
    market: str,
    horizon_weeks: int,
    analog_mode: str,
    analog_mode_ru: str,
    features: dict,
    conditions: list,
    data_start: Optional[str] = None,
    data_end: Optional[str] = None,
    data_source: str = "CFTC + FRED/Stooq",
    as_of: Optional[str] = None,
) -> EdgeEvidence:
    r = analog_returns.dropna()
    pop = population_returns.dropna()

    modes = summarize_all_modes(r, horizon_weeks)
    raw = modes[SamplingMode.RAW.value]
    nov = modes[SamplingMode.NON_OVERLAP.value]
    blk = modes[SamplingMode.BLOCK.value]

    cond_rate = float((r > 0).mean()) if len(r) else None
    base_rate = float((pop > 0).mean()) if len(pop) else None
    edge = (cond_rate - base_rate) * 100 if (cond_rate is not None and base_rate is not None) else None

    caveats = [
        "Наблюдения недельные, горизонт многонедельный — соседние делят почти всю "
        f"историю цены. Ориентируйтесь на эффективный размер ({raw.effective_n}), "
        f"а не на сырой ({raw.raw_n}).",
        "Историческая связь не означает причины. COT не двигает цену; совпадение "
        "может объясняться третьим фактором.",
        "Данные отражают позиции на вторник и публикуются в пятницу — решение по ним "
        "принимается минимум через три дня после замера.",
    ]

    # Порог доказанности — по эффективному размеру, а не по сырому.
    if raw.effective_n < MIN_EFFECTIVE_N:
        verdict = (f"Преимущество НЕ доказано: эффективный размер выборки {raw.effective_n} "
                   f"при сырых {raw.raw_n}. На таком количестве независимых наблюдений "
                   f"разница неотличима от случайности.")
    elif edge is None:
        verdict = "Недостаточно данных для сравнения с базовой ставкой."
    elif abs(edge) < 5:
        verdict = (f"Разница с базовой ставкой {edge:+.1f} п.п. — в пределах шума. "
                   f"Преимущества нет.")
    else:
        ci = blk.ci_win_rate
        crosses = (ci is not None and base_rate is not None and ci[0] <= base_rate <= ci[1])
        if crosses:
            verdict = (f"Разница {edge:+.1f} п.п., но блочный доверительный интервал доли "
                       f"[{ci[0]*100:.0f}%, {ci[1]*100:.0f}%] накрывает базовую ставку "
                       f"{base_rate*100:.0f}%. Преимущество не подтверждено с учётом "
                       f"зависимости наблюдений.")
        else:
            verdict = (f"Разница {edge:+.1f} п.п. Блочный интервал доли не накрывает базовую "
                       f"ставку — с учётом перекрытия наблюдений результат устойчив. "
                       f"Это по-прежнему наблюдение на истории, а не гарантия.")

    return EdgeEvidence(
        market=market, horizon_weeks=horizon_weeks,
        analog_mode=analog_mode, analog_mode_ru=analog_mode_ru,
        conditional_rate=cond_rate, base_rate=base_rate, edge_pp=edge,
        median_return=raw.median_return,
        base_median_return=float(pop.median()) if len(pop) else None,
        raw_n=raw.raw_n, non_overlapping_n=nov.used_n, effective_n=raw.effective_n,
        ci_block_median=blk.ci_median, ci_block_win_rate=blk.ci_win_rate,
        ci_iid_median=raw.ci_median,
        ci_method_note=(f"Блочный бутстрап, длина блока {horizon_weeks} нед. "
                        f"Обычный IID-интервал показан для сравнения: он заведомо уже, "
                        f"потому что не учитывает зависимость соседних наблюдений."),
        features=dict(features), conditions=list(conditions),
        data_start=data_start, data_end=data_end, data_source=data_source, as_of=as_of,
        quality=raw.quality, verdict=verdict, caveats=caveats,
    )
