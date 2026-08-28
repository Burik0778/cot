"""
src/data/export.py

Spec sections 33, 48. CSV/JSON/Excel have zero optional dependencies beyond
what's already required (pandas + openpyxl). Parquet requires pyarrow (or
fastparquet); if neither is installed, `to_parquet_bytes` raises a clear
ImportError-derived message rather than silently writing CSV and calling
it Parquet.
"""
from __future__ import annotations
import io
import json
import pandas as pd


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def to_json_bytes(df: pd.DataFrame) -> bytes:
    return df.to_json(orient="records", date_format="iso", default_handler=str).encode("utf-8")


def to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Data") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


class ParquetUnavailable(RuntimeError):
    pass


def to_parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    try:
        df.to_parquet(buf, index=False)
    except ImportError as e:
        raise ParquetUnavailable(
            "Parquet export requires the 'pyarrow' package, which is not installed "
            "in this environment. Install it (`pip install pyarrow`) and retry -- "
            "this function does not fall back to a different format silently."
        ) from e
    return buf.getvalue()
