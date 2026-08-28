"""
src/data/synthetic.py

Synthetic COT + price data generator.

WHY THIS EXISTS: the build sandbox this project was developed in has no
outbound network access to CFTC/FRED (confirmed by direct testing -- see
README "What was actually verified"). To run and test the full pipeline
end-to-end for real (not as pseudocode), this module produces a clearly
labeled, reproducible synthetic dataset shaped exactly like the real one.

EVERY row produced here is tagged source="synthetic_demo" in the database,
distinct from source="cftc_socrata" / "fred" used by the real connectors.
The Streamlit app and reports check this tag and show an explicit "DEMO /
SYNTHETIC DATA" banner -- see app/Home.py and src/reporting/report.py. This
data must never be described or exported as real market information.

One deliberate, documented design choice: weekly price returns are
generated as (small_known_coefficient * lagged leveraged-fund positioning
change) + noise. This is NOT an attempt to simulate a realistic market --
it exists so that scripts/run_demo.py can check that the analog/base-rate
engine actually recovers a *known, engineered* edge. Finding it is evidence
the statistics machinery works; it is not evidence about real FX markets.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from datetime import date, timedelta

from config import settings
from src.data.availability import get_availability

SYNTHETIC_SOURCE_TAG = "synthetic_demo"

# Deliberately engineered signal strength (see module docstring). Kept small
# and clearly named so nobody mistakes it for a real market effect.
ENGINEERED_SIGNAL_COEF = 0.35

_BASE_OI = {
    "EUR": 700_000, "GBP": 220_000, "JPY": 210_000, "AUD": 140_000,
    "CAD": 135_000, "CHF": 55_000, "NZD": 42_000, "MXN": 185_000,
}
_BASE_PRICE = {
    "EUR": 1.08, "GBP": 1.27, "JPY": 152.0, "AUD": 0.65,
    "CAD": 1.37, "CHF": 0.88, "NZD": 0.59, "MXN": 18.5,
}


def _weekly_tuesdays(start: date, end: date) -> list[date]:
    d = start
    while d.isoweekday() != 2:
        d += timedelta(days=1)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def _ou_process(n: int, rng: np.random.Generator, theta: float, sigma: float, scale: float) -> np.ndarray:
    """Mean-reverting Ornstein-Uhlenbeck-style process on [-scale, scale]-ish range."""
    x = np.zeros(n)
    for i in range(1, n):
        shock = rng.normal(0, sigma)
        # occasional regime shock to create genuine multi-week trends/extremes
        if rng.random() < 0.02:
            shock += rng.normal(0, sigma * 6)
        x[i] = x[i - 1] + theta * (0 - x[i - 1]) + shock
    return np.clip(x, -scale, scale)


def generate_currency(currency: str, start: date, end: date, seed: int) -> tuple[list[dict], pd.DataFrame]:
    """
    Returns (cot_raw_rows, price_df[date, close]) for one currency, fully
    synthetic, tagged accordingly.
    """
    rng = np.random.default_rng(seed)
    dates = _weekly_tuesdays(start, end)
    n = len(dates)
    base_oi = _BASE_OI[currency]

    oi = base_oi * (1 + 0.15 * np.cumsum(rng.normal(0, 0.01, n)))
    oi = np.maximum(oi, base_oi * 0.5)

    lev_net_frac = _ou_process(n, rng, theta=0.06, sigma=0.03, scale=0.45)
    am_net_frac = _ou_process(n, rng, theta=0.03, sigma=0.015, scale=0.35)
    other_net_frac = _ou_process(n, rng, theta=0.10, sigma=0.02, scale=0.20)
    dealer_net_frac = -0.5 * am_net_frac - 0.3 * lev_net_frac + _ou_process(n, rng, theta=0.08, sigma=0.01, scale=0.15)

    ingested_at = pd.Timestamp.utcnow().isoformat()
    rows: list[dict] = []
    lev_net_prev = 0.0
    for i, d in enumerate(dates):
        this_oi = float(oi[i])
        avail = get_availability(d)

        def long_short(net_frac: float, gross_mult: float) -> tuple[int, int]:
            net = net_frac * this_oi
            gross = max(gross_mult * this_oi, abs(net) * 1.1 + 50)
            long_v = int(round((gross + net) / 2))
            short_v = int(round((gross - net) / 2))
            return max(long_v, 0), max(short_v, 0)

        participants_ls = {
            "dealer": long_short(dealer_net_frac[i], 0.35),
            "asset_manager": long_short(am_net_frac[i], 0.55),
            "leveraged_funds": long_short(lev_net_frac[i], 0.5),
            "other_reportables": long_short(other_net_frac[i], 0.15),
        }

        # The COT accounting identity requires that all participant longs sum
        # to open interest, and likewise shorts (non-reportables being the
        # residual). Because the gross-position floor above can, at extreme
        # net values, push total reportable positions past OI, the residual
        # would go negative and get clamped to zero -- silently breaking the
        # identity. Scale reportable positions down proportionally so the
        # residual is always >= 0 and the identity holds exactly. (Caught by
        # check_accounting_identity in src/data/data_quality.py, which is
        # exactly the kind of defect that check exists to find.)
        oi_int = int(round(this_oi))
        for side_index in (0, 1):
            total = sum(v[side_index] for v in participants_ls.values())
            if total > oi_int:
                scale = oi_int / total
                for participant, values in participants_ls.items():
                    scaled = list(values)
                    scaled[side_index] = int(scaled[side_index] * scale)
                    participants_ls[participant] = tuple(scaled)

        reportable_long_total = sum(v[0] for v in participants_ls.values())
        reportable_short_total = sum(v[1] for v in participants_ls.values())

        for participant, (long_v, short_v) in participants_ls.items():
            rows.append({
                "market": currency, "participant": participant,
                "report_date": d.isoformat(), "availability_date": avail.availability_date.isoformat(),
                "availability_source": avail.source, "long": long_v, "short": short_v,
                "open_interest": oi_int, "source": SYNTHETIC_SOURCE_TAG, "ingested_at": ingested_at,
            })
        rows.append({
            "market": currency, "participant": "nonreportables",
            "report_date": d.isoformat(), "availability_date": avail.availability_date.isoformat(),
            "availability_source": avail.source,
            "long": max(oi_int - reportable_long_total, 0),
            "short": max(oi_int - reportable_short_total, 0),
            "open_interest": oi_int, "source": SYNTHETIC_SOURCE_TAG, "ingested_at": ingested_at,
        })
        lev_net_prev = lev_net_frac[i]

    # --- price: engineered positioning-driven signal + noise (see module docstring) ---
    price = np.zeros(n)
    price[0] = _BASE_PRICE[currency]
    lev_chg = np.diff(lev_net_frac, prepend=lev_net_frac[0])
    noise_vol = 0.012
    for i in range(1, n):
        weekly_ret = ENGINEERED_SIGNAL_COEF * lev_chg[i - 1] + rng.normal(0, noise_vol)
        price[i] = max(price[i - 1] * (1 + weekly_ret), 0.0001)

    price_df = pd.DataFrame({"date": dates, "close": price})
    return rows, price_df


def generate_all(start: date | None = None, end: date | None = None, seed: int = settings.RANDOM_SEED):
    start = start or date(2015, 1, 6)
    end = end or date.today()
    all_rows: list[dict] = []
    price_frames: dict[str, pd.DataFrame] = {}
    for idx, currency in enumerate(settings.CURRENCIES):
        rows, price_df = generate_currency(currency, start, end, seed=seed + idx)
        all_rows.extend(rows)
        price_frames[currency] = price_df
    return all_rows, price_frames
