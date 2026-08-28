"""
src/pipeline.py

Orchestrates the full raw -> processed -> market_states build for every
currency present in cot_raw. This is intentionally a FULL REBUILD of the
derived layer every time it runs (spec section 58's "incremental update"
requirement is met at the FETCH layer, not here -- see src/data/loader.py):
recomputing rolling statistics for ~500-1000 weekly rows per currency is
cheap locally and avoids an entire class of incremental-recompute bugs.
This tradeoff is documented, not hidden -- see METHODOLOGY.md.
"""
from __future__ import annotations
import json
import pandas as pd
from datetime import date

from config import settings
from src.data.db import Database
from src.cot.metrics import add_basic_metrics, add_changes, add_streaks
from src.cot.percentile import add_percentiles, add_zscores, rolling_zscore_excl_current
from src.cot.regimes import classify_dataframe
from src.cot.divergence import detect_pairwise_divergence
from src.price.returns import add_forward_returns


def build_cot_processed(cot_raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (market, participant, report_date) with all derived
    per-participant metrics. `cot_raw` may span multiple markets."""
    frames = []
    for (market, participant), sub in cot_raw.groupby(["market", "participant"]):
        sub = sub.sort_values("report_date").reset_index(drop=True)
        sub = add_basic_metrics(sub)
        sub = add_changes(sub, "net")
        sub = add_streaks(sub, "net")
        sub = add_percentiles(sub, "net_oi")
        sub = add_zscores(sub, "net_oi")
        sub["chg_4w_z"] = rolling_zscore_excl_current(sub["chg_4w"], window=52)
        frames.append(sub)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    keep_cols = [
        "market", "participant", "report_date", "availability_date",
        "long", "short", "net", "open_interest", "net_oi", "long_oi", "short_oi",
        "chg_1w", "chg_4w", "chg_8w", "chg_13w", "chg_26w", "chg_52w", "chg_4w_z",
        "pct_13w", "pct_26w", "pct_52w", "pct_156w", "pct_260w",
        "z_13w", "z_26w", "z_52w", "z_156w", "z_260w",
        "streak_up_weeks", "streak_down_weeks",
    ]
    return out[keep_cols]


def pivot_wide(cot_processed: pd.DataFrame) -> pd.DataFrame:
    """Long (market, participant, report_date, <metrics>) -> wide
    (market, report_date, availability_date, <participant>_<metric>...)."""
    value_cols = [c for c in cot_processed.columns
                  if c not in ("market", "participant", "report_date", "availability_date")]
    wide = cot_processed.pivot(index=["market", "report_date", "availability_date"],
                                columns="participant", values=value_cols)
    wide.columns = [f"{participant}_{value_col}" for value_col, participant in wide.columns]
    return wide.reset_index()


def attach_price_features(wide: pd.DataFrame, price_df: pd.DataFrame) -> pd.DataFrame:
    """price_df: [date, close] daily. Attaches the price ON/AFTER each
    report_date (never before -- would look back) plus trailing % changes
    and a z-scored 8W change, all computed causally (shift-before-rolling)."""
    wide = wide.copy().sort_values("report_date").reset_index(drop=True)
    price_df = price_df.sort_values("date").reset_index(drop=True)

    def _close_on_or_after(d):
        cand = price_df[price_df["date"] >= d]
        return float(cand.iloc[0]["close"]) if len(cand) else None

    wide["price_close"] = wide["report_date"].apply(_close_on_or_after)
    wide["price_chg_4w"] = wide["price_close"].pct_change(4)
    wide["price_chg_8w"] = wide["price_close"].pct_change(8)
    wide["price_chg_12w"] = wide["price_close"].pct_change(12)
    wide["price_chg_8w_z"] = rolling_zscore_excl_current(wide["price_chg_8w"], window=52)
    return wide


def add_divergence_flags(wide: pd.DataFrame, window_weeks: int = 4) -> pd.DataFrame:
    wide = wide.copy()
    am_lev = detect_pairwise_divergence(wide, "asset_manager_net", "leveraged_funds_net",
                                         "Asset Managers", "Leveraged Funds", window_weeks)
    lev_price = detect_pairwise_divergence(wide, "leveraged_funds_net", "price_close",
                                            "Leveraged Funds", "Price", window_weeks)

    def _flags(i):
        out = []
        if am_lev.iloc[i]:
            out.append("Asset Managers vs Leveraged Funds")
        if lev_price.iloc[i]:
            out.append("Leveraged Funds vs Price")
        return out

    wide["divergence_flags"] = [json.dumps(_flags(i)) for i in range(len(wide))]
    return wide


def build_market_states_for_currency(cot_processed_all: pd.DataFrame, currency: str, price_df: pd.DataFrame | None,
                                      as_of_date: date | None = None) -> pd.DataFrame:
    sub = cot_processed_all[cot_processed_all["market"] == currency]
    wide = pivot_wide(sub)
    if price_df is not None and len(price_df):
        wide = attach_price_features(wide, price_df)
        wide = add_divergence_flags(wide)
        wide = add_forward_returns(wide, price_df, currency, settings.FORWARD_HORIZONS_WEEKS, as_of_date=as_of_date)
    else:
        wide["divergence_flags"] = "[]"
        for h in settings.FORWARD_HORIZONS_WEEKS:
            wide[f"fwd_return_{h}w"] = None

    wide = classify_dataframe(wide)
    wide["regime_reasons"] = wide["regime_reasons"].apply(json.dumps)
    wide["features_json"] = wide.apply(lambda r: r.drop(labels=["regime_reasons", "divergence_flags"], errors="ignore").to_json(default_handler=str), axis=1)
    return wide


def expand_features_json(df: pd.DataFrame) -> pd.DataFrame:
    """
    market_states as read back from the database only carries a fixed set
    of explicitly-named columns (see rebuild_all's db_cols) plus everything
    else packed into features_json -- this keeps the SQL schema stable even
    as regime/analog feature configs evolve. ANY caller that needs a
    per-participant wide column (leveraged_funds_net_oi, asset_manager_
    pct_52w, etc. -- used by the analog engine, the scanner, event studies,
    and backtest conditions) must call this right after db.read_market_states().
    Forgetting to call this was a real bug found during development
    (KeyError on the analog feature columns) -- see README "what was
    actually verified".
    """
    if df.empty or "features_json" not in df.columns:
        return df
    expanded = pd.json_normalize(df["features_json"].apply(json.loads))
    expanded.index = df.index
    new_cols = {col: expanded[col] for col in expanded.columns if col not in df.columns}
    # built and concatenated once (not assigned column-by-column) to avoid
    # pandas' fragmented-frame performance warning on wide feature sets.
    return pd.concat([df, pd.DataFrame(new_cols, index=df.index)], axis=1)


def rebuild_all(db: Database, price_data: dict[str, pd.DataFrame], as_of_date: date | None = None) -> None:
    """Full rebuild of cot_processed and market_states for every currency
    present in cot_raw. price_data: {currency: DataFrame[date, close]}."""
    cot_raw = db.read_cot_raw()
    if cot_raw.empty:
        raise RuntimeError("cot_raw is empty -- ingest data first (real or synthetic).")

    cot_processed = build_cot_processed(cot_raw)
    db.replace_cot_processed(cot_processed)

    all_states = []
    for currency in cot_processed["market"].unique():
        price_df = price_data.get(currency)
        states = build_market_states_for_currency(cot_processed, currency, price_df, as_of_date=as_of_date)
        all_states.append(states)
    combined = pd.concat(all_states, ignore_index=True)

    db_cols = [
        "market", "report_date", "availability_date", "regime", "regime_reasons", "divergence_flags",
        "price_close", "price_chg_4w", "price_chg_8w", "price_chg_12w", "price_chg_8w_z",
        "fwd_return_1w", "fwd_return_2w", "fwd_return_4w", "fwd_return_8w", "fwd_return_12w", "fwd_return_26w",
        "features_json",
    ]
    combined["fwd_return_matured_json"] = None  # reserved for future use; not populated in this build
    for c in db_cols:
        if c not in combined.columns:
            combined[c] = None
    db.replace_market_states(combined[db_cols + ["fwd_return_matured_json"]])
