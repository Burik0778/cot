"""
src/data/cftc_client.py

Клиент CFTC Public Reporting (Socrata) для двух отчётов сразу:
    TFF            — gpe5-46if — финансовые фьючерсы
    DISAGGREGATED  — 72hh-3qpy — товары (у нас только металлы)

Контракты ищутся ПО ПОДСТРОКЕ через SoQL `like`, а не точным совпадением.
Причина: CFTC периодически переименовывает контракты, и точное совпадение
даёт ноль строк — то есть рынок молча исчезает из сборки. При поиске по
подстроке мы либо находим, либо падаем с внятной ошибкой, где перечислены
похожие названия из живых данных.

Если API недоступен, схема изменилась или контракт не найден — исключение,
а не пустые/выдуманные строки.
"""
from __future__ import annotations
import requests
from datetime import date, datetime
from typing import Optional

from config import settings
from config.markets import market, RESOURCE_IDS, TFF, DISAGGREGATED

from src.data.availability import get_availability

BASE_URLS = settings.CFTC_API_BASE_URL_CANDIDATES

COMMON_COLUMNS = ["report_date_as_yyyy_mm_dd", "market_and_exchange_names", "open_interest_all"]

PARTICIPANT_COLUMNS = {
    TFF: {
        "dealer": ("dealer_positions_long_all", "dealer_positions_short_all"),
        "asset_manager": ("asset_mgr_positions_long", "asset_mgr_positions_short"),
        "leveraged_funds": ("lev_money_positions_long", "lev_money_positions_short"),
        "other_reportables": ("other_rept_positions_long", "other_rept_positions_short"),
    },
    DISAGGREGATED: {
        "producer_merchant": ("prod_merc_positions_long", "prod_merc_positions_short"),
        "swap_dealers": ("swap_positions_long_all", "swap__positions_short_all"),
        "managed_money": ("m_money_positions_long_all", "m_money_positions_short_all"),
        "other_reportables": ("other_rept_positions_long", "other_rept_positions_short"),
    },
}


class CftcApiError(RuntimeError):
    """CFTC недоступен."""


class CftcSchemaError(RuntimeError):
    """Схема изменилась или контракт не найден — молча не продолжаем."""


