"""
src/data/db.py

Thin, dependency-light SQLite data-access layer (spec sections 35, 37).

Design choices (documented, not hidden):
- Plain sqlite3, no ORM: every query is visible and auditable.
- Raw ingested rows (`cot_raw`, `price_raw`) are append-only and deduplicated
  on (market, participant/pair, date, source). They are never overwritten by
  reprocessing -- reprocessing always starts from this raw layer.
- Derived tables (`cot_processed`, `market_states`) are fully rebuildable
  from the raw layer at any time (see src/pipeline.py) and are replaced
  wholesale on each rebuild -- there is no incremental-update bug surface
  in the derived layer, only in the (cheap, local) recomputation step.
"""
from __future__ import annotations
import sqlite3
import pandas as pd
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS cot_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    participant TEXT NOT NULL,
    report_date TEXT NOT NULL,
    availability_date TEXT NOT NULL,
    availability_source TEXT NOT NULL,
    long INTEGER NOT NULL,
    short INTEGER NOT NULL,
    open_interest INTEGER NOT NULL,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(market, participant, report_date, source)
);

CREATE TABLE IF NOT EXISTS cot_processed (
    market TEXT NOT NULL,
    participant TEXT NOT NULL,
    report_date TEXT NOT NULL,
    availability_date TEXT NOT NULL,
    long INTEGER, short INTEGER, net INTEGER, open_interest INTEGER,
    net_oi REAL, long_oi REAL, short_oi REAL,
    chg_1w REAL, chg_4w REAL, chg_8w REAL, chg_13w REAL, chg_26w REAL, chg_52w REAL,
    chg_4w_z REAL,
    pct_13w REAL, pct_26w REAL, pct_52w REAL, pct_156w REAL, pct_260w REAL,
    z_13w REAL, z_26w REAL, z_52w REAL, z_156w REAL, z_260w REAL,
    streak_up_weeks INTEGER, streak_down_weeks INTEGER,
    PRIMARY KEY (market, participant, report_date)
);

CREATE TABLE IF NOT EXISTS price_raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL NOT NULL,
    source TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    UNIQUE(pair, date, source)
);

CREATE TABLE IF NOT EXISTS market_states (
    market TEXT NOT NULL,
    report_date TEXT NOT NULL,
    availability_date TEXT NOT NULL,
    regime TEXT, regime_reasons TEXT, divergence_flags TEXT,
    price_close REAL,
    price_chg_4w REAL, price_chg_8w REAL, price_chg_12w REAL, price_chg_8w_z REAL,
    fwd_return_1w REAL, fwd_return_2w REAL, fwd_return_4w REAL,
    fwd_return_8w REAL, fwd_return_12w REAL, fwd_return_26w REAL,
    fwd_return_matured_json TEXT,
    features_json TEXT,
    PRIMARY KEY (market, report_date)
);

CREATE TABLE IF NOT EXISTS data_quality_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    source TEXT NOT NULL,
    check_name TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS research_notebook (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT,
    kind TEXT NOT NULL,
    condition_text TEXT,
    params_json TEXT,
    results_json TEXT,
    note TEXT
);

CREATE TABLE IF NOT EXISTS hypothesis_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    condition_text TEXT NOT NULL,
    market TEXT,
    horizon_weeks INTEGER
);

