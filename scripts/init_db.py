"""
scripts/init_db.py

Usage:
    python scripts/init_db.py --synthetic [--start 2015-01-06] [--end 2026-08-18]
    python scripts/init_db.py --live --currencies EUR GBP [--start 2015-01-06]

--synthetic populates data/cot_research.db with clearly-labeled synthetic
data (source=synthetic_demo) and requires no network access -- this is
what was used to build and test this platform (see README).

--live calls the real CFTC and FRED connectors. This has NOT been
exercised end-to-end during development (the build sandbox has no route to
either host -- confirmed by direct testing, see README "What was actually
verified"). Run this on a machine with normal internet access, then run
scripts/validate_date.py immediately after to check the results against
CFTC's own published numbers before trusting anything downstream.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from config.markets import all_codes
from src.data.db import Database, now_iso
from src.data.synthetic import generate_all
from src.pipeline import rebuild_all


def init_synthetic(db: Database, start: date, end: date):
    print(f"Generating synthetic demo data from {start} to {end} (source=synthetic_demo)...")
    rows, price_frames = generate_all(start=start, end=end)
    n = db.upsert_cot_raw(rows)
    print(f"  cot_raw: {len(rows)} rows generated, {n} inserted (deduplicated).")

    price_rows = []
    for ccy, pdf in price_frames.items():
        for _, r in pdf.iterrows():
            price_rows.append({"pair": ccy, "date": r["date"].isoformat(), "close": float(r["close"]),
                                "source": "synthetic_demo", "ingested_at": now_iso()})
    n_price = db.upsert_price_raw(price_rows)
    print(f"  price_raw: {len(price_rows)} rows generated, {n_price} inserted (deduplicated).")

    print("Rebuilding cot_processed and market_states...")
    rebuild_all(db, price_frames, as_of_date=end)
    print("Done. This is SYNTHETIC data -- see README before using it for anything beyond testing the platform.")


def init_live(db: Database, currencies: list[str], start: date, end: date | None):
    from src.data.cftc_client import fetch_report, CftcApiError, CftcSchemaError
    from src.data.price_client import fetch_price_series, PriceApiError, PriceSourceNotConfigured

    price_frames = {}
    any_cot_success = False
    for currency in currencies:
        print(f"[{currency}] Fetching CFTC TFF Futures Only...")
        try:
            rows = fetch_report(currency, start_date=start, end_date=end)
            n = db.upsert_cot_raw(rows)
            print(f"  {len(rows)} rows fetched, {n} new rows inserted.")
            any_cot_success = True
        except (CftcApiError, CftcSchemaError) as e:
            print(f"  FAILED (per spec section 57, this failure does not affect other currencies): {e}")
            continue

        print(f"[{currency}] Fetching price series...")
        try:
            pdf = fetch_price_series(currency, start_date=start)
            price_frames[currency] = pdf
            price_rows = [{"pair": currency, "date": d.isoformat(), "close": float(c),
                            "source": "fred", "ingested_at": now_iso()}
                          for d, c in zip(pdf["date"], pdf["close"])]
            n_price = db.upsert_price_raw(price_rows)
            print(f"  {len(price_rows)} rows fetched, {n_price} new rows inserted.")
        except (PriceApiError, PriceSourceNotConfigured) as e:
            print(f"  Price fetch failed ({e}) -- COT analysis for {currency} will still work per spec section 57, "
                  f"but price/regime/forward-return features will be unavailable for it.")

    if not any_cot_success:
        raise RuntimeError("No currency's COT data could be fetched -- refusing to rebuild derived tables from nothing.")

    print("Rebuilding cot_processed and market_states...")
    rebuild_all(db, price_frames, as_of_date=end or date.today())
    print("Done.")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--synthetic", action="store_true")
    group.add_argument("--live", action="store_true")
    parser.add_argument("--currencies", nargs="+", default=all_codes())
    parser.add_argument("--start", type=str, default="2015-01-06")
    parser.add_argument("--end", type=str, default=None)
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else date.today()

    db = Database(settings.DB_PATH)
    if args.synthetic:
        init_synthetic(db, start, end)
    else:
        init_live(db, args.currencies, start, end)


if __name__ == "__main__":
    main()
