"""
src/ai/analysis_ru.py

Профессиональный разбор позиционирования на русском языке.

Отличие от interpreter.py (который остаётся для короткой справки): здесь
не пять шаблонных блоков, а связный аналитический текст, который:

  - называет КОНФИГУРАЦИЮ участников (кто против кого), а не описывает
    каждую группу изолированно;
  - ставит каждое число в контекст ("29.5% — это 82-й перцентиль, то есть
    выше, чем в 82% недель за 3 года");
  - ссылается на КОНКРЕТНЫЕ исторические даты и что было после них;
  - формулирует, что подтвердит вывод, а что его опровергнет.

Контракт тот же, что и везде в проекте: модуль НЕ вычисляет статистику.
Все числа приходят из квант-движка. Здесь только выбор формулировок.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParticipantSnapshot:
    key: str
    net: Optional[float]
    net_oi: Optional[float]
    pct_52w: Optional[float]
    pct_156w: Optional[float]
    chg_4w: Optional[float]
    streak_up: Optional[int]
    streak_down: Optional[int]


@dataclass
class AnalogCase:
    date: str
    similarity: float
    forward_returns: dict          # {horizon_weeks: return или None}


@dataclass
class AnalysisContext:
    currency: str
    pair_symbol: str
    regime: str
    participants: dict             # {key: ParticipantSnapshot}
    analogs: list[AnalogCase]
    horizon_stats: dict            # {h: {n, win_rate, base_rate, edge_pp, median_return, sample_quality}}
    # Роли участников зависят от отчёта: в TFF быстрые деньги это хедж-фонды,
    # в Disaggregated — управляемые деньги, а вторая группа там хеджеры
    # с обратной трактовкой. Значения по умолчанию соответствуют TFF.
    spec_key: str = "leveraged_funds"
    slow_key: str = "asset_manager"
    slow_is_hedger: bool = False
    spec_label: str = "Хедж-фонды"
    slow_label: str = "Управляющие активами"
    price_chg_4w: Optional[float] = None
    price_chg_8w: Optional[float] = None
    divergences: list[str] = field(default_factory=list)


# --- вспомогательные форматтеры -------------------------------------------

def pct(x, d=1):
    return "н/д" if x is None else f"{x * 100:.{d}f}%"


def signed_pct(x, d=1):
    return "н/д" if x is None else f"{x * 100:+.{d}f}%"


def num(x):
    return "н/д" if x is None else f"{x:,.0f}".replace(",", " ")


def ordinal_pctile(x):
    return "н/д" if x is None else f"{x:.0f}-й"


def _stance(p: ParticipantSnapshot) -> str:
    """Лонг / шорт / нейтрально — по знаку чистой позиции."""
    if p.net_oi is None:
        return "неизвестно"
    if p.net_oi > 0.02:
        return "лонг"
    if p.net_oi < -0.02:
        return "шорт"
    return "нейтрально"


def _extremity(pct_val: Optional[float]) -> str:
    if pct_val is None:
        return ""
    if pct_val <= 5:
        return "исторический экстремум вниз"
    if pct_val <= 20:
        return "вблизи нижней границы диапазона"
    if pct_val >= 95:
        return "исторический экстремум вверх"
    if pct_val >= 80:
        return "вблизи верхней границы диапазона"
    if 40 <= pct_val <= 60:
        return "середина диапазона"
    return "внутри обычного диапазона"


def _momentum(p: ParticipantSnapshot) -> str:
    if p.streak_up and p.streak_up >= 2:
        return f"растёт {p.streak_up} нед. подряд"
    if p.streak_down and p.streak_down >= 2:
        return f"сокращается {p.streak_down} нед. подряд"
    if p.chg_4w is None:
        return "динамика неизвестна"
    if p.chg_4w > 0:
        return "за месяц подросла"
    if p.chg_4w < 0:
        return "за месяц сократилась"
    return "без движения"


# --- определение конфигурации ---------------------------------------------

def describe_configuration(ctx: AnalysisContext) -> tuple[str, str]:
    """
    Возвращает (название конфигурации, объяснение).

    Смотрим не на каждую группу отдельно, а на то, как они стоят ДРУГ
    ПРОТИВ ДРУГА — это информативнее.

    Для товаров (Disaggregated) вторая группа — производители и торговцы,
    то есть хеджеры. Они по определению держат сторону, противоположную
    спекулянтам, поэтому их лонг не означает бычий настрой, а означает
    страховку от падения. Флаг slow_is_hedger переключает трактовку.
    """
    spec = ctx.participants.get(ctx.spec_key)
    slow = ctx.participants.get(ctx.slow_key)
    if spec is None or slow is None:
        return "Данных недостаточно", "Не хватает данных по ключевым группам участников."

    spec_st, slow_st = _stance(spec), _stance(slow)
    S, L = ctx.spec_label, ctx.slow_label

    if ctx.slow_is_hedger:
        # Товарная логика: смотрим на спекулянтов, хеджеры — зеркало.
        if spec_st == "лонг":
            return (
                f"{S} в лонге, {L.lower()} хеджируют продажи",
                f"{S} держат {pct(spec.net_oi)} открытого интереса в лонг, "
                f"{L.lower()} — {pct(slow.net_oi)}. Для товарного рынка это обычная "
                f"конструкция: спекулянты покупают, производители страхуют будущую "
                f"продажу. Важно не само наличие такой картины, а насколько далеко "
                f"она зашла: чем плотнее спекулятивный лонг, тем меньше остаётся "
                f"новых покупателей и тем резче разгрузка при развороте."
            )
        if spec_st == "шорт":
            return (
                f"{S} в шорте — редкая для товара картина",
                f"{S} держат {pct(spec.net_oi)} открытого интереса в шорт. "
                f"Спекулянты в товарах чаще стоят в лонг, поэтому чистый шорт — "
                f"состояние нечастое и обычно связано с выраженным нисходящим трендом. "
                f"{L} при этом на {pct(slow.net_oi)}."
            )
        return (
            "Спекулянты близки к нейтральному",
            f"{S} практически без чистой позиции ({pct(spec.net_oi)}). "
            f"Как самостоятельный контекст позиционирование сейчас говорит мало."
        )

    # Финансовая логика (TFF): медленные против быстрых
    if slow_st == "лонг" and spec_st == "шорт":
        return (
            "Медленные деньги в лонге, быстрые в шорте",
            f"{L} держат {pct(slow.net_oi)} открытого интереса в лонг, "
            f"{S.lower()} — {pct(abs(spec.net_oi or 0))} в шорт. Это расхождение между "
            f"инерционным капиталом и спекулятивным. {L} двигаются медленно и редко "
            f"разворачиваются резко; {S.lower()} подвижны и часто оказываются на другой "
            f"стороне краткосрочного движения. Пока расхождение сохраняется, направление "
            f"считается неразрешённым: рынок ещё не решил, чья сторона права."
        )
    if slow_st == "шорт" and spec_st == "лонг":
        return (
            "Медленные деньги в шорте, быстрые в лонге",
            f"{L} в шорте на {pct(abs(slow.net_oi or 0))} открытого интереса, "
            f"{S.lower()} в лонге на {pct(spec.net_oi)}. Спекулятивный капитал опережает "
            f"инерционный. Такая конфигурация чаще возникает на ранней стадии разворота, "
            f"когда быстрые деньги уже развернулись, а медленные ещё нет."
        )
    if slow_st == spec_st == "лонг":
        return (
            "Обе группы в лонге — консенсус вверх",
            f"И {L.lower()} ({pct(slow.net_oi)}), и {S.lower()} ({pct(spec.net_oi)}) "
            f"стоят в лонг. Согласие между медленными и быстрыми деньгами. Обратная сторона "
            f"согласия — отсутствие тех, кто ещё может купить: позиция становится "
            f"переполненной, и разгрузка при развороте идёт быстрее."
        )
    if slow_st == spec_st == "шорт":
        return (
            "Обе группы в шорте — консенсус вниз",
            f"{L} ({pct(slow.net_oi)}) и {S.lower()} ({pct(spec.net_oi)}) "
            f"стоят в шорт одновременно. Единодушие в сторону снижения. Топливо для "
            f"дальнейшего падения ограничено — продавать уже почти некому, и риск "
            f"шорт-сквиза при неожиданной новости повышен."
        )
    return (
        "Смешанная картина",
        f"{L} — {slow_st} ({pct(slow.net_oi)}), {S.lower()} — {spec_st} "
        f"({pct(spec.net_oi)}). Выраженной конфигурации нет: как самостоятельный контекст "
        f"позиционирование сейчас говорит мало."
    )


def describe_extremes(ctx: AnalysisContext) -> list[str]:
    """Что сейчас находится в крайности — по каждой значимой группе."""
    out = []
    labels = {
        ctx.spec_key: ctx.spec_label,
        ctx.slow_key: ctx.slow_label,
    }
    for key, label in labels.items():
        p = ctx.participants.get(key)
        if p is None or p.pct_52w is None:
            continue
        ex = _extremity(p.pct_52w)
        if "экстремум" in ex or "границы" in ex:
            three_yr = (f", за 3 года — {ordinal_pctile(p.pct_156w)} перцентиль"
                        if p.pct_156w is not None else "")
            out.append(
                f"**{label}:** {num(p.net)} контрактов ({pct(p.net_oi)} от открытого интереса). "
                f"{ordinal_pctile(p.pct_52w)} перцентиль за год{three_yr} — {ex}. "
                f"Позиция {_momentum(p)}."
            )
    return out


def describe_analogs(ctx: AnalysisContext, horizon: int) -> str:
    """Конкретные исторические ситуации, а не абстрактная статистика."""
    if not ctx.analogs:
        return "Исторические аналоги не рассчитаны."

    stats = ctx.horizon_stats.get(horizon, {})
    if stats.get("sample_quality") == "Insufficient sample size":
        return (f"Похожих ситуаций в истории нашлось всего {stats.get('n')}. "
                f"Это слишком мало — на такой выборке любой вывод был бы случайным, "
                f"поэтому статистика не показывается.")

    shown = []
    for a in ctx.analogs:
        r = a.forward_returns.get(horizon)
        # Пропускаем «неотработавшие» аналоги: если после той даты ещё не
        # прошло `horizon` недель, результат неизвестен (NaN), и показывать
        # его как «снизилась на nan%» — прямая дезинформация. pandas отдаёт
        # NaN, который не равен сам себе — на это и проверяем.
        if r is None or r != r:
            continue
        shown.append((a, r))
        if len(shown) >= 5:
            break

    lines = []
    for a, r in shown:
        direction = "выросла" if r > 0 else "снизилась"
        lines.append(f"- **{a.date}** (совпадение {a.similarity:.0f}) — "
                     f"через {horizon} нед. валюта {direction} на {abs(r) * 100:.1f}%")

    header = (f"Ближайшие исторические аналоги текущего состояния "
              f"(всего найдено {stats.get('n', '—')}):")
    if not lines:
        return header + "\n\nНи один из ближайших аналогов ещё не отработал этот горизонт."
    return header + "\n\n" + "\n".join(lines)


def describe_statistics(ctx: AnalysisContext, horizon: int) -> str:
    s = ctx.horizon_stats.get(horizon)
    if not s:
        return "Статистика по этому горизонту не рассчитана."
    if s.get("sample_quality") == "Insufficient sample size":
        return f"Выборка недостаточна (N={s.get('n')}) — вывод не делается."

    edge = s.get("edge_pp")
    lines = [
        f"На горизонте **{horizon} недель** после похожих состояний валюта была выше "
        f"в **{pct(s.get('win_rate'), 0)}** случаев (N={s.get('n')}).",
        f"Обычная вероятность роста на том же горизонте, без всяких условий — "
        f"**{pct(s.get('base_rate'), 0)}**.",
    ]
    if edge is None:
        lines.append("Сравнение с базовой вероятностью недоступно.")
    elif abs(edge) < 5:
        lines.append(f"Разница: **{edge:+.1f} п.п.** Это в пределах шума. Практически "
                     f"говоря, текущее состояние ничем не отличается от случайно взятой недели.")
    elif abs(edge) < 12:
        lines.append(f"Разница: **{edge:+.1f} п.п.** Умеренный перевес — заметный, но не такой, "
                     f"на который стоит опираться в одиночку.")
    else:
        lines.append(f"Разница: **{edge:+.1f} п.п.** Существенный перевес по историческим меркам.")

    median = s.get("median_return")
    if median is not None:
        lines.append(f"Медианное движение после аналогов: **{signed_pct(median, 2)}**.")
    return "\n\n".join(lines)


def describe_confirmation(ctx: AnalysisContext) -> tuple[list[str], list[str]]:
    """Что подтвердит вывод / что его опровергнет — самое практичное для трейдера."""
    lf = ctx.participants.get(ctx.spec_key)
    confirm, invalidate = [], []
    if lf is None or lf.pct_52w is None:
        return confirm, invalidate
    S, L = ctx.spec_label, ctx.slow_label

    if lf.pct_52w <= 20:
        confirm.append(f"{S} продолжают сокращать шорт две недели подряд и дольше — "
                       f"закрытие переполненной позиции обычно идёт именно так.")
        confirm.append(f"{L} не начинают сокращать лонг.")
        invalidate.append(f"{S} наращивают шорт дальше — значит экстремум ещё не экстремум, "
                          f"и позиция может стать плотнее.")
        invalidate.append(f"{L} разворачиваются в шорт — тогда расхождение "
                          f"разрешается не в пользу роста.")
    elif lf.pct_52w >= 80:
        confirm.append(f"{S} начинают сокращать лонг две недели подряд и дольше.")
        invalidate.append(f"{S} продолжают наращивать лонг — переполненность может "
                          f"усиливаться ещё долго.")
    else:
        confirm.append("Появление выраженного движения позиции в одну сторону несколько "
                       "недель подряд — сейчас его нет.")
        invalidate.append("Позиция продолжает болтаться в середине диапазона — тогда COT "
                          "просто не даёт полезного сигнала в этот период.")
    return confirm, invalidate


def build_full_analysis(ctx: AnalysisContext, horizon: int = 8) -> dict:
    """Собирает все части разбора. Возвращает словарь секций для рендера в UI."""
    config_name, config_text = describe_configuration(ctx)
    confirm, invalidate = describe_confirmation(ctx)
    return {
        "configuration_name": config_name,
        "configuration_text": config_text,
        "extremes": describe_extremes(ctx),
        "analogs": describe_analogs(ctx, horizon),
        "statistics": describe_statistics(ctx, horizon),
        "confirm": confirm,
        "invalidate": invalidate,
        "caveats": [
            "Данные отражают позиции на вторник и публикуются в пятницу — к моменту "
            "просмотра им от 3 до 10 дней. Это контекст, а не тайминг входа.",
            "Наблюдения перекрываются: недельные срезы с горизонтом в несколько недель "
            "делят почти всю историю цены. Реально независимых случаев меньше, чем N, "
            "поэтому любая «значимость» здесь завышена.",
            "Экстремум позиционирования исторически плохо работает как точка входа. "
            "Он полезен как фон для решения, принятого по другой системе.",
        ],
    }
