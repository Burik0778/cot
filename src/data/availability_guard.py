"""
src/data/availability_guard.py

Единый центральный механизм защиты от заглядывания в будущее.

Зачем отдельный модуль: раньше проверки жили в нескольких местах —
своя в analog engine, своя в расчёте форвардных доходностей. Из-за этого
баг с датой за границей datetime64[ns] сидел в одной копии и не был
виден по другой: механизм формально был, а фактически на части сред не
работал. Одна реализация, один набор тестов, один способ ошибиться.

Основная идея: у каждой величины есть момент, начиная с которого она
известна. Использовать её раньше нельзя, и запрет должен быть громким —
исключение, а не тихое отбрасывание строк.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Iterable, Optional
import pandas as pd


class Confidence(str, Enum):
    """Насколько мы уверены в дате доступности."""
    OFFICIAL = "official"     # опубликованное расписание источника
    DERIVED = "derived"       # выведена по задокументированному правилу
    UNKNOWN = "unknown"       # неизвестна — использовать нельзя


class LookaheadError(RuntimeError):
    """Попытка использовать данные раньше, чем они стали доступны."""


def to_date(v) -> Optional[date]:
    """
    Приводит значение к datetime.date БЕЗ pd.to_datetime.

    pandas 2.x по умолчанию берёт datetime64[ns] с потолком 2262-04-11 и
    роняет конверсию на более поздних датах. Защита обязана работать на
    любой дате, поэтому сравниваются объекты date напрямую.
    """
    if v is None:
        return None
    if isinstance(v, float) and v != v:      # NaN
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip()[:10]
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    to_pydatetime = getattr(v, "to_pydatetime", None)
    if callable(to_pydatetime):
        try:
            return to_pydatetime().date()
        except Exception:  # noqa: BLE001
            return None
    return None


@dataclass(frozen=True)
class Availability:
    """Момент, с которого величина известна."""
    available_at: Optional[date]
    confidence: Confidence
    source: str = ""

    def is_known_at(self, as_of: date) -> bool:
        if self.confidence is Confidence.UNKNOWN or self.available_at is None:
            return False
        return self.available_at <= as_of


class DataAvailabilityGuard:
    """
    Один объект на исследование. Все проверки идут через него.

    strict=True (по умолчанию) — нарушение бросает исключение.
    strict=False — нарушения собираются в violations и доступны для
    отчёта. Тихо отбрасывать строки нельзя ни в одном режиме: молчаливая
    фильтрация и есть то, из-за чего такие ошибки живут годами.
    """

    def __init__(self, as_of: date, strict: bool = True):
        self.as_of = as_of
        self.strict = strict
        self.violations: list[str] = []

    # -- одиночная проверка ------------------------------------------

    def check(self, availability: Availability, what: str) -> bool:
        if availability.is_known_at(self.as_of):
            return True
        msg = (f"{what}: доступно с {availability.available_at} "
               f"(уверенность: {availability.confidence.value}), "
               f"а запрошено на {self.as_of}")
        self.violations.append(msg)
        if self.strict:
            raise LookaheadError(msg)
        return False

    # -- проверка таблицы --------------------------------------------

    def assert_frame_available(self, df: pd.DataFrame, what: str,
                                availability_col: str = "availability_date",
                                confidence_col: str = "availability_source") -> None:
        if availability_col not in df.columns or df.empty:
            return
        dates = df[availability_col].map(to_date)
        future = dates.map(lambda d: d is not None and d > self.as_of)
        unknown = dates.isna()

        if future.any():
            n = int(future.sum())
            sample = [str(d) for d in dates[future].head(3)]
            msg = (f"{what}: {n} строк с датой доступности позже {self.as_of} "
                   f"(например {sample}). Отфильтруйте их явно — сам guard "
                   f"молча этого не делает.")
            self.violations.append(msg)
            if self.strict:
                raise LookaheadError(msg)

        if unknown.any():
            n = int(unknown.sum())
            msg = f"{what}: {n} строк без даты доступности — использовать нельзя."
            self.violations.append(msg)
            if self.strict:
                raise LookaheadError(msg)

    def filter_available(self, df: pd.DataFrame,
                          availability_col: str = "availability_date") -> pd.DataFrame:
        """
        Явная фильтрация. В отличие от assert_* здесь отбрасывание —
        осознанное действие вызывающего кода, и оно видно в тексте.
        """
        if availability_col not in df.columns or df.empty:
            return df
        dates = df[availability_col].map(to_date)
        keep = dates.map(lambda d: d is not None and d <= self.as_of)
        return df[keep]

    # -- фичи ---------------------------------------------------------

    def assert_features_are_not_outcomes(self, feature_names: Iterable[str],
                                          forbidden_prefixes: tuple = ("fwd_return_",)) -> None:
        """
        Форвардные доходности нельзя использовать как признаки: это утечка
        результата в условие. Формально даты не нарушены, но это тот же
        самый вид ошибки, только тоньше.
        """
        bad = [f for f in feature_names if str(f).startswith(forbidden_prefixes)]
        if bad:
            msg = (f"Признаки содержат будущий результат: {bad}. "
                   f"Совпадение по собственной доходности — скрытое заглядывание.")
            self.violations.append(msg)
            if self.strict:
                raise LookaheadError(msg)

    def report(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "strict": self.strict,
            "violations": list(self.violations),
            "clean": not self.violations,
        }
