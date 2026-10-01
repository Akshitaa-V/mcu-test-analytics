"""Load cleaned data into SQLite and read the KPI views."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

import pandas as pd

from .generate import BINS

VIEWS = [
    "v_lot_yield",
    "v_yield_by_temperature",
    "v_station_daily",
    "v_bin_pareto",
]


def load(clean: pd.DataFrame, lots: pd.DataFrame, db_path: str | Path = ":memory:") -> sqlite3.Connection:
    """Write tables and create the KPI views. Returns an open connection."""
    con = sqlite3.connect(str(db_path))
    tests = clean.copy()
    tests["test_ts"] = tests["test_ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    tests.to_sql("tests", con, if_exists="replace", index=False)
    lots.astype({"fab_out_date": str}).to_sql("lots", con, if_exists="replace", index=False)
    BINS.to_sql("bins", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_tests_unit ON tests(unit_id, temperature_c, test_ts)")
    sql = resources.files("mcu_analytics").joinpath("sql/kpis.sql").read_text()
    con.executescript(sql)
    con.commit()
    return con


def read_kpis(con: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    return {v: pd.read_sql_query(f"SELECT * FROM {v}", con) for v in VIEWS}


def headline(con: sqlite3.Connection) -> dict[str, float]:
    row = con.execute(
        """
        SELECT COUNT(*),
               ROUND(100.0 * AVG(first_pass), 2),
               ROUND(100.0 * AVG(final_pass), 2)
        FROM v_unit
        """
    ).fetchone()
    return {"units": row[0], "first_pass_yield_pct": row[1], "final_yield_pct": row[2]}