def _get(base_url: str, resource_id: str, params: dict, timeout: int = 45) -> list[dict]:
    url = f"{base_url}/{resource_id}.json"
    resp = requests.get(url, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise CftcApiError(f"CFTC вернул HTTP {resp.status_code} для {url}: {resp.text[:300]}")
    return resp.json()


def _request(resource_id: str, params: dict) -> list[dict]:
    last_error = None
    for base in BASE_URLS:
        try:
            return _get(base, resource_id, params)
        except Exception as e:  # noqa: BLE001 — пробуем следующий хост
            last_error = e
    raise CftcApiError(
        f"Ни один хост CFTC не ответил. Пробовали: {BASE_URLS}. Последняя ошибка: {last_error}")


_NAME_CACHE: dict[str, list[str]] = {}


def list_contract_names(report: str, pattern: str = "") -> list[str]:
    """
    Все названия контрактов в живых данных, с кэшем на процесс.

    Фильтрация делается в Python, а НЕ через SoQL `like`/`upper()`:
    разные версии Socrata поддерживают их по-разному, и запрос, который
    молча возвращает ноль строк, выглядит как «контракта не существует».
    Один запрос за полным списком надёжнее любого серверного фильтра.
    """
    if report not in _NAME_CACHE:
        rows = _request(RESOURCE_IDS[report], {
            "$select": "market_and_exchange_names",
            "$group": "market_and_exchange_names",
            "$limit": 50000,
        })
        _NAME_CACHE[report] = sorted(
            {r["market_and_exchange_names"] for r in rows if r.get("market_and_exchange_names")})
    names = _NAME_CACHE[report]
    if not pattern:
        return names
    p = pattern.upper()
    return [n for n in names if p in n.upper()]


def resolve_contract_name(report: str, match: str) -> str:
    """
    Находит контракт по одному из вариантов написания. `match` может быть
    строкой или списком вариантов через '|' — пробуем по очереди, потому
    что CFTC пишет одни и те же контракты по-разному в разные годы.

    Если вариантов совпало несколько, берём самое короткое название: это
    обычно основной контракт, а не его микро/мини-версия с более длинным
    именем. Правило задокументировано, а не случайно.
    """
    variants = [v.strip() for v in match.split("|") if v.strip()]
    for variant in variants:
        names = list_contract_names(report, variant)
        if names:
            return min(names, key=len)

    first_word = variants[0].split()[0] if variants and variants[0].split() else ""
    hint = list_contract_names(report, first_word) if first_word else []
    raise CftcSchemaError(
        f"В отчёте {report} не найден контракт ни по одному из вариантов {variants}. "
        f"Похожие названия в живых данных: {hint[:15] or 'ничего похожего'}. "
        f"Обновите cftc_match в config/markets.py."
    )


def fetch_report(code: str, start_date: Optional[date] = None,
                 end_date: Optional[date] = None, page_size: int = 50000) -> list[dict]:
    """История одного инструмента, развёрнутая в строки для cot_raw."""
    m = market(code)
    report = m.report
    resource_id = RESOURCE_IDS[report]
    contract = resolve_contract_name(report, m.cftc_match)

    where = [f"market_and_exchange_names='{contract}'"]
    if start_date:
        where.append(f"report_date_as_yyyy_mm_dd >= '{start_date.isoformat()}T00:00:00.000'")
    if end_date:
        where.append(f"report_date_as_yyyy_mm_dd <= '{end_date.isoformat()}T00:00:00.000'")

    payload = _request(resource_id, {
        "$where": " AND ".join(where),
        "$order": "report_date_as_yyyy_mm_dd ASC",
        "$limit": page_size,
    })

    if not payload:
        raise CftcSchemaError(f"Контракт '{contract}' найден, но строк за период нет ({code}).")

    columns = PARTICIPANT_COLUMNS[report]
    present = set(payload[0].keys())
    missing = [c for c in COMMON_COLUMNS if c not in present]
    for participant, (lc, sc) in columns.items():
        missing += [c for c in (lc, sc) if c not in present]
    if missing:
        raise CftcSchemaError(
            f"Схема отчёта {report} изменилась: нет колонок {sorted(set(missing))}. "
            f"Доступные: {sorted(present)[:40]}. "
            f"Поправьте PARTICIPANT_COLUMNS в src/data/cftc_client.py."
        )

    rows: list[dict] = []
    ingested_at = datetime.utcnow().isoformat()
    for rec in payload:
        report_date = datetime.strptime(rec["report_date_as_yyyy_mm_dd"][:10], "%Y-%m-%d").date()
        avail = get_availability(report_date)
        oi = int(float(rec["open_interest_all"]))

        long_total = short_total = 0
        for participant, (lc, sc) in columns.items():
            lv = int(float(rec[lc] or 0))
            sv = int(float(rec[sc] or 0))
            long_total += lv
            short_total += sv
            rows.append({
                "market": code, "participant": participant,
                "report_date": report_date.isoformat(),
                "availability_date": avail.availability_date.isoformat(),
                "availability_source": avail.source,
                "long": lv, "short": sv, "open_interest": oi,
                "source": f"cftc_{report}", "ingested_at": ingested_at,
            })

        rows.append({
            "market": code, "participant": "nonreportables",
            "report_date": report_date.isoformat(),
            "availability_date": avail.availability_date.isoformat(),
            "availability_source": avail.source,
            "long": max(oi - long_total, 0), "short": max(oi - short_total, 0),
            "open_interest": oi,
            "source": f"cftc_{report}", "ingested_at": ingested_at,
        })

    return rows


def fetch_tff_futures_only(currency: str, start_date=None, end_date=None, page_size=50000):
    """Совместимость со старым именем."""
    return fetch_report(currency, start_date, end_date, page_size)
