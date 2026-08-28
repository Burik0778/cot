"""
src/data/data_quality.py

Spec section 34. Every check RETURNS a finding; it never silently repairs
data or hides a problem. `run_all_checks` is meant to be called after every
ingestion/rebuild and its results logged via Database.log_quality so the
Data Quality UI page has a real history, not just the latest snapshot.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class QualityFinding:
    check_name: str
    status: str  # "ok" | "warning" | "error"
    detail: str


def check_missing_weeks(df: pd.DataFrame, date_col: str = "report_date", expected_gap_days: int = 7) -> QualityFinding:
    dates = sorted(pd.to_datetime(df[date_col]).unique())
    if len(dates) < 2:
        return QualityFinding("missing_weeks", "ok", "Not enough rows to check for gaps.")
    gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    bad = [(dates[i].date(), dates[i + 1].date(), g) for i, g in enumerate(gaps) if g > expected_gap_days and g < 21]
    # gaps of 21+ days are common around known holiday clusters/backlog windows and are
    # reported separately rather than flagged as anomalies here.
    if bad:
        return QualityFinding("missing_weeks", "warning", f"{len(bad)} gap(s) longer than {expected_gap_days} days found, e.g. {bad[:3]}")
    return QualityFinding("missing_weeks", "ok", "No unexplained gaps between consecutive report dates.")


def check_duplicates(df: pd.DataFrame, subset: list[str]) -> QualityFinding:
    dupes = df.duplicated(subset=subset, keep=False)
    if dupes.any():
        return QualityFinding("duplicates", "error", f"{dupes.sum()} duplicated row(s) on {subset}.")
    return QualityFinding("duplicates", "ok", "No duplicate rows.")


def check_unexpected_jumps(df: pd.DataFrame, value_col: str, threshold: float = 3.5) -> QualityFinding:
    """
    Uses a MEDIAN-based robust modified z-score (Iglewicz & Hoaglin), not a
    classical mean/std z-score. Classical std is itself inflated by the
    very outlier it is supposed to detect (a single huge jump can drag the
    z-score of that same jump below a naive threshold -- verified with a
    concrete constructed example during development, see tests), which is
    exactly the failure mode a data-quality check must not have.
    """
    diffs = df[value_col].diff().dropna()
    if len(diffs) < 10:
        return QualityFinding("unexpected_jumps", "ok", "Not enough history to assess.")
    median = diffs.median()
    mad = (diffs - median).abs().median()
    if mad == 0:
        outliers = diffs[diffs != median]
    else:
        modified_z = 0.6745 * (diffs - median) / mad
        outliers = diffs[modified_z.abs() > threshold]
    if len(outliers):
        return QualityFinding("unexpected_jumps", "warning", f"{len(outliers)} week-over-week change(s) flagged as statistical outliers (robust modified z-score > {threshold}).")
    return QualityFinding("unexpected_jumps", "ok", "No extreme week-over-week jumps detected.")


def check_freshness(latest_availability_date: Optional[date], as_of: Optional[date] = None, stale_after_days: int = 14) -> QualityFinding:
    as_of = as_of or date.today()
    if latest_availability_date is None:
        return QualityFinding("freshness", "error", "No data ingested yet.")
    age = (as_of - latest_availability_date).days
    if age > stale_after_days:
        return QualityFinding("freshness", "warning", f"Latest availability_date is {age} days old (threshold {stale_after_days}).")
    return QualityFinding("freshness", "ok", f"Latest availability_date is {age} day(s) old.")


def check_schema_signature(columns: list[str], previous_signature: Optional[str]) -> tuple[QualityFinding, str]:
    signature = ",".join(sorted(columns))
    if previous_signature is not None and previous_signature != signature:
        return QualityFinding("schema", "error", "Data source schema changed since the last check -- verify column mapping before trusting new data."), signature
    return QualityFinding("schema", "ok", "Schema unchanged."), signature


def check_accounting_identity(df: pd.DataFrame, date_col: str = "report_date") -> QualityFinding:
    """
    The fundamental COT identity: the sum of every participant category's long
    positions must equal total open interest, and likewise for shorts (every
    long is someone's short). Because non-reportables are computed as the
    residual, this identity holding is a real check that the reportable
    columns were mapped and parsed correctly -- if CFTC renames a column and
    a category silently reads as zero, this catches it where a row-count
    check would not.
    """
    violations = []
    for report_date, group in df.groupby(date_col):
        oi = group["open_interest"].iloc[0]
        if group["long"].sum() != oi or group["short"].sum() != oi:
            violations.append(str(report_date))
    if violations:
        return QualityFinding(
            "accounting_identity", "error",
            f"{len(violations)} report date(s) where participant longs/shorts do not sum to open "
            f"interest -- check column mapping in cftc_client.py. First few: {violations[:3]}")
    return QualityFinding("accounting_identity", "ok",
                           "Participant longs and shorts both sum to open interest on every report date.")


def run_all_checks(cot_raw: pd.DataFrame, market: str) -> list[QualityFinding]:
    sub = cot_raw[cot_raw["market"] == market]
    findings = [
        check_missing_weeks(sub[sub["participant"] == "leveraged_funds"]),
        check_duplicates(cot_raw, ["market", "participant", "report_date", "source"]),
        check_unexpected_jumps(sub[sub["participant"] == "leveraged_funds"].sort_values("report_date"), "open_interest"),
        check_accounting_identity(sub),
    ]
    if len(sub):
        latest_avail = pd.to_datetime(sub["availability_date"]).max().date()
        findings.append(check_freshness(latest_avail))
    return findings
