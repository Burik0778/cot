"""
config/markets.py

Реестр инструментов. Одно место, где перечислено всё, что тянет система.

Два источника CFTC:
  TFF (Traders in Financial Futures, ресурс gpe5-46if)
      — валюты, индексы, ставки, крипта.
      Группы: Dealer / Asset Manager / Leveraged Funds / Other / Non-Reportable

  DISAGGREGATED (ресурс 72hh-3qpy)
      — физические товары, у нас только металлы.
      Группы: Producer-Merchant / Swap Dealers / Managed Money / Other / Non-Reportable

Это РАЗНЫЕ группы участников, и читаются они по-разному. Поэтому у каждого
рынка есть роли:
    spec  — быстрые спекулятивные деньги (Leveraged Funds / Managed Money)
    slow  — вторая опорная группа. В TFF это Asset Manager (инерционный
            институциональный капитал, идёт скорее вместе с трендом).
            В Disaggregated это Producer/Merchant — ХЕДЖЕРЫ, они по
            определению стоят против спекулянтов и их рост net-позиции
            означает обратное. Знак интерпретации задаётся slow_is_contrarian.

Названия контрактов CFTC ищутся ПО ПОДСТРОКЕ, а не точным совпадением:
CFTC периодически их переименовывает, и жёсткое совпадение — самый частый
способ молча потерять рынок. См. src/data/cftc_client.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

TFF = "tff"
DISAGGREGATED = "disaggregated"

# Ресурсы Socrata, подтверждены 2026-08-28 по документации CFTC и OpenAPI
RESOURCE_IDS = {
    TFF: "gpe5-46if",
    DISAGGREGATED: "72hh-3qpy",
}

# Роли участников по типу отчёта
ROLE_COLUMNS = {
    TFF: {
        "spec": "leveraged_funds",
        "slow": "asset_manager",
        "other_side": "dealer",
    },
    DISAGGREGATED: {
        "spec": "managed_money",
        "slow": "producer_merchant",
        "other_side": "swap_dealers",
    },
}

PARTICIPANTS_BY_REPORT = {
    TFF: ["dealer", "asset_manager", "leveraged_funds", "other_reportables", "nonreportables"],
    DISAGGREGATED: ["producer_merchant", "swap_dealers", "managed_money", "other_reportables", "nonreportables"],
}

PARTICIPANT_RU = {
    "dealer": "Дилеры",
    "asset_manager": "Управляющие активами",
    "leveraged_funds": "Хедж-фонды",
    "producer_merchant": "Производители и торговцы",
    "swap_dealers": "Своп-дилеры",
    "managed_money": "Управляемые деньги",
    "other_reportables": "Прочие крупные",
    "nonreportables": "Мелкие участники",
}

PARTICIPANT_ROLE_RU = {
    "dealer": "маркет-мейкеры, обычно на другой стороне от спекулянтов",
    "asset_manager": "медленный институциональный капитал",
    "leveraged_funds": "быстрые спекулятивные деньги",
    "producer_merchant": "хеджеры: добытчики и переработчики, страхуют физический товар",
    "swap_dealers": "посредники по свопам, зеркалят клиентский поток",
    "managed_money": "быстрые спекулятивные деньги: фонды и CTA",
    "other_reportables": "крупные участники вне основных категорий",
    "nonreportables": "мелкие участники, считаются как остаток",
}


@dataclass(frozen=True)
class Market:
    code: str                       # внутренний код: EUR, SP500, GOLD
    name: str                       # человеческое имя по-русски
    sector: str                     # FX / INDICES / CRYPTO / METALS / RATES
    report: str                     # TFF или DISAGGREGATED
    cftc_match: str                 # подстрока для поиска контракта в данных CFTC
    price_symbol: Optional[str] = None      # как называем ценовой ряд
    fred_series: Optional[str] = None       # серия FRED, если есть
    price_is_inverse: bool = False  # True: рост пары = ослабление инструмента (USD в базе)
    aliases: tuple = field(default_factory=tuple)


SECTORS_RU = {
    "FX": "Валюты",
    "INDICES": "Индексы",
    "CRYPTO": "Крипта",
    "METALS": "Металлы",
    "RATES": "Ставки",
}

MARKETS: list[Market] = [
    # ─── Валюты (TFF) ────────────────────────────────────────────────────
    Market("EUR", "Евро", "FX", TFF, "EURO FX", "EURUSD", "DEXUSEU"),
    Market("GBP", "Фунт стерлингов", "FX", TFF, "BRITISH POUND", "GBPUSD", "DEXUSUK"),
    Market("JPY", "Японская иена", "FX", TFF, "JAPANESE YEN", "USDJPY", "DEXJPUS", True),
    Market("AUD", "Австралийский доллар", "FX", TFF, "AUSTRALIAN DOLLAR", "AUDUSD", "DEXUSAL"),
    Market("CAD", "Канадский доллар", "FX", TFF, "CANADIAN DOLLAR", "USDCAD", "DEXCAUS", True),
    Market("CHF", "Швейцарский франк", "FX", TFF, "SWISS FRANC", "USDCHF", "DEXSZUS", True),
    Market("NZD", "Новозеландский доллар", "FX", TFF, "NEW ZEALAND DOLLAR", "NZDUSD", None),
    Market("MXN", "Мексиканское песо", "FX", TFF, "MEXICAN PESO", "USDMXN", "DEXMXUS", True),
    Market("DXY", "Индекс доллара", "FX", TFF, "USD INDEX|U.S. DOLLAR INDEX|DOLLAR INDEX", "DXY", None),

    # ─── Индексы (TFF) ───────────────────────────────────────────────────
    Market("SP500", "S&P 500", "INDICES", TFF, "E-MINI S&P 500|E-MINI S&P500|S&P 500 Consolidated|S&P 500", "SPX", "SP500"),
    Market("NASDAQ", "Nasdaq 100", "INDICES", TFF, "NASDAQ-100 Consolidated|NASDAQ-100 STOCK INDEX|E-MINI NASDAQ|NASDAQ", "NDX", "NASDAQ100"),
    Market("DOW", "Dow Jones", "INDICES", TFF, "DJIA Consolidated|DOW JONES|DJIA", "DJI", "DJIA"),
    Market("RUSSELL", "Russell 2000", "INDICES", TFF, "RUSSELL E-MINI|E-MINI RUSSELL 2000|RUSSELL 2000", "RUT", None),
    Market("VIX", "Индекс волатильности VIX", "INDICES", TFF, "VIX FUTURES|CBOE VOLATILITY|VOLATILITY INDEX", "VIX", "VIXCLS"),

    # ─── Крипта (TFF) ────────────────────────────────────────────────────
    Market("BTC", "Биткоин", "CRYPTO", TFF, "BITCOIN", "BTCUSD", "CBBTCUSD"),
    Market("ETH", "Эфир", "CRYPTO", TFF, "ETHER CASH SETTLED|ETHER", "ETHUSD", "CBETHUSD"),

    # ─── Металлы (DISAGGREGATED) ─────────────────────────────────────────
    Market("GOLD", "Золото", "METALS", DISAGGREGATED, "GOLD - COMMODITY EXCHANGE|GOLD", "XAUUSD", None),
    Market("SILVER", "Серебро", "METALS", DISAGGREGATED, "SILVER - COMMODITY EXCHANGE|SILVER", "XAGUSD", None),
    Market("COPPER- #1|COPPER", "Медь", "METALS", DISAGGREGATED, "COPPER", "COPPER", None),
    Market("PLATINUM", "Платина", "METALS", DISAGGREGATED, "PLATINUM", "XPTUSD", None),

    # ─── Ставки (TFF) ────────────────────────────────────────────────────
    Market("UST10Y", "Гособлигации США 10 лет", "RATES", TFF, "UST 10Y NOTE|10-YEAR U.S. TREASURY|10 YEAR NOTE", "US10Y", None),
    Market("UST2Y", "Гособлигации США 2 года", "RATES", TFF, "UST 2Y NOTE|2-YEAR U.S. TREASURY|2 YEAR NOTE", "US2Y", None),
]

BY_CODE = {m.code: m for m in MARKETS}


def market(code: str) -> Market:
    if code not in BY_CODE:
        raise KeyError(f"Неизвестный инструмент '{code}'. Доступны: {sorted(BY_CODE)}")
    return BY_CODE[code]


def codes_for_report(report: str) -> list[str]:
    return [m.code for m in MARKETS if m.report == report]


def all_codes() -> list[str]:
    return [m.code for m in MARKETS]


def spec_key(code: str) -> str:
    """Колонка быстрых спекулятивных денег для этого рынка."""
    return ROLE_COLUMNS[market(code).report]["spec"]


def slow_key(code: str) -> str:
    return ROLE_COLUMNS[market(code).report]["slow"]


def other_side_key(code: str) -> str:
    return ROLE_COLUMNS[market(code).report]["other_side"]


def slow_is_contrarian(code: str) -> bool:
    """
    True, если вторая опорная группа — хеджеры (Producer/Merchant в
    Disaggregated). Они по определению стоят против спекулянтов, и рост их
    чистой позиции читается ПРОТИВОПОЛОЖНО росту позиции Asset Manager в TFF.
    Без этого флага разбор металлов был бы перевёрнут.
    """
    return market(code).report == DISAGGREGATED
