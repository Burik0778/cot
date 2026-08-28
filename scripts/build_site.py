"""
scripts/build_site.py

Прогоняет движок по всем загруженным рынкам и запекает результат в один
самодостаточный HTML-файл: site/index.html.

    python scripts/build_site.py
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from config.markets import (
    market, all_codes, spec_key, slow_key, other_side_key, slow_is_contrarian,
    PARTICIPANTS_BY_REPORT, PARTICIPANT_RU, PARTICIPANT_ROLE_RU, SECTORS_RU,
)
from src.data.db import Database
from src.pipeline import expand_features_json
from src.analogs.similarity import fit, find_analogs
from src.analogs.baserate import compare_to_base_rate
from src.ai.analysis_ru import AnalysisContext, ParticipantSnapshot, AnalogCase, build_full_analysis

REGIME_RU = {
    "Bullish Reversal": "Разворот вверх", "Bearish Reversal": "Разворот вниз",
    "Extreme Long": "Экстремальный лонг", "Extreme Short": "Экстремальный шорт",
    "Accumulation": "Накопление", "Distribution": "Распределение",
    "Bullish Positioning": "Позиционирование вверх",
    "Bearish Positioning": "Позиционирование вниз",
    "Neutral": "Нейтрально", "Unclassified": "Не определено",
}

HORIZONS = [4, 8, 12]


def clean(v):
    """numpy-типы (bool_, int64, float64) не сериализуются в JSON напрямую —
    приводим к чистому Python. NaN превращаем в None: 'nan%' в интерфейсе
    уже однажды всплывало."""
    if v is None:
        return None
    if isinstance(v, (bool,)) or type(v).__name__ in ("bool_", "bool8"):
        return bool(v)
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return str(v)


def signal_badge(pct52, streak_up, streak_down, chg4):
    """Короткий бейдж состояния для скринера — по тем же порогам, что и режимы."""
    p = pct52 if pct52 is not None else 50
    up = streak_up or 0
    down = streak_down or 0
    if p <= 5 or p >= 95:
        return ("Экстремум", "extreme")
    if p <= 10 and up >= 2 and (chg4 or 0) > 0:
        return ("Разворот?", "reversal")
    if p >= 90 and down >= 2 and (chg4 or 0) < 0:
        return ("Разворот?", "reversal")
    if p <= 20 or p >= 80:
        return ("Переполнено", "crowded")
    if up >= 4:
        return ("Накопление", "accum")
    if down >= 4:
        return ("Распределение", "distrib")
    return ("—", "none")



def build_table(states, participants):
    """
    Таблица в духе референса: по каждой группе — изменение лонга и шорта,
    Net/OI в процентах, изменение нетто и сама чистая позиция.
    Свежие отчёты сверху.
    """
    rows = []
    for _, r in states.tail(80).iloc[::-1].iterrows():
        row = {"d": str(r["report_date"])}
        for k in participants:
            row[f"{k}_lc"] = clean(r.get(f"{k}_long_chg_1w"))
            row[f"{k}_sc"] = clean(r.get(f"{k}_short_chg_1w"))
            row[f"{k}_oi"] = clean(r.get(f"{k}_net_oi"))
            row[f"{k}_nc"] = clean(r.get(f"{k}_chg_1w"))
            row[f"{k}_np"] = clean(r.get(f"{k}_net"))
        rows.append(row)
    return rows


def build_table_stats(states, participants):
    """Строки MAX / MIN / 5Y MAX / 5Y MIN / среднее за 13 недель — как в
    референсе. Считаются по тем же колонкам, что и сама таблица."""
    out = {}
    tail5y = states.tail(261)
    tail13 = states.tail(13)
    for label, frame, fn in [
        ("MAX", states, "max"), ("MIN", states, "min"),
        ("MAX5Y", tail5y, "max"), ("MIN5Y", tail5y, "min"),
        ("AVG13W", tail13, "mean"),
    ]:
        row = {}
        for k in participants:
            for suffix, col in [("lc", f"{k}_long_chg_1w"), ("sc", f"{k}_short_chg_1w"),
                                 ("oi", f"{k}_net_oi"), ("nc", f"{k}_chg_1w"), ("np", f"{k}_net")]:
                if col in frame.columns:
                    series = frame[col].dropna()
                    row[f"{k}_{suffix}"] = clean(getattr(series, fn)()) if len(series) else None
                else:
                    row[f"{k}_{suffix}"] = None
        out[label] = row
    return out


def snap(row, key):
    return ParticipantSnapshot(
        key=key, net=clean(row.get(f"{key}_net")), net_oi=clean(row.get(f"{key}_net_oi")),
        pct_52w=clean(row.get(f"{key}_pct_52w")), pct_156w=clean(row.get(f"{key}_pct_156w")),
        chg_4w=clean(row.get(f"{key}_chg_4w")),
        streak_up=clean(row.get(f"{key}_streak_up_weeks")),
        streak_down=clean(row.get(f"{key}_streak_down_weeks")),
    )


def analyze(states, code):
    m = market(code)
    sk, lk, ok = spec_key(code), slow_key(code), other_side_key(code)
    participants = PARTICIPANTS_BY_REPORT[m.report]

    feats = [f for f in settings.DEFAULT_ANALOG_FEATURES if f in states.columns]
    usable = states.dropna(subset=feats).reset_index(drop=True) if feats else states
    # bool(...) обязателен: выражение с pandas/numpy возвращает np.bool_,
    # который не сериализуется в JSON.
    has_analogs = bool(len(usable) >= 30 and "fwd_return_8w" in usable.columns
                       and usable["fwd_return_8w"].notna().sum() >= 20)

    current = states.iloc[-1]
    analog_cases, horizon_stats, analog_pcts, analog_details = [], {}, [], []

    if has_analogs:
        cur = usable.iloc[-1]
        fitted = fit(usable.iloc[:-1], settings.DEFAULT_ANALOG_FEATURES)
        found = find_analogs(fitted, cur, as_of_date=cur["availability_date"],
                              max_analogs=settings.DEFAULT_MAX_ANALOGS)
        rows = usable.loc[[a.index for a in found]]
        analog_pcts = [clean(usable.loc[a.index].get(f"{sk}_pct_52w")) for a in found]
        for h in HORIZONS:
            col = f"fwd_return_{h}w"
            if col in usable.columns:
                c = compare_to_base_rate(rows[col], usable, h, col)
                horizon_stats[h] = {
                    "n": c.analog_rate.n, "win_rate": clean(c.analog_rate.win_rate),
                    "median_return": clean(c.analog_rate.median_return),
                    "base_rate": clean(c.base_rate.win_rate), "edge_pp": clean(c.win_rate_diff_pp),
                    "sample_quality": c.analog_rate.sample_quality,
                }
        analog_cases = [
            AnalogCase(date=str(usable.loc[a.index]["report_date"]), similarity=a.similarity_score,
                       forward_returns={h: clean(usable.loc[a.index].get(f"fwd_return_{h}w")) for h in HORIZONS})
            for a in found[:14]
        ]
        # Полный снимок состояния на дату каждого аналога — чтобы карточку
        # можно было раскрыть и увидеть, ЧТО именно тогда было похожего,
        # а не только результат.
        analog_details = []
        for a in found[:14]:
            r = usable.loc[a.index]
            analog_details.append({
                "date": str(r["report_date"]),
                "similarity": round(a.similarity_score, 1),
                "distance": round(a.distance, 3),
                "regime": REGIME_RU.get(r.get("regime"), r.get("regime")),
                "price": clean(r.get("price_close")),
                "price_chg_4w": clean(r.get("price_chg_4w")),
                "price_chg_8w": clean(r.get("price_chg_8w")),
                "participants": [
                    {"key": k, "label": PARTICIPANT_RU[k],
                     "net": clean(r.get(f"{k}_net")), "net_oi": clean(r.get(f"{k}_net_oi")),
                     "pct_52w": clean(r.get(f"{k}_pct_52w")), "z_52w": clean(r.get(f"{k}_z_52w")),
                     "chg_4w": clean(r.get(f"{k}_chg_4w"))}
                    for k in participants
                ],
                "returns": {str(h): clean(r.get(f"fwd_return_{h}w")) for h in HORIZONS},
                "feature_match": [
                    {"f": f, "now": clean(cur.get(f)), "then": clean(r.get(f))}
                    for f in settings.DEFAULT_ANALOG_FEATURES if f in usable.columns
                ],
            })

    ctx = AnalysisContext(
        currency=code, pair_symbol=m.price_symbol or code,
        regime=REGIME_RU.get(current.get("regime"), current.get("regime")),
        participants={k: snap(current, k) for k in participants},
        analogs=analog_cases, horizon_stats=horizon_stats,
        spec_key=sk, slow_key=lk, slow_is_hedger=slow_is_contrarian(code),
        spec_label=PARTICIPANT_RU[sk], slow_label=PARTICIPANT_RU[lk],
        price_chg_4w=clean(current.get("price_chg_4w")),
        price_chg_8w=clean(current.get("price_chg_8w")),
        divergences=json.loads(current["divergence_flags"]) if isinstance(current.get("divergence_flags"), str) else [],
    )

    sections = {str(h): build_full_analysis(ctx, h) for h in HORIZONS}
    spec = ctx.participants[sk]
    badge, badge_kind = signal_badge(spec.pct_52w, spec.streak_up, spec.streak_down, spec.chg_4w)
    hist = states.tail(261)

    return {
        "code": code, "name": m.name, "sector": m.sector, "sector_ru": SECTORS_RU[m.sector],
        "report": m.report, "symbol": m.price_symbol or code,
        "report_date": str(current["report_date"]), "published": str(current["availability_date"]),
        "regime": ctx.regime, "badge": badge, "badge_kind": badge_kind,
        "has_price": bool(m.fred_series), "has_analogs": has_analogs,
        "spec_key": sk, "slow_key": lk, "other_key": ok,
        "price": clean(current.get("price_close")),
        "price_chg_4w": clean(current.get("price_chg_4w")),
        "price_chg_8w": clean(current.get("price_chg_8w")),
        "open_interest": clean(current.get(f"{sk}_open_interest")) or clean(current.get("open_interest")),
        "participants": [
            {"key": k, "label": PARTICIPANT_RU[k], "role": PARTICIPANT_ROLE_RU[k],
             "net": clean(current.get(f"{k}_net")), "net_oi": clean(current.get(f"{k}_net_oi")),
             "long": clean(current.get(f"{k}_long")), "short": clean(current.get(f"{k}_short")),
             "pct_52w": clean(current.get(f"{k}_pct_52w")), "pct_156w": clean(current.get(f"{k}_pct_156w")),
             "z_52w": clean(current.get(f"{k}_z_52w")),
             "chg_1w": clean(current.get(f"{k}_chg_1w")), "chg_4w": clean(current.get(f"{k}_chg_4w")),
             "chg_13w": clean(current.get(f"{k}_chg_13w")),
             "is_spec": k == sk, "is_slow": k == lk}
            for k in participants
        ],
        "analog_percentiles": analog_pcts,
        "analog_details": analog_details,
        "analogs": [{"date": a.date, "similarity": round(a.similarity, 1),
                      "returns": {str(h): clean(v) for h, v in a.forward_returns.items()}}
                     for a in analog_cases],
        "horizon_stats": {str(h): s for h, s in horizon_stats.items()},
        "sections": sections,
        "history": [
            {"d": str(r["report_date"]), "p": clean(r.get("price_close")),
             "oi": clean(r.get(f"{sk}_open_interest")),
             **{k: clean(r.get(f"{k}_net")) for k in participants},
             "spec_oi": clean(r.get(f"{sk}_net_oi")), "pct": clean(r.get(f"{sk}_pct_52w")),
             "z": clean(r.get(f"{sk}_z_52w"))}
            for _, r in hist.iterrows()
        ],
        "table": build_table(states, participants),
        "table_stats": build_table_stats(states, participants),
    }


def main():
    db = Database(settings.DB_PATH)
    raw = db.read_cot_raw()
    if raw.empty:
        print("В базе нет данных. Сначала загрузите их."); sys.exit(1)

    synth = any(s.startswith("synthetic") for s in raw["source"].unique())
    loaded = set(raw["market"].unique())
    payload = {"built": date.today().isoformat(), "synthetic": synth,
               "sectors": SECTORS_RU, "markets": []}

    for code in all_codes():
        if code not in loaded:
            continue
        states = expand_features_json(db.read_market_states(code))
        if states.empty:
            continue
        states = states.sort_values("report_date").reset_index(drop=True)
        try:
            payload["markets"].append(analyze(states, code))
            print(f"  {code}: готово")
        except Exception as e:  # noqa: BLE001 — один рынок не должен ронять всю сборку
            print(f"  {code}: ПРОПУЩЕН — {type(e).__name__}: {e}")

    if not payload["markets"]:
        print("Ни одного рынка не собралось."); sys.exit(1)

    root = Path(__file__).resolve().parents[1]
    tpl = (root / "site_template" / "index.template.html").read_text(encoding="utf-8")
    out = tpl.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False))
    (root / "site").mkdir(exist_ok=True)
    (root / "site" / "index.html").write_text(out, encoding="utf-8")
    print(f"\nСайт собран: {root / 'site' / 'index.html'}  ({len(payload['markets'])} рынков)")


if __name__ == "__main__":
    main()
