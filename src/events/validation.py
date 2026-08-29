"""
src/events/validation.py

Проверка на истории: что предшествовало крупным движениям.

ДВЕ ОШИБКИ, ОТ КОТОРЫХ ЗАЩИЩАЕТСЯ ЭТОТ МОДУЛЬ

1. Фиксированный порог в процентах.
   «Движение 5%» для евро и для золота — это совершенно разные события.
   Евро почти никогда не ходит 5% за 8 недель, поэтому такой порог даёт
   ноль случаев и бессмысленную статистику. Здесь порог задаётся
   ПЕРЦЕНТИЛЕМ СОБСТВЕННОГО распределения инструмента: «крупное» — это
   верхние 20% его же движений за всю историю. Порог автоматически
   получается свой для каждого рынка, и он показывается в пунктах, чтобы
   было видно, о каком масштабе речь.

2. Уровень вместо события.
   «Фонды у нижней границы» — это состояние. Оно тянется месяцами и
   ничего не запускает. Триггером может быть только ИЗМЕНЕНИЕ: резкий
   поток, перелом позиции через ноль, схлопывание расхождения. Поэтому
   признаки здесь — события, а не уровни.

Кроме прямой проверки «признак → движение» есть обратная: взять сами
крупные движения и посмотреть, что происходило в отчётах за недели ДО
них. Именно этот вопрос обычно и задают.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd


@dataclass
class EventDefinition:
    key: str
    name: str
    description: str
    quantile: float        # верхние (1-quantile) движений считаем крупными
    horizon_weeks: int
    direction: str         # "up" | "down"


EVENT_DEFS: list[EventDefinition] = [
    EventDefinition("big_up_8w", "Крупный рост за 8 недель",
                     "Движение вверх из верхних 20% всех восьминедельных движений этого инструмента.",
                     0.80, 8, "up"),
    EventDefinition("big_down_8w", "Крупное падение за 8 недель",
                     "Движение вниз из верхних 20% всех восьминедельных падений этого инструмента.",
                     0.80, 8, "down"),
    EventDefinition("huge_up_12w", "Очень крупный рост за 12 недель",
                     "Верхние 10% двенадцатинедельных движений вверх.",
                     0.90, 12, "up"),
    EventDefinition("huge_down_12w", "Очень крупное падение за 12 недель",
                     "Верхние 10% двенадцатинедельных движений вниз.",
                     0.90, 12, "down"),
    EventDefinition("big_up_4w", "Крупный рост за 4 недели",
                     "Верхние 20% четырёхнедельных движений вверх.",
                     0.80, 4, "up"),
    EventDefinition("big_down_4w", "Крупное падение за 4 недели",
                     "Верхние 20% четырёхнедельных движений вниз.",
                     0.80, 4, "down"),
]


@dataclass
class Condition:
    key: str
    name: str
    description: str


CONDITIONS: list[Condition] = [
    Condition("flow_spike_up", "Резкий приток в лонг",
              "Недельный прирост чистой позиции быстрых денег вошёл в верхние 15% "
              "всех недельных изменений этого инструмента. Не уровень, а всплеск потока."),
    Condition("flow_spike_down", "Резкий сброс позиции",
              "Недельное сокращение позиции вошло в верхние 15% по величине."),
    Condition("net_flip_up", "Перелом позиции в лонг",
              "Чистая позиция быстрых денег перешла через ноль снизу вверх: из шорта в лонг."),
    Condition("net_flip_down", "Перелом позиции в шорт",
              "Чистая позиция перешла через ноль сверху вниз: из лонга в шорт."),
    Condition("turn_from_low", "Разворот от нижней границы",
              "Позиция была в нижних 20% диапазона и начала расти две недели подряд. "
              "Не сам экстремум, а выход из него."),
    Condition("turn_from_high", "Разворот от верхней границы",
              "Позиция была в верхних 20% диапазона и начала падать две недели подряд."),
    Condition("short_squeeze", "Выбивание шортов",
              "Позиция выросла заметно, но лонг почти не менялся: растёт за счёт закрытия "
              "шортов, а не притока покупателей."),
    Condition("divergence_closing", "Схлопывание расхождения",
              "Быстрые и медленные деньги месяц шли врозь, а на этой неделе пошли в одну сторону. "
              "Спор между группами разрешился."),
    Condition("oi_surge", "Всплеск открытого интереса",
              "Открытый интерес вырос в верхние 15% своих недельных приростов — на рынок "
              "заходят новые деньги."),
]


def _forward_move(price: pd.Series, horizon: int, direction: str) -> pd.Series:
    """Максимальное движение в нужную сторону за horizon недель вперёд, в долях."""
    vals = price.to_numpy(dtype=float)
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(n):
        end = min(i + horizon + 1, n)
        if end - i < 2 or np.isnan(vals[i]) or vals[i] == 0:
            continue
        w = vals[i + 1:end]
        w = w[~np.isnan(w)]
        if not len(w):
            continue
        out[i] = (w.max() / vals[i] - 1.0) if direction == "up" else (1.0 - w.min() / vals[i])
    return pd.Series(out, index=price.index)


def event_threshold(states: pd.DataFrame, ev: EventDefinition,
                     price_col: str = "price_close") -> Optional[float]:
    """Порог «крупного» движения для этого инструмента, в долях цены."""
    if price_col not in states.columns:
        return None
    moves = _forward_move(states[price_col], ev.horizon_weeks, ev.direction).dropna()
    if len(moves) < 50:
        return None
    return float(moves.quantile(ev.quantile))


def detect_events(states: pd.DataFrame, ev: EventDefinition,
                   price_col: str = "price_close") -> tuple[pd.Series, Optional[float]]:
    thr = event_threshold(states, ev, price_col)
    if thr is None:
        return pd.Series([np.nan] * len(states), index=states.index), None
    moves = _forward_move(states[price_col], ev.horizon_weeks, ev.direction)
    return moves.ge(thr).where(moves.notna(), other=np.nan), thr


def _top_quantile_flag(series: pd.Series, q: float, negative: bool = False) -> pd.Series:
    s = -series if negative else series
    valid = s.dropna()
    if len(valid) < 50:
        return pd.Series([np.nan] * len(series), index=series.index)
    thr = valid.quantile(q)
    return s.ge(thr).where(s.notna(), other=np.nan)


def evaluate_condition(states: pd.DataFrame, cond: Condition, spec: str, slow: str) -> pd.Series:
    nan = pd.Series([np.nan] * len(states), index=states.index)
    g = lambda c: states[c] if c in states.columns else nan

    net = g(f"{spec}_net")
    chg1 = g(f"{spec}_chg_1w")
    pct = g(f"{spec}_pct_52w")
    up_s = g(f"{spec}_streak_up_weeks")
    dn_s = g(f"{spec}_streak_down_weeks")

    if cond.key == "flow_spike_up":
        return _top_quantile_flag(chg1, 0.85)
    if cond.key == "flow_spike_down":
        return _top_quantile_flag(chg1, 0.85, negative=True)
    if cond.key == "net_flip_up":
        return ((net > 0) & (net.shift(1) <= 0)).where(net.notna() & net.shift(1).notna(), other=np.nan)
    if cond.key == "net_flip_down":
        return ((net < 0) & (net.shift(1) >= 0)).where(net.notna() & net.shift(1).notna(), other=np.nan)
    if cond.key == "turn_from_low":
        return ((pct <= 20) & (up_s >= 2)).where(pct.notna(), other=np.nan)
    if cond.key == "turn_from_high":
        return ((pct >= 80) & (dn_s >= 2)).where(pct.notna(), other=np.nan)
    if cond.key == "short_squeeze":
        lchg = g(f"{spec}_long_chg_1w")
        return ((chg1 > 0) & (lchg.abs() < chg1.abs() / 3)).where(chg1.notna() & lchg.notna(), other=np.nan)
    if cond.key == "divergence_closing":
        a4, b4 = g(f"{spec}_chg_4w"), g(f"{slow}_chg_4w")
        a1, b1 = chg1, g(f"{slow}_chg_1w")
        was_apart = (a4 * b4) < 0
        now_together = (a1 * b1) > 0
        return (was_apart & now_together).where(a4.notna() & b4.notna() & a1.notna() & b1.notna(), other=np.nan)
    if cond.key == "oi_surge":
        return _top_quantile_flag(g(f"{spec}_oi_chg_1w"), 0.85)
    return nan


MIN_OCCURRENCES = 15


def validate(states: pd.DataFrame, cond: Condition, ev: EventDefinition,
             spec: str, slow: str, pip: float = 0.0001, unit: str = "пп",
             date_col: str = "report_date") -> dict:
    happened, thr = detect_events(states, ev)
    holds = evaluate_condition(states, cond, spec, slow)

    usable = happened.notna() & holds.notna()
    h = happened[usable].astype(bool)
    c_ = holds[usable].astype(bool)

    a = int((c_ & h).sum()); b = int((c_ & ~h).sum())
    cc = int((~c_ & h).sum()); d = int((~c_ & ~h).sum())
    n_cond, total = a + b, a + b + cc + d

    rate_with = a / n_cond if n_cond else None
    rate_without = cc / (cc + d) if (cc + d) else None
    base = (a + cc) / total if total else None
    lift = (rate_with - base) * 100 if (rate_with is not None and base is not None) else None

    # Порог в пунктах — чтобы было видно, о каком масштабе речь
    thr_pts = None
    if thr is not None and price_ref(states) is not None:
        thr_pts = thr * price_ref(states) / pip

    if n_cond < MIN_OCCURRENCES:
        verdict = (f"Признак встречался {n_cond} раз — мало для вывода. "
                   f"Ни подтвердить, ни опровергнуть нельзя.")
    elif lift is None:
        verdict = "Недостаточно данных."
    elif abs(lift) < 5:
        verdict = (f"Разница с обычной вероятностью {lift:+.1f} п.п. — шум. "
                   f"После этого признака движение случалось примерно так же часто, как всегда.")
    elif lift > 0:
        verdict = (f"После признака движение случалось в {rate_with*100:.0f}% случаев "
                   f"против обычных {base*100:.0f}%. Перевес {lift:+.1f} п.п. "
                   f"Но в {b} случаях признак был, а движения не последовало.")
    else:
        verdict = (f"После признака движение случалось РЕЖЕ обычного: {rate_with*100:.0f}% "
                   f"против {base*100:.0f}% ({lift:+.1f} п.п.).")

    dates = states.loc[usable & holds.fillna(False).astype(bool), date_col].astype(str).tolist()
    return {
        "cond_key": cond.key, "cond": cond.name, "cond_desc": cond.description,
        "ev_key": ev.key, "ev": ev.name, "ev_desc": ev.description,
        "a": a, "b": b, "c": cc, "d": d,
        "rate_with": rate_with, "rate_without": rate_without,
        "base_rate": base, "lift_pp": lift, "n": n_cond,
        "threshold_pts": None if thr_pts is None else round(thr_pts),
        "threshold_pct": None if thr is None else thr,
        "unit": unit, "verdict": verdict, "dates": dates[-40:],
    }


def price_ref(states: pd.DataFrame) -> Optional[float]:
    if "price_close" not in states.columns:
        return None
    s = states["price_close"].dropna()
    return float(s.median()) if len(s) else None


def validate_all(states, spec, slow, pip=0.0001, unit="пп") -> list[dict]:
    return [validate(states, c, e, spec, slow, pip, unit) for c in CONDITIONS for e in EVENT_DEFS]


# ═════════════════════════════════════════════════════════════════════
# ОБРАТНЫЙ ВЗГЛЯД: от движения — назад к отчётам
# ═════════════════════════════════════════════════════════════════════
# Прямая проверка отвечает «что бывает после признака». Здесь обратный
# вопрос, который обычно и задают: берём сами крупные движения и смотрим,
# что творилось в отчётах за недели ДО них.
#
# Ключевая деталь, без которой этот взгляд обманывает: мало увидеть, что
# перед движениями фонды набирали позицию. Надо сравнить с тем, что они
# делали перед ОБЫЧНЫМИ неделями. Если одно и то же — предвестника нет,
# просто фонды всегда что-то набирают. Поэтому каждая цифра идёт парой:
# «перед движениями» и «в среднем всегда».

def precursor_profile(states: pd.DataFrame, ev: EventDefinition, spec: str, slow: str,
                       weeks_before: int = 4, top_n: int = 25,
                       date_col: str = "report_date") -> dict:
    happened, thr = detect_events(states, ev)
    if thr is None:
        return {"available": False, "reason": "нет ценового ряда"}

    moves = _forward_move(states["price_close"], ev.horizon_weeks, ev.direction)
    idx = moves.dropna().sort_values(ascending=False).head(top_n).index
    if len(idx) < 5:
        return {"available": False, "reason": "мало движений в истории"}

    metrics = [
        (f"{spec}_chg_1w", "Поток быстрых денег за неделю", "n"),
        (f"{spec}_chg_4w", "Поток быстрых денег за месяц", "n"),
        (f"{spec}_pct_52w", "Перцентиль быстрых денег", "p"),
        (f"{slow}_chg_4w", "Поток медленных денег за месяц", "n"),
        (f"{spec}_oi_chg_4w", "Изменение открытого интереса за месяц", "n"),
    ]

    rows = []
    for col, label, kind in metrics:
        if col not in states.columns:
            continue
        before = []
        for i in idx:
            pos = states.index.get_loc(i)
            lo = max(0, pos - weeks_before + 1)
            window = states[col].iloc[lo:pos + 1].dropna()
            if len(window):
                before.append(window.mean())
        overall = states[col].dropna()
        if not before or not len(overall):
            continue
        rows.append({
            "label": label, "kind": kind,
            "before": float(np.mean(before)),
            "always": float(overall.mean()),
            "diff": float(np.mean(before) - overall.mean()),
        })

    # Какие признаки чаще выполнялись перед движениями, чем обычно
    cond_rows = []
    for cond in CONDITIONS:
        flags = evaluate_condition(states, cond, spec, slow)
        if flags.isna().all():
            continue
        hits = 0
        for i in idx:
            pos = states.index.get_loc(i)
            lo = max(0, pos - weeks_before + 1)
            w = flags.iloc[lo:pos + 1].dropna()
            if len(w) and bool(w.any()):
                hits += 1
        share_before = hits / len(idx)
        base_share = float(flags.dropna().astype(bool).mean())
        cond_rows.append({
            "cond": cond.name, "cond_key": cond.key,
            "share_before": share_before, "base_share": base_share,
            "diff_pp": (share_before - base_share) * 100,
        })
    cond_rows.sort(key=lambda r: -abs(r["diff_pp"]))

    return {
        "available": True,
        "event": ev.name, "event_desc": ev.description,
        "n_moves": len(idx), "weeks_before": weeks_before,
        "threshold_pct": thr,
        "metrics": rows,
        "conditions": cond_rows,
        "dates": states.loc[idx, date_col].astype(str).sort_values().tolist(),
    }


def precursors_all(states, spec, slow) -> list[dict]:
    out = []
    for ev in EVENT_DEFS:
        p = precursor_profile(states, ev, spec, slow)
        if p.get("available"):
            p["ev_key"] = ev.key
            out.append(p)
    return out
