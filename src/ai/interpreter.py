"""
src/ai/interpreter.py

Плоский, объясняющий слой поверх квант-движка.

Формат вывода (по запросу пользователя):
    ФАКТ            — что показывают цифры
    ЧТО ЭТО ЗНАЧИТ  — интерпретация состояния
    ЧЕГО НЕ ЗНАЧИТ  — против чего страхуемся
    ИСТОРИЯ         — что было после похожих состояний, против базовой ставки
    ПРОТИВ          — что противоречит основному выводу

Тот же жёсткий контракт, что и в analyst.py: модуль НЕ считает статистику.
Он получает уже посчитанные значения и подставляет их в текст. Нет ни одной
ветки кода, которая порождала бы число. Всё, что он делает — выбирает
формулировку по уровню перцентиля, направлению импульса и качеству выборки.

Язык вывода — русский: это персональный инструмент пользователя.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

PARTICIPANT_RU = {
    "leveraged_funds": "Хедж-фонды",
    "asset_manager": "Управляющие активами",
    "dealer": "Дилеры (маркет-мейкеры)",
    "other_reportables": "Прочие крупные",
    "nonreportables": "Мелкие участники",
}

PARTICIPANT_ROLE_RU = {
    "leveraged_funds": "самые активные и направленные деньги на рынке: хедж-фонды и CTA. "
                       "Идут за трендом и разворачиваются резко.",
    "asset_manager": "медленные институционалы: пенсионные фонды, страховые. "
                     "Двигаются инерционно, разворачиваются долго.",
    "dealer": "маркет-мейкеры. Обычно стоят по другую сторону от спекулянтов, "
              "их позиция — во многом зеркало остальных.",
    "other_reportables": "крупные участники вне основных категорий.",
    "nonreportables": "мелкие участники — остаток после всех крупных. "
                      "Считается как разница, состав неизвестен.",
}

SAMPLE_QUALITY_RU = {
    "Good": "хорошее (50+ наблюдений)",
    "Moderate": "среднее (30-49 наблюдений)",
    "Low confidence": "низкое (20-29 наблюдений)",
    "Insufficient sample size": "недостаточное",
}

# Метки расхождений приходят из движка на английском (это имена правил).
# Здесь они переводятся и, что важнее, объясняются — иначе строка
# "Asset Managers vs Leveraged Funds" читателю ничего не говорит.
DIVERGENCE_RU = {
    "Asset Managers vs Leveraged Funds":
        "Управляющие активами и хедж-фонды движутся в разные стороны — "
        "медленные и быстрые деньги не согласны друг с другом. Пока расхождение "
        "не закрылось, направление считается спорным.",
    "Leveraged Funds vs Price":
        "Позиция хедж-фондов движется против цены — фонды набирают позицию "
        "вопреки текущему движению. Либо они рано, либо движение цены не подтверждено потоком.",
}


def translate_divergence(label: str) -> str:
    return DIVERGENCE_RU.get(label, label)


@dataclass
class InterpretationInput:
    market: str
    pair_symbol: str
    participant: str
    net: Optional[float]
    net_oi: Optional[float]
    pct_52w: Optional[float]
    pct_156w: Optional[float]
    chg_1w: Optional[float]
    chg_4w: Optional[float]
    streak_up_weeks: Optional[int]
    streak_down_weeks: Optional[int]
    horizon_weeks: Optional[int] = None
    n_analogs: Optional[int] = None
    analog_win_rate: Optional[float] = None
    base_rate: Optional[float] = None
    edge_pp: Optional[float] = None
    sample_quality: Optional[str] = None
    contradictions: list[str] = field(default_factory=list)


def _level_label(pct: Optional[float]) -> str:
    """Словесная метка уровня позиционирования по перцентилю."""
    if pct is None:
        return "неизвестно"
    if pct <= 5:
        return "экстремальный шорт"
    if pct <= 20:
        return "сильный шорт"
    if pct < 40:
        return "умеренный шорт"
    if pct <= 60:
        return "нейтрально"
    if pct < 80:
        return "умеренный лонг"
    if pct < 95:
        return "сильный лонг"
    return "экстремальный лонг"


def _is_crowded(pct: Optional[float]) -> bool:
    return pct is not None and (pct <= 20 or pct >= 80)


def _momentum_phrase(data: InterpretationInput) -> tuple[str, bool]:
    """Возвращает (описание импульса, есть_ли_разворот)."""
    up = data.streak_up_weeks or 0
    down = data.streak_down_weeks or 0
    chg4 = data.chg_4w

    if up >= 2 and (chg4 or 0) > 0:
        return f"позиция растёт {up} нед. подряд, за 4 недели прибавила", True
    if down >= 2 and (chg4 or 0) < 0:
        return f"позиция падает {down} нед. подряд, за 4 недели сократилась", True
    if chg4 is not None and chg4 > 0:
        return "за 4 недели выросла, но без устойчивой серии", False
    if chg4 is not None and chg4 < 0:
        return "за 4 недели сократилась, но без устойчивой серии", False
    return "заметного движения за 4 недели нет", False


def _fmt_pct(x, digits=1):
    return "н/д" if x is None else f"{x * 100:.{digits}f}%"


def _fmt_num(x, digits=0):
    return "н/д" if x is None else f"{x:,.{digits}f}".replace(",", " ")


def _fmt_pctile(x):
    return "н/д" if x is None else f"{x:.0f}-й"


def interpret(data: InterpretationInput) -> str:
    name = PARTICIPANT_RU.get(data.participant, data.participant)
    level = _level_label(data.pct_52w)
    crowded = _is_crowded(data.pct_52w)
    momentum_text, is_turning = _momentum_phrase(data)
    direction_long = (data.net_oi or 0) > 0

    L = []

    # --- ФАКТ ---
    L.append("ФАКТ")
    L.append(f"{name} по {data.market}: чистая позиция {_fmt_num(data.net)} контрактов "
             f"({_fmt_pct(data.net_oi)} от открытого интереса).")
    L.append(f"Это {_fmt_pctile(data.pct_52w)} перцентиль за год"
             + (f" и {_fmt_pctile(data.pct_156w)} за 3 года." if data.pct_156w is not None else "."))
    L.append(f"Динамика: {momentum_text}.")
    L.append("")

    # --- ЧТО ЭТО ЗНАЧИТ ---
    L.append("ЧТО ЭТО ЗНАЧИТ")
    L.append(f"{name} — {PARTICIPANT_ROLE_RU.get(data.participant, '')}")
    if crowded and not direction_long:
        L.append(f"Уровень: {level}. Позиция переполнена вниз — те, кто хотел продать, "
                 f"в основном уже продали. Топливо для дальнейшего падения ограничено, "
                 f"а риск шорт-сквиза повышен.")
    elif crowded and direction_long:
        L.append(f"Уровень: {level}. Позиция переполнена вверх — покупка во многом уже "
                 f"состоялась. Дальнейший рост требует новых покупателей, которых мало, "
                 f"а риск резкой фиксации повышен.")
    else:
        L.append(f"Уровень: {level}. Позиционирование не в крайности — как самостоятельный "
                 f"контекст говорит мало.")

    if crowded and is_turning:
        turn_dir = "разворачиваться вверх" if (data.chg_4w or 0) > 0 else "разворачиваться вниз"
        L.append(f"Важнее самого уровня то, что позиция начала {turn_dir}. Для среднесрочного "
                 f"горизонта именно смена направления с экстремума статистически осмысленнее, "
                 f"чем сам факт экстремума.")
    L.append("")

    # --- ЧЕГО ЭТО НЕ ЗНАЧИТ ---
    L.append("ЧЕГО ЭТО НЕ ЗНАЧИТ")
    if crowded:
        L.append("Не значит, что разворот случится на следующей неделе. Экстремум может "
                 "держаться месяцами и становиться ещё экстремальнее.")
    L.append("Не значит, что это сигнал на вход. Позиционирование — это состояние рынка, "
             "а не точка входа и не тайминг.")
    L.append("Данные отражают позиции на вторник и публикуются в пятницу — к моменту "
             "просмотра им от 3 до 10 дней.")
    L.append("")

    # --- ИСТОРИЯ ---
    L.append("ИСТОРИЯ")
    if data.n_analogs is None or data.horizon_weeks is None:
        L.append("Исторические аналоги для этого состояния не рассчитывались.")
    elif data.sample_quality == "Insufficient sample size":
        L.append(f"Похожих ситуаций в истории нашлось всего {data.n_analogs}. "
                 f"Этого мало для любого вывода — статистика не показывается.")
    else:
        L.append(f"Похожих состояний в истории: {data.n_analogs}. "
                 f"Через {data.horizon_weeks} нед. после них цена валюты была выше, "
                 f"чем в момент наблюдения, в {_fmt_pct(data.analog_win_rate, 0)} случаев.")
        L.append(f"Обычная вероятность (без всяких условий): {_fmt_pct(data.base_rate, 0)}.")
        if data.edge_pp is not None:
            if abs(data.edge_pp) < 5:
                L.append(f"Перевес: {data.edge_pp:+.1f} п.п. — это в пределах шума. "
                         f"Практически говоря, ситуация ничем не отличается от обычной.")
            else:
                L.append(f"Перевес над обычной вероятностью: {data.edge_pp:+.1f} п.п. "
                         f"Качество выборки: "
                         f"{SAMPLE_QUALITY_RU.get(data.sample_quality, data.sample_quality)}.")
    L.append("")

    # --- ПРОТИВ ---
    L.append("ПРОТИВ ЭТОГО ВЫВОДА")
    for c in data.contradictions:
        L.append(f"- {translate_divergence(c)}")
    L.append("- Наблюдения перекрываются: недельные срезы с горизонтом в несколько недель "
             "делят между собой почти всю историю цены. Реально независимых случаев "
             "меньше, чем N, а значит любая «значимость» здесь завышена.")
    if crowded:
        L.append("- Экстремум позиционирования сам по себе исторически плохо работает как "
                 "тайминг. Он полезен как фон, а не как триггер.")

    return "\n".join(L)


def interpret_market_summary(pair_symbol: str, regime: str, lf_text: str, am_text: str) -> str:
    """Короткая шапка над подробными разборами по участникам."""
    return (f"{pair_symbol} — режим по позиционированию: {regime}\n\n"
            f"Ниже разбор по двум ключевым группам. Хедж-фонды показывают, куда "
            f"направлены быстрые спекулятивные деньги; управляющие активами — куда "
            f"медленно смещается инерционный капитал. Расхождение между ними обычно "
            f"информативнее, чем каждая группа по отдельности.\n\n"
            f"{lf_text}\n\n{'-' * 60}\n\n{am_text}")
