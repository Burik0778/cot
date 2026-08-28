"""
scripts/refresh_data.py

Spec section 36: check for new COT reports, don't re-download old data
unnecessarily. Incremental at the FETCH layer (only requests report_dates
after the latest one already in cot_raw); the derived-table rebuild that
follows is a full, cheap, local recompute (see src/pipeline.py docstring
for why that tradeoff is deliberate, not an oversight).

Usage:
    python scripts/refresh_data.py --currencies EUR GBP
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from config.markets import all_codes
from src.data.db import Database, now_iso
from src.pipeline import rebuild_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--currencies", nargs="+", default=all_codes())
    args = parser.parse_args()

    from src.data.cftc_client import fetch_report, CftcApiError, CftcSchemaError
    from src.data.price_client import fetch_price_series, PriceApiError, PriceSourceNotConfigured

    db = Database(settings.DB_PATH)
    price_frames = {}

    for currency in args.currencies:
        existing = db.read_cot_raw(currency)
        since = (existing["report_date"].max() + timedelta(days=1)) if len(existing) else date(2015, 1, 6)
        print(f"[{currency}] Fetching reports since {since}...")
        try:
            rows = fetch_report(currency, start_date=since)
            n = db.upsert_cot_raw(rows)
            print(f"  {len(rows)} rows fetched, {n} genuinely new.")
        except (CftcApiError, CftcSchemaError) as e:
            print(f"  FAILED: {e}")
            continue

        try:
            pdf = fetch_price_series(currency, start_date=since - timedelta(days=30))
            price_frames[currency] = pdf
            rows = [{"pair": currency, "date": d.isoformat(), "close": float(c), "source": "fred", "ingested_at": now_iso()}
                    for d, c in zip(pdf["date"], pdf["close"])]
            db.upsert_price_raw(rows)
        except (PriceApiError, PriceSourceNotConfigured) as e:
            print(f"  Price refresh failed ({e}) -- continuing with COT-only data for {currency}.")

    print("Rebuilding derived tables...")
    rebuild_all(db, price_frames, as_of_date=date.today())
    print("Refresh complete.")


if __name__ == "__main__":
    main()
