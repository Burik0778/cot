"""
scripts/validate_cftc.py

Построчная сверка загруженных данных с живым CFTC. Возвращает PASS или
FAIL и сохраняет снимок в data/validation/.

Зачем: до сих пор в проекте нигде не было доказательства, что цифры,
которые считает движок, совпадают с тем, что публикует CFTC. Всё
остальное — перцентили, аналоги, статистика — стоит на этом фундаменте,
и если он кривой, красивая надстройка бессмысленна.

Что делает:
  1. Тянет строку отчёта напрямую из CFTC на указанную дату.
  2. Тянет ту же строку из локальной базы.
  3. Сравнивает Long, Short, Open Interest по каждой группе участников.
  4. Пересчитывает Net = Long - Short независимо от обеих сторон.
  5. Проверяет тождество: сумма лонгов = сумма шортов = открытый интерес.
  6. Пишет снимок с исходными числами обеих сторон — чтобы результат
     можно было перепроверить руками, а не верить скрипту на слово.

Коды возврата: 0 = PASS, 1 = FAIL, 2 = не удалось получить данные.

    python scripts/validate_cftc.py --markets EUR GBP --date 2026-08-18
    python scripts/validate_cftc.py --all-fx --date 2026-08-18
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import settings
from config.markets import market, all_codes, PARTICIPANTS_BY_REPORT, PARTICIPANT_RU
from src.data.db import Database

VALIDATION_DIR = ROOT / "data" / "validation"
FX_CODES = ["EUR", "GBP", "JPY", "AUD", "CAD", "CHF", "NZD", "MXN"]


@dataclass
class FieldCheck:
    market: str
    participant: str
    field: str
    live: int | None
    local: int | None
    match: bool
    note: str = ""


@dataclass
class MarketResult:
    market: str
    report_date: str
    status: str                      # PASS | FAIL | BLOCKED
    contract_name: str | None = None
    checks: list = field(default_factory=list)
    identity_ok: bool | None = None
    message: str = ""


def fetch_live(code: str, target: date) -> tuple[dict, str]:
    """Строка живого CFTC на дату: {participant: (long, short, oi)}."""
    from src.data.cftc_client import fetch_report, resolve_contract_name
    m = market(code)
    contract = resolve_contract_name(m.report, m.cftc_match)
    rows = fetch_report(code, start_date=target, end_date=target)
    out = {}
    for r in rows:
        if r["report_date"] == target.isoformat():
            out[r["participant"]] = (r["long"], r["short"], r["open_interest"])
    return out, contract


def read_local(db: Database, code: str, target: date) -> dict:
    df = db.read_cot_raw(code)
    if df.empty:
        return {}
    sub = df[df["report_date"] == target]
    return {r["participant"]: (int(r["long"]), int(r["short"]), int(r["open_interest"]))
            for _, r in sub.iterrows()}


def validate_market(db: Database, code: str, target: date, live_available: bool) -> MarketResult:
    m = market(code)
    participants = PARTICIPANTS_BY_REPORT[m.report]

    if not live_available:
        return MarketResult(code, target.isoformat(), "BLOCKED",
                             message="Живой CFTC недоступен в этой среде — сверка не выполнялась.")

    try:
        live, contract = fetch_live(code, target)
    except Exception as e:  # noqa: BLE001 — любая сетевая/схемная проблема здесь фатальна для сверки
        return MarketResult(code, target.isoformat(), "BLOCKED",
                             message=f"Не удалось получить живые данные: {type(e).__name__}: {e}")

    if not live:
        return MarketResult(code, target.isoformat(), "FAIL", contract,
                             message=f"CFTC не вернул строку за {target}. Возможно, это не отчётный вторник.")

    local = read_local(db, code, target)
    checks: list[FieldCheck] = []

    for p in participants:
        lv = live.get(p)
        lo = local.get(p)
        for i, fname in enumerate(("long", "short", "open_interest")):
            a = lv[i] if lv else None
            b = lo[i] if lo else None
            checks.append(FieldCheck(code, p, fname, a, b, a == b,
                                      "" if lv and lo else "нет строки на одной из сторон"))
        # Net считаем сами с обеих сторон — если совпали Long и Short,
        # Net обязан совпасть; расхождение здесь означало бы ошибку в
        # самом сравнении.
        a_net = (lv[0] - lv[1]) if lv else None
        b_net = (lo[0] - lo[1]) if lo else None
        checks.append(FieldCheck(code, p, "net (пересчитан)", a_net, b_net, a_net == b_net))

    # Бухгалтерское тождество на живых данных
    identity_ok = None
    if live:
        oi = next(iter(live.values()))[2]
        sum_long = sum(v[0] for v in live.values())
        sum_short = sum(v[1] for v in live.values())
        identity_ok = (sum_long == oi and sum_short == oi)
        checks.append(FieldCheck(code, "ВСЕ ГРУППЫ", "сумма лонгов = OI", sum_long, oi, sum_long == oi))
        checks.append(FieldCheck(code, "ВСЕ ГРУППЫ", "сумма шортов = OI", sum_short, oi, sum_short == oi))

    failed = [c for c in checks if not c.match]
    if not local:
        status, msg = "FAIL", "В локальной базе нет данных на эту дату. Сначала загрузите их (START.bat / init_db.py --live)."
    elif failed:
        status = "FAIL"
        msg = f"Расхождений: {len(failed)} из {len(checks)}. Подробности в снимке."
    else:
        status = "PASS"
        msg = f"Все {len(checks)} проверок совпали."

    return MarketResult(code, target.isoformat(), status, contract,
                         [asdict(c) for c in checks], identity_ok, msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", nargs="+", default=None)
    ap.add_argument("--all-fx", action="store_true")
    ap.add_argument("--date", required=True, help="report_date, YYYY-MM-DD")
    args = ap.parse_args()

    codes = FX_CODES if args.all_fx else (args.markets or ["EUR", "GBP"])
    unknown = [c for c in codes if c not in all_codes()]
    if unknown:
        print(f"Неизвестные инструменты: {unknown}")
        sys.exit(2)

    target = date.fromisoformat(args.date)
    db = Database(settings.DB_PATH)

    # Одна дешёвая проба: есть ли вообще связь с CFTC
    live_available = True
    probe_error = ""
    try:
        from src.data.cftc_client import list_contract_names
        from config.markets import TFF
        names = list_contract_names(TFF, "EURO")
        if not names:
            live_available, probe_error = False, "CFTC ответил пустым списком контрактов"
    except Exception as e:  # noqa: BLE001
        live_available, probe_error = False, f"{type(e).__name__}: {e}"

    print("=" * 70)
    print(f"СВЕРКА С ЖИВЫМ CFTC · отчётная дата {target}")
    print("=" * 70)
    if not live_available:
        print(f"\nLIVE VALIDATION BLOCKED — {probe_error}")
        print("Сверка НЕ выполнена. Это не PASS и не FAIL: данных для сравнения не получено.\n")

    results = [validate_market(db, c, target, live_available) for c in codes]

    for r in results:
        icon = {"PASS": "PASS", "FAIL": "FAIL", "BLOCKED": "BLOCKED"}[r.status]
        print(f"\n[{icon}] {r.market}  ({r.contract_name or 'контракт не определён'})")
        print(f"       {r.message}")
        bad = [c for c in r.checks if not c["match"]]
        for c in bad[:12]:
            print(f"       расхождение · {c['participant']} / {c['field']}: "
                  f"CFTC={c['live']}  локально={c['local']}")

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot = VALIDATION_DIR / f"validation_{target.isoformat()}_{stamp}.json"
    snapshot.write_text(json.dumps({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "report_date": target.isoformat(),
        "live_available": live_available,
        "probe_error": probe_error,
        "results": [asdict(r) for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    statuses = {r.status for r in results}
    print("\n" + "=" * 70)
    if "BLOCKED" in statuses:
        overall = "BLOCKED"
    elif "FAIL" in statuses:
        overall = "FAIL"
    else:
        overall = "PASS"
    print(f"ИТОГ: {overall}")
    print(f"Снимок сохранён: {snapshot.relative_to(ROOT)}")
    print("=" * 70)

    if overall == "FAIL":
        print("\nНЕ считайте данные проверенными. Сначала сверьте PARTICIPANT_COLUMNS")
        print("в src/data/cftc_client.py с текущими названиями колонок в живых данных.")
    sys.exit({"PASS": 0, "FAIL": 1, "BLOCKED": 2}[overall])


if __name__ == "__main__":
    main()