CREATE TABLE IF NOT EXISTS schema_watch (
    dataset TEXT PRIMARY KEY,
    column_signature TEXT NOT NULL,
    last_checked TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """SQLite has no native date type -- every date is stored as ISO TEXT
    and comes back from pandas.read_sql as a plain Python str. Every reader
    in this class converts the relevant columns to real datetime.date
    objects right here, ONCE, so no code downstream has to guess whether a
    given DataFrame's dates are strings or dates (the bug this fixes:
    comparing/adding timedelta to a str silently doesn't work)."""
    if df.empty:
        return df
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.date
    return df


class Database:
    def __init__(self, path: str = "data/cot_research.db"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- raw layer: append-only, deduplicated -----------------------------

    def upsert_cot_raw(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        with self.connect() as conn:
            cur = conn.executemany(
                """INSERT OR IGNORE INTO cot_raw
                   (market, participant, report_date, availability_date, availability_source,
                    long, short, open_interest, source, ingested_at)
                   VALUES (:market, :participant, :report_date, :availability_date,
                           :availability_source, :long, :short, :open_interest, :source, :ingested_at)""",
                rows,
            )
            return cur.rowcount

    def upsert_price_raw(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        with self.connect() as conn:
            cur = conn.executemany(
                """INSERT OR IGNORE INTO price_raw (pair, date, close, source, ingested_at)
                   VALUES (:pair, :date, :close, :source, :ingested_at)""",
                rows,
            )
            return cur.rowcount

    def read_cot_raw(self, market: str | None = None) -> pd.DataFrame:
        with self.connect() as conn:
            if market:
                df = pd.read_sql("SELECT * FROM cot_raw WHERE market = ? ORDER BY report_date", conn, params=[market])
            else:
                df = pd.read_sql("SELECT * FROM cot_raw ORDER BY market, participant, report_date", conn)
        return _parse_date_columns(df, ["report_date", "availability_date"])

    def read_price_raw(self, pair: str | None = None) -> pd.DataFrame:
        with self.connect() as conn:
            if pair:
                df = pd.read_sql("SELECT * FROM price_raw WHERE pair = ? ORDER BY date", conn, params=[pair])
            else:
                df = pd.read_sql("SELECT * FROM price_raw ORDER BY pair, date", conn)
        return _parse_date_columns(df, ["date"])

    # -- derived layer: fully rebuildable, replaced wholesale --------------

    def replace_cot_processed(self, df: pd.DataFrame):
        with self.connect() as conn:
            conn.execute("DELETE FROM cot_processed")
            df.to_sql("cot_processed", conn, if_exists="append", index=False)

    def read_cot_processed(self, market: str | None = None) -> pd.DataFrame:
        with self.connect() as conn:
            if market:
                df = pd.read_sql("SELECT * FROM cot_processed WHERE market = ? ORDER BY report_date", conn, params=[market])
            else:
                df = pd.read_sql("SELECT * FROM cot_processed ORDER BY market, participant, report_date", conn)
        return _parse_date_columns(df, ["report_date", "availability_date"])

    def replace_market_states(self, df: pd.DataFrame):
        with self.connect() as conn:
            conn.execute("DELETE FROM market_states")
            df.to_sql("market_states", conn, if_exists="append", index=False)

    def read_market_states(self, market: str | None = None) -> pd.DataFrame:
        with self.connect() as conn:
            if market:
                df = pd.read_sql("SELECT * FROM market_states WHERE market = ? ORDER BY report_date", conn, params=[market])
            else:
                df = pd.read_sql("SELECT * FROM market_states ORDER BY market, report_date", conn)
        return _parse_date_columns(df, ["report_date", "availability_date"])

    # -- data quality / research notebook / hypothesis log ------------------

    def log_quality(self, source: str, check_name: str, status: str, detail: str = ""):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO data_quality_log (run_at, source, check_name, status, detail) VALUES (?,?,?,?,?)",
                (now_iso(), source, check_name, status, detail),
            )

    def read_quality_log(self, limit: int = 200) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql("SELECT * FROM data_quality_log ORDER BY id DESC LIMIT ?", conn, params=[limit])

    def save_research(self, title: str, kind: str, condition_text: str, params_json: str, results_json: str, note: str = "") -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO research_notebook (created_at, title, kind, condition_text, params_json, results_json, note)
                   VALUES (?,?,?,?,?,?,?)""",
                (now_iso(), title, kind, condition_text, params_json, results_json, note),
            )
            return cur.lastrowid

    def read_research(self) -> pd.DataFrame:
        with self.connect() as conn:
            return pd.read_sql("SELECT * FROM research_notebook ORDER BY id DESC", conn)

    def log_hypothesis(self, condition_text: str, market: str | None, horizon_weeks: int | None):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO hypothesis_log (run_at, condition_text, market, horizon_weeks) VALUES (?,?,?,?)",
                (now_iso(), condition_text, market, horizon_weeks),
            )

    def count_hypotheses(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM hypothesis_log").fetchone()
            return row[0] if row else 0

    def check_schema_signature(self, dataset: str, signature: str) -> tuple[bool, str | None]:
        """Returns (changed, previous_signature). Records the new signature either way."""
        with self.connect() as conn:
            row = conn.execute("SELECT column_signature FROM schema_watch WHERE dataset = ?", (dataset,)).fetchone()
            prev = row[0] if row else None
            conn.execute(
                "INSERT INTO schema_watch (dataset, column_signature, last_checked) VALUES (?,?,?) "
                "ON CONFLICT(dataset) DO UPDATE SET column_signature=excluded.column_signature, last_checked=excluded.last_checked",
                (dataset, signature, now_iso()),
            )
            return (prev is not None and prev != signature), prev
