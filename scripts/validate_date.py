"""
scripts/validate_date.py

Spec section 52: "take a specific CFTC date, check Long/Short/Net/Open
Interest against the official CFTC source; if they differ, do NOT say
everything is fine -- stop and explain the discrepancy."

This script cannot run inside the build sandbox (no network route to CFTC
-- confirmed by direct testing). It is written so that the FIRST thing you
do after `init_db.py --live` is run this, side by side with CFTC's own
website, for one specific date, before trusting anything else.

Usage:
    python scripts/validate_date.py --market EUR --date 2026-08-18
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from config.markets import all_codes, market
from src.data.db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=all_codes())
    parser.add_argument("--date", required=True, help="report_date, YYYY-MM-DD")
    args = parser.parse_args()

    target = date.fromisoformat(args.date)
    db = Database(settings.DB_PATH)
    df = db.read_cot_raw(args.market)
    if df.empty:
        print(f"No data for {args.market} in the database. Run init_db.py first.")
        sys.exit(1)

    rows = df[df["report_date"] == target]
    if rows.empty:
        available = sorted(df["report_date"].unique())
        nearest = min(available, key=lambda d: abs((d - target).days)) if available else None
        print(f"No row for {args.market} on {target}. Nearest available report_date: {nearest}")
        sys.exit(1)

    m_ = market(args.market)
    report_title = "TFF (Traders in Financial Futures) — Futures Only" if m_.report == "tff" \
        else "Disaggregated — Futures Only"
    print(f"=== {args.market} ({m_.name}) · {report_title} · отчёт за {target} ===")
    m = market(args.market)
    print(f"Отчёт: {m.report.upper()} · поиск контракта по подстроке: {m.cftc_match!r}")
    print(f"Source: {rows.iloc[0]['source']}")
    print()
    dataset = "Traders in Financial Futures — Futures Only" if m_.report == "tff" \
        else "Disaggregated — Futures Only"
    print("Сверьте КАЖДУЮ строку ниже с официальным отчётом CFTC:")
    print(f"  https://publicreporting.cftc.gov/  (набор данных: {dataset})")
    print("или с историческими отчётами в читаемом виде:")
    print("  https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/index.htm")
    print()
    for _, r in rows.sort_values("participant").iterrows():
        print(f"  {r['participant']:<20s}  Long={r['long']:>10,d}  Short={r['short']:>10,d}  "
              f"Net={r['long'] - r['short']:>10,d}  OpenInterest={r['open_interest']:>10,d}")
    print()
    print("Если ХОТЬ ОДНА цифра расходится с официальным отчётом — не продолжайте.")
    print("Сначала проверьте PARTICIPANT_COLUMNS в src/data/cftc_client.py против")
    print("текущих названий колонок в живых данных, и только потом ищите ошибку в расчётах.")


if __name__ == "__main__":
    main()
