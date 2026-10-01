"""Rule-based data quality checks for end-of-line test data.

Each rule returns a boolean mask over the rows it flags. ``validate`` runs all
rules and returns a summary table; ``clean`` drops duplicate copies and moves
every other flagged row to a quarantine table with the reasons attached, so
nothing is silently deleted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from .generate import TEMPERATURES

REQUIRED_COLUMNS = [
    "test_id",
    "unit_id",
    "lot_id",
    "wafer_id",
    "temperature_c",
    "station_id",
    "test_ts",
    "supply_current_ma",
    "leakage_ua",
    "max_clock_mhz",
    "vdd_v",
    "bin_code",
    "result",
]
MEASUREMENTS = ["supply_current_ma", "leakage_ua", "max_clock_mhz"]
# Highest physically plausible leakage per temperature insertion (uA).
# Real values sit well below these; values above are almost always unit errors.
MAX_PLAUSIBLE_LEAKAGE_UA = {-40: 2.0, 25: 8.0, 125: 40.0}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    severity: str  # "drop" (safe to remove) or "quarantine" (keep for review)
    description: str
    likely_cause: str
    check: Callable[[pd.DataFrame, Context], pd.Series]


@dataclass(frozen=True)
class Context:
    known_lots: frozenset
    as_of: pd.Timestamp


def check_schema(tests: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in tests.columns]
    if missing:
        raise SchemaError(f"Missing required columns: {missing}")
    if not pd.api.types.is_datetime64_any_dtype(tests["test_ts"]):
        raise SchemaError("test_ts must be a datetime column")


RULES = [
    Rule(
        "R01",
        "duplicate_test_id",
        "drop",
        "Same test_id appears more than once (later copies flagged)",
        "File loaded twice or tester re-sent a record",
        lambda df, ctx: df.duplicated(subset="test_id", keep="first"),
    ),
    Rule(
        "R02",
        "missing_measurement",
        "quarantine",
        "A required measurement is empty",
        "Tester aborted or the value was not logged",
        lambda df, ctx: df[MEASUREMENTS].isna().any(axis=1),
    ),
    Rule(
        "R03",
        "implausible_leakage",
        "quarantine",
        "Leakage above the plausible maximum for its temperature (2 / 8 / 40 uA at -40 / 25 / 125 degC)",
        "Value logged in nA instead of uA",
        lambda df, ctx: df["leakage_ua"] > df["temperature_c"].map(MAX_PLAUSIBLE_LEAKAGE_UA),
    ),
    Rule(
        "R04",
        "invalid_temperature",
        "quarantine",
        f"Temperature is not one of the test insertions {TEMPERATURES}",
        "Chamber sensor glitch or wrong test program",
        lambda df, ctx: ~df["temperature_c"].isin(TEMPERATURES),
    ),
    Rule(
        "R05",
        "future_timestamp",
        "quarantine",
        "Test timestamp lies after the data extract date",
        "Tester clock set wrong",
        lambda df, ctx: df["test_ts"] > ctx.as_of,
    ),
    Rule(
        "R06",
        "bin_result_mismatch",
        "quarantine",
        "Result says PASS but bin is a fail bin, or the other way round",
        "Binning table out of sync with the test program",
        lambda df, ctx: (df["result"] == "PASS") != (df["bin_code"] == 1),
    ),
    Rule(
        "R07",
        "unknown_lot",
        "quarantine",
        "lot_id is not in the lot master data",
        "Typo at lot start or missing master data entry",
        lambda df, ctx: ~df["lot_id"].isin(ctx.known_lots),
    ),
]


def run_rules(tests: pd.DataFrame, lots: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return a boolean frame: one column per rule name, one row per test row."""
    check_schema(tests)
    ctx = Context(known_lots=frozenset(lots["lot_id"]), as_of=pd.Timestamp(as_of))
    return pd.DataFrame({r.name: r.check(tests, ctx).fillna(False).astype(bool) for r in RULES})


def validate(tests: pd.DataFrame, lots: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Summary table: how many rows each rule flags, with example test_ids."""
    flags = run_rules(tests, lots, as_of)
    out = []
    for r in RULES:
        hit = flags[r.name]
        out.append(
            {
                "rule_id": r.rule_id,
                "rule": r.name,
                "action": r.severity,
                "rows_flagged": int(hit.sum()),
                "pct_of_rows": round(100 * hit.mean(), 3),
                "description": r.description,
                "likely_cause": r.likely_cause,
                "examples": ", ".join(tests.loc[hit, "test_id"].head(3)),
            }
        )
    return pd.DataFrame(out)


def clean(tests: pd.DataFrame, lots: pd.DataFrame, as_of: pd.Timestamp):
    """Split rows into clean data and a quarantine table with reasons.

    Returns (clean, quarantine, dropped_duplicate_count).
    """
    flags = run_rules(tests, lots, as_of)
    drop_cols = [r.name for r in RULES if r.severity == "drop"]
    q_cols = [r.name for r in RULES if r.severity == "quarantine"]
    dropped = flags[drop_cols].any(axis=1)
    quarantined = flags[q_cols].any(axis=1) & ~dropped

    reasons = flags[q_cols].apply(lambda row: ";".join(c for c in q_cols if row[c]), axis=1)
    quarantine = tests.loc[quarantined].copy()
    quarantine["reasons"] = reasons[quarantined]
    clean_df = tests.loc[~dropped & ~quarantined].copy()
    return clean_df.reset_index(drop=True), quarantine.reset_index(drop=True), int(dropped.sum())
