"""
src/ai/briefing_ru.py

Фактическая сводка по рынку.

Отличие от analysis_ru.py: тот описывает КОНФИГУРАЦИЮ (кто против кого),
а этот выдаёт ФАКТЫ — что именно произошло за неделю и за месяц, в
контрактах, с разложением на действия.

Ключевая идея, ради которой всё это считается: чистая позиция может
вырасти двумя совершенно разными способами.

    лонги выросли      → приток новых денег, покупают
    шорты сократились  → закрытие позиций, шортистов выбивает

Внешне и то и другое выглядит как «нетто вырос». Но первое — это спрос,
а второе — вынужденное закрытие, которое заканчивается, как только шорты
кончатся. По одному нетто их не различить, поэтому здесь всё раскладывается
на составляющие.

Второй слой — открытый интерес. Если позиция растёт вместе с OI, на рынок
приходят новые участники. Если растёт при падающем OI, идёт перекладывание
между существующими. Это разные вещи, и трейдеру полезнее знать какая.

Модуль НЕ вычисляет статистику: он получает уже посчитанные значения и
только формулирует. Ни одного числа не появляется из воздуха.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


def n(x) -> str:
    """Число контрактов со знаком и разделителями."""
    if x is None:
        return "н/д"
    return f"{x:+,.0f}".replace(",", " ")


def a(x) -> str:
    """Абсолютное число контрактов."""
    if x is None:
        return "н/д"
    return f"{abs(x):,.0f}".replace(",", " ")


def pc(x, d=1) -> str:
    return "н/д" if x is None else f"{x * 100:.{d}f}%"


@dataclass
class Flow:
    """Что группа сделала за период."""
    label: str
    net: Optional[float]
    net_oi: Optional[float]
    chg_1w: Optional[float]
    chg_4w: Optional[float]
    chg_13w: Optional[float]
    long_chg_1w: Optional[float]
    short_chg_1w: Optional[float]
    long_chg_4w: Optional[float]
    short_chg_4w: Optional[float]
    pct_52w: Optional[float]
    pct_156w: Optional[float]
    z_52w: Optional[float]
    streak_up: Optional[int]
    streak_down: Optional[int]
    rank_156w: Optional[float]
    is_spec: bool = False


@dataclass
class BriefingInput:
    market_name: str
    report_date: str
    flows: list[Flow]
    open_interest: Optional[float]
    oi_chg_1w: Optional[float]
    oi_chg_4w: Optional[float]
    oi_pct_52w: Optional[float]
    price: Optional[float] = None
    price_chg_1w: Optional[float] = None
    price_chg_4w: Optional[float] = None
    price_chg_8w: Optional[float] = None
    weeks_history: Optional[int] = None


def decompose(long_chg: Optional[float], short_chg: Optional[float]) -> Optional[str]:
    """
    Раскладывает изменение нетто на действие. Это самая полезная строка во
    всей сводке: она отвечает, ЧТО сделали, а не только куда сдвинулось.
    """
    if long_chg is None or short_chg is None:
        return None
    dl, ds = long_chg, short_chg
    if abs(dl) < 1 and abs(ds) < 1:
        return "без движения"

    # «Движение с двух сторон» имеет смысл только когда стороны сопоставимы.
    # Если одна больше другой в разы, это доминирование одной стороны, и
    # называть его «обеими» — потерять именно ту разницу, ради которой
    # раскладка и делается (закрытие шортов против настоящих покупок).
    BALANCED = 2.5
    both_ways = (dl > 0) != (ds > 0)
    comparable = min(abs(dl), abs(ds)) * BALANCED >= max(abs(dl), abs(ds))
    if both_ways and comparable:
        if dl > 0:
            return f"покупали и закрывали шорты (лонг {n(dl)}, шорт {n(ds)}) — движение с двух сторон"
        return f"продавали и наращивали шорты (лонг {n(dl)}, шорт {n(ds)}) — движение с двух сторон"

    if abs(dl) >= abs(ds):
        if dl > 0:
            return f"в основном набирали лонг ({n(dl)}), шорт при этом {n(ds)}"
        return f"в основном сокращали лонг ({n(dl)}), шорт при этом {n(ds)}"
    if ds > 0:
        return f"в основном наращивали шорт ({n(ds)}), лонг при этом {n(dl)}"
    return f"в основном закрывали шорт ({n(ds)}), лонг при этом {n(dl)} — это закрытие позиций, а не приток покупателей"


def oi_context(oi_chg: Optional[float], net_chg: Optional[float]) -> Optional[str]:
    """Растёт ли рынок целиком или идёт перекладывание."""
    if oi_chg is None or net_chg is None or abs(oi_chg) < 1:
        return None
    if oi_chg > 0 and net_chg > 0:
        return "открытый интерес рос вместе с позицией — на рынок приходили новые деньги"
    if oi_chg > 0 and net_chg < 0:
        return "открытый интерес рос при сокращении позиции — приходили участники с другой стороны"
    if oi_chg < 0 and net_chg > 0:
        return "открытый интерес падал при росте позиции — это закрытие противоположных позиций, а не приток"
    return "открытый интерес и позиция падали вместе — участники уходят с рынка"


def build_facts(b: BriefingInput) -> list[dict]:
    """
    Возвращает список фактических блоков. Каждый — словарь с заголовком и
    строками, чтобы интерфейс мог отрисовать их как угодно.
    """
    out: list[dict] = []

    # ── 1. Что произошло за неделю ───────────────────────────────────────
    week_lines = []
    for f in b.flows:
        if f.chg_1w is None:
            continue
        verb = "нарастили" if f.chg_1w > 0 else "сократили" if f.chg_1w < 0 else "не изменили"
        line = f"**{f.label}** {verb} чистую позицию на {a(f.chg_1w)} контрактов"
        d = decompose(f.long_chg_1w, f.short_chg_1w)
        if d:
            line += f" — {d}"
        line += f". Сейчас {n(f.net)} ({pc(f.net_oi)} открытого интереса)."
        week_lines.append(line)
    if week_lines:
        out.append({"title": f"Что произошло за неделю к {b.report_date}", "lines": week_lines})

    # ── 2. Открытый интерес ──────────────────────────────────────────────
    oi_lines = []
    if b.open_interest is not None:
        s = f"Открытый интерес {a(b.open_interest)} контрактов"
        if b.oi_chg_1w is not None:
            s += f", за неделю {n(b.oi_chg_1w)}"
        if b.oi_chg_4w is not None:
            s += f", за месяц {n(b.oi_chg_4w)}"
        if b.oi_pct_52w is not None:
            s += f". Это {b.oi_pct_52w:.0f}-й перцентиль за год — "
            s += ("рынок необычно активен" if b.oi_pct_52w >= 80
                  else "активность необычно низкая" if b.oi_pct_52w <= 20
                  else "активность в обычных пределах")
        oi_lines.append(s + ".")
        spec = next((f for f in b.flows if f.is_spec), None)
        if spec is not None:
            ctx = oi_context(b.oi_chg_1w, spec.chg_1w)
            if ctx:
                oi_lines.append(ctx[0].upper() + ctx[1:] + ".")
    if oi_lines:
        out.append({"title": "Активность на рынке", "lines": oi_lines})

    # ── 3. Месяц ─────────────────────────────────────────────────────────
    month_lines = []
    for f in b.flows:
        if f.chg_4w is None:
            continue
        verb = "прибавила" if f.chg_4w > 0 else "потеряла"
        line = f"**{f.label}**: за 4 недели позиция {verb} {a(f.chg_4w)} контрактов"
        d = decompose(f.long_chg_4w, f.short_chg_4w)
        if d:
            line += f" — {d}"
        if f.chg_13w is not None:
            line += f". За 13 недель {n(f.chg_13w)}"
        month_lines.append(line + ".")
    if month_lines:
        out.append({"title": "Что происходило за месяц и квартал", "lines": month_lines})

    # ── 4. Серии ─────────────────────────────────────────────────────────
    streak_lines = []
    for f in b.flows:
        up, down = f.streak_up or 0, f.streak_down or 0
        if up >= 2:
            streak_lines.append(f"**{f.label}** наращивают позицию {int(up)} нед. подряд без перерыва.")
        elif down >= 2:
            streak_lines.append(f"**{f.label}** сокращают позицию {int(down)} нед. подряд без перерыва.")
    if streak_lines:
        out.append({"title": "Устойчивые серии",
                    "lines": streak_lines + [
                        "Серия из нескольких недель информативнее одиночного движения: "
                        "она означает решение, а не реакцию на одну новость."]})

    # ── 5. Где это относительно истории ──────────────────────────────────
    hist_lines = []
    for f in b.flows:
        if f.pct_52w is None:
            continue
        line = f"**{f.label}**: {f.pct_52w:.0f}-й перцентиль за год"
        if f.pct_156w is not None:
            line += f", {f.pct_156w:.0f}-й за три года"
        if f.rank_156w is not None:
            line += f". За последние три года позиция была ниже текущей в {f.rank_156w:.0f} неделях из 156"
        if f.z_52w is not None:
            line += f". Отклонение от собственной нормы: {f.z_52w:+.2f} стандартных отклонения"
        hist_lines.append(line + ".")
    if hist_lines:
        out.append({"title": "Насколько это необычно", "lines": hist_lines})

    # ── 6. Цена рядом ────────────────────────────────────────────────────
    if b.price is not None:
        pl = [f"Цена {b.price:.4f}."]
        parts = []
        if b.price_chg_4w is not None:
            parts.append(f"за 4 недели {b.price_chg_4w * 100:+.1f}%")
        if b.price_chg_8w is not None:
            parts.append(f"за 8 недель {b.price_chg_8w * 100:+.1f}%")
        if parts:
            pl.append("Движение: " + ", ".join(parts) + ".")
        spec = next((f for f in b.flows if f.is_spec), None)
        if spec is not None and spec.chg_4w is not None and b.price_chg_4w is not None:
            same = (spec.chg_4w > 0) == (b.price_chg_4w > 0)
            pl.append("Позиция спекулянтов и цена за месяц двигались в одну сторону — "
                      "спекулянты идут за трендом." if same else
                      "Позиция спекулянтов и цена за месяц разошлись — спекулянты набирают "
                      "против движения цены. Либо они рано, либо движение не подтверждено потоком.")
        out.append({"title": "Цена рядом с позиционированием", "lines": pl})

    return out
