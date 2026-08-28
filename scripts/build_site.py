"""
scripts/build_site.py

Собирает готовый сайт: прогоняет квант-движок по всем загруженным
валютам и запекает результат в один самодостаточный HTML-файл.

    python scripts/build_site.py

На выходе: site/index.html — открывается двойным кликом, без сервера,
без интернета, без Python. Внутри уже посчитанные цифры; браузер только
рисует.
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from src.data.db import Database
from src.pipeline import expand_features_json
from src.analogs.similarity import fit, find_analogs
from src.analogs.baserate import compare_to_base_rate
from src.ai.analysis_ru import (
    AnalysisContext, ParticipantSnapshot, AnalogCase, build_full_analysis,
)

CURRENCY_NAMES = {
    "EUR": "Евро", "GBP": "Фунт стерлингов", "JPY": "Японская иена",
    "AUD": "Австралийский доллар", "CAD": "Канадский доллар",
    "CHF": "Швейцарский франк", "NZD": "Новозеландский доллар",
    "MXN": "Мексиканское песо",
}

REGIME_RU = {
    "Bullish Reversal": "Разворот вверх", "Bearish Reversal": "Разворот вниз",
    "Extreme Long": "Экстремальный лонг", "Extreme Short": "Экстремальный шорт",
    "Accumulation": "Накопление", "Distribution": "Распределение",
    "Bullish Positioning": "Позиционирование вверх",
    "Bearish Positioning": "Позиционирование вниз",
    "Neutral": "Нейтрально", "Unclassified": "Не определено",
}

PARTICIPANTS_SHOWN = [
    ("leveraged_funds", "Хедж-фонды", "быстрые спекулятивные деньги"),
    ("asset_manager", "Управляющие активами", "медленный инерционный капитал"),
    ("dealer", "Дилеры", "маркет-мейкеры, обычно на другой стороне"),
]

HORIZONS = [4, 8, 12]


def _snap(row, key) -> ParticipantSnapshot:
    return ParticipantSnapshot(
        key=key, net=row.get(f"{key}_net"), net_oi=row.get(f"{key}_net_oi"),
        pct_52w=row.get(f"{key}_pct_52w"), pct_156w=row.get(f"{key}_pct_156w"),
        chg_4w=row.get(f"{key}_chg_4w"),
        streak_up=row.get(f"{key}_streak_up_weeks"),
        streak_down=row.get(f"{key}_streak_down_weeks"),
    )


def _clean(v):
    """NaN -> None, numpy -> python. JSON не умеет NaN, а 'nan%' в интерфейсе
    уже однажды всплывало (см. LIMITATIONS)."""
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return str(v)


def analyze_currency(states, currency: str) -> dict | None:
    feats = [f for f in settings.DEFAULT_ANALOG_FEATURES if f in states.columns]
    usable = states.dropna(subset=feats).reset_index(drop=True)
    if len(usable) < 30:
        return None

    current = usable.iloc[-1]
    pool = usable.iloc[:-1]
    fitted = fit(pool, settings.DEFAULT_ANALOG_FEATURES)
    found = find_analogs(fitted, current, as_of_date=current["availability_date"],
                          max_analogs=settings.DEFAULT_MAX_ANALOGS)
    analog_rows = usable.loc[[a.index for a in found]]

    horizon_stats = {}
    for h in HORIZONS:
        col = f"fwd_return_{h}w"
        if col not in usable.columns:
            continue
        cmp = compare_to_base_rate(analog_rows[col], usable, h, col)
        horizon_stats[h] = {
            "n": cmp.analog_rate.n, "win_rate": _clean(cmp.analog_rate.win_rate),
            "median_return": _clean(cmp.analog_rate.median_return),
            "base_rate": _clean(cmp.base_rate.win_rate),
            "edge_pp": _clean(cmp.win_rate_diff_pp),
            "sample_quality": cmp.analog_rate.sample_quality,
        }

    analog_cases = [
        AnalogCase(date=str(usable.loc[a.index]["report_date"]), similarity=a.similarity_score,
                   forward_returns={h: usable.loc[a.index].get(f"fwd_return_{h}w") for h in HORIZONS})
        for a in found[:14]
    ]

    ctx = AnalysisContext(
        currency=currency, pair_symbol=settings.FX_PAIRS[currency].symbol,
        regime=REGIME_RU.get(current["regime"], current["regime"]),
        participants={k: _snap(current, k) for k, _, _ in PARTICIPANTS_SHOWN},
        analogs=analog_cases, horizon_stats=horizon_stats,
        price_chg_4w=_clean(current.get("price_chg_4w")),
        price_chg_8w=_clean(current.get("price_chg_8w")),
        divergences=json.loads(current["divergence_flags"]) if isinstance(current.get("divergence_flags"), str) else [],
    )

    sections_by_horizon = {h: build_full_analysis(ctx, h) for h in HORIZONS}
    history = usable.tail(156)

    return {
        "code": currency,
        "name": CURRENCY_NAMES.get(currency, currency),
        "pair": ctx.pair_symbol,
        "report_date": str(current["report_date"]),
        "published": str(current["availability_date"]),
        "regime": ctx.regime,
        "price": _clean(current.get("price_close")),
        "price_chg_4w": _clean(current.get("price_chg_4w")),
        "price_chg_8w": _clean(current.get("price_chg_8w")),
        "participants": [
            {"key": k, "label": label, "role": role,
             "net": _clean(current.get(f"{k}_net")),
             "net_oi": _clean(current.get(f"{k}_net_oi")),
             "pct_52w": _clean(current.get(f"{k}_pct_52w")),
             "pct_156w": _clean(current.get(f"{k}_pct_156w")),
             "chg_4w": _clean(current.get(f"{k}_chg_4w"))}
            for k, label, role in PARTICIPANTS_SHOWN
        ],
        "analog_percentiles": [_clean(usable.loc[a.index].get("leveraged_funds_pct_52w")) for a in found],
        "analogs": [
            {"date": a.date, "similarity": round(a.similarity, 1),
             "returns": {str(h): _clean(v) for h, v in a.forward_returns.items()}}
            for a in analog_cases
        ],
        "horizon_stats": {str(h): s for h, s in horizon_stats.items()},
        "sections": {
            str(h): {
                "configuration_name": s["configuration_name"],
                "configuration_text": s["configuration_text"],
                "extremes": s["extremes"], "analogs": s["analogs"],
                "statistics": s["statistics"], "confirm": s["confirm"],
                "invalidate": s["invalidate"], "caveats": s["caveats"],
            } for h, s in sections_by_horizon.items()
        },
        "history": [
            {"d": str(r["report_date"]),
             "p": _clean(r.get("price_close")),
             "lf": _clean(r.get("leveraged_funds_net_oi")),
             "am": _clean(r.get("asset_manager_net_oi")),
             "pct": _clean(r.get("leveraged_funds_pct_52w"))}
            for _, r in history.iterrows()
        ],
    }


def main():
    db = Database(settings.DB_PATH)
    raw = db.read_cot_raw()
    if raw.empty:
        print("В базе нет данных. Сначала запустите START.bat или scripts/init_db.py.")
        sys.exit(1)

    is_synth = "synthetic_demo" in set(raw["source"].unique())
    available = [c for c in settings.CURRENCIES if c in set(raw["market"].unique())]

    payload = {"built": date.today().isoformat(), "synthetic": is_synth, "currencies": []}
    for c in available:
        states = expand_features_json(db.read_market_states(c))
        if states.empty:
            continue
        states = states.sort_values("report_date").reset_index(drop=True)
        rec = analyze_currency(states, c)
        if rec:
            payload["currencies"].append(rec)
            print(f"  {c}: готово ({len(rec['analogs'])} аналогов, {len(rec['history'])} недель истории)")
        else:
            print(f"  {c}: пропущено — мало истории")

    if not payload["currencies"]:
        print("Ни одной валюты с достаточной историей.")
        sys.exit(1)

    root = Path(__file__).resolve().parents[1]
    template = (root / "site_template" / "index.template.html").read_text(encoding="utf-8")
    out = template.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    (root / "site").mkdir(exist_ok=True)
    out_path = root / "site" / "index.html"
    out_path.write_text(out, encoding="utf-8")
    print(f"\nСайт собран: {out_path}")
    print("Откройте этот файл двойным кликом.")


if __name__ == "__main__":
    main()
