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
from src.data.db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True, choices=settings.CURRENCIES)
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

    print(f"=== {args.market} TFF Futures Only -- report_date {target} ===")
    print(f"CFTC contract name used for this currency: {settings.CFTC_MARKET_NAMES[args.market]}")
    print(f"Source: {rows.iloc[0]['source']}")
    print()
    print("Compare EVERY row below against the official CFTC report at:")
    print("  https://publicreporting.cftc.gov/  (search: Traders in Financial Futures, Futures Only)")
    print("or the human-readable historical viewable report at:")
    print("  https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/index.htm")
    print()
    for _, r in rows.sort_values("participant").iterrows():
        print(f"  {r['participant']:<20s}  Long={r['long']:>10,d}  Short={r['short']:>10,d}  "
              f"Net={r['long'] - r['short']:>10,d}  OpenInterest={r['open_interest']:>10,d}")
    print()
    print("If ANY of these numbers differ from the official CFTC report, DO NOT proceed --")
    print("open a discrepancy note in LIMITATIONS.md describing exactly what differs, and check")
    print("REQUIRED_COLUMNS / PARTICIPANT_COLUMN_MAP in src/data/cftc_client.py against the live")
    print("dataset's current column names before assuming the platform's math is at fault.")


if __name__ == "__main__":
    main()
