"""Synthetic end-of-line test data for automotive microcontrollers.

Every unit is tested at three temperature insertions (-40, 25 and 125 degC),
as is common for automotive-grade parts. Failing units may be retested once.

When ``inject_issues`` is True, a fixed number of rows get known data problems
(duplicates, missing values, a unit error, invalid temperatures, future
timestamps, inconsistent bins, unknown lots). The validator in ``validate.py``
must find exactly these. Station T3 also gets a slow upward drift in hot
leakage from day 18 on. That drift is a *process* problem, not a data error,
and should be caught by the SPC checks in ``spc.py``, not by the validator.

All data is synthetic. Product names are placeholders.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

PRODUCTS = ["MCU-A32", "MCU-B64"]
STATIONS = ["T1", "T2", "T3", "T4"]
TEMPERATURES = [-40, 25, 125]
START = pd.Timestamp("2026-08-01")

# Specification limits (synthetic)
SPEC = {
    "supply_current_ma": {"lsl": 18.0, "usl": 32.0},
    "leakage_ua": {"lsl": None, "usl": 5.0},
    "max_clock_mhz": {"lsl": 300.0, "usl": None},
}

BINS = pd.DataFrame(
    {
        "bin_code": [1, 2, 3, 4],
        "bin_name": ["Pass", "Supply current out of spec", "Leakage too high", "Clock below spec"],
    }
)

# How many rows of each problem are injected
INJECTED_COUNTS = {
    "duplicate_test_id": 280,
    "missing_measurement": 180,
    "implausible_leakage": 0,  # set from the actual rows of the unit-error day
    "invalid_temperature": 30,
    "future_timestamp": 20,
    "bin_result_mismatch": 25,
    "unknown_lot": 15,
}

DRIFT_STATION = "T3"
DRIFT_START_DAY = 18
DRIFT_PER_DAY = 0.04  # +4 % hot leakage per day after DRIFT_START_DAY
UNIT_ERROR_STATION = "T2"
UNIT_ERROR_DAY = 10  # leakage logged in nA instead of uA on this day


@dataclass
class GeneratedData:
    lots: pd.DataFrame
    tests: pd.DataFrame
    truth: pd.DataFrame  # one row per injected problem: test_id, issue
    days: int


def _measure(rng: np.random.Generator, temps: np.ndarray, products: np.ndarray) -> dict:
    n = len(temps)
    product_offset = np.where(products == "MCU-B64", 1.0, 0.0)
    supply = rng.normal(25.0 + 0.02 * (temps - 25) + product_offset, 2.5, n)
    median_leak = np.select([temps == -40, temps == 25], [0.1, 0.4], default=2.0)
    leakage = median_leak * rng.lognormal(0.0, 0.5, n)
    clock = rng.normal(330.0 - 0.1 * (temps - 25), 10.0, n)
    vdd = rng.normal(3.3, 0.01, n)
    return {
        "supply_current_ma": supply,
        "leakage_ua": leakage,
        "max_clock_mhz": clock,
        "vdd_v": vdd,
    }


def assign_bins(df: pd.DataFrame) -> pd.DataFrame:
    """Set bin_code and result from the measurements (first failing test wins)."""
    s = SPEC
    supply_fail = (df["supply_current_ma"] < s["supply_current_ma"]["lsl"]) | (
        df["supply_current_ma"] > s["supply_current_ma"]["usl"]
    )
    leak_fail = df["leakage_ua"] > s["leakage_ua"]["usl"]
    clock_fail = df["max_clock_mhz"] < s["max_clock_mhz"]["lsl"]
    df["bin_code"] = np.select([supply_fail, leak_fail, clock_fail], [2, 3, 4], default=1)
    df["result"] = np.where(df["bin_code"] == 1, "PASS", "FAIL")
    return df


def _apply_drift(df: pd.DataFrame) -> pd.DataFrame:
    day = (df["test_ts"] - START).dt.days
    mask = (df["station_id"] == DRIFT_STATION) & (df["temperature_c"] == 125) & (day >= DRIFT_START_DAY)
    factor = 1 + DRIFT_PER_DAY * (day[mask] - DRIFT_START_DAY + 1)
    df.loc[mask, "leakage_ua"] = df.loc[mask, "leakage_ua"] * factor
    return df


def generate(
    n_lots: int = 40,
    wafers_per_lot: int = 5,
    units_per_wafer: int = 60,
    days: int = 30,
    retest_probability: float = 0.7,
    seed: int = 7,
    inject_issues: bool = True,
) -> GeneratedData:
    rng = np.random.default_rng(seed)

    lots = pd.DataFrame(
        {
            "lot_id": [f"L{i:03d}" for i in range(1, n_lots + 1)],
            "product": rng.choice(PRODUCTS, n_lots),
            "start_day": rng.integers(0, days - 2, n_lots),
        }
    )
    lots["fab_out_date"] = (START + pd.to_timedelta(lots["start_day"] - 14, unit="D")).dt.date

    # One row per unit and temperature insertion
    rows = []
    for lot in lots.itertuples():
        for w in range(1, wafers_per_lot + 1):
            for u in range(1, units_per_wafer + 1):
                unit_id = f"{lot.lot_id}-W{w:02d}-U{u:03d}"
                for t in TEMPERATURES:
                    rows.append(
                        (unit_id, lot.lot_id, f"{lot.lot_id}-W{w:02d}", t, lot.product, lot.start_day)
                    )
    first = pd.DataFrame(
        rows, columns=["unit_id", "lot_id", "wafer_id", "temperature_c", "product", "start_day"]
    )
    n = len(first)
    first["station_id"] = rng.choice(STATIONS, n)
    hours = rng.uniform(0, 48, n)
    first["test_ts"] = (
        START + pd.to_timedelta(first["start_day"], unit="D") + pd.to_timedelta(hours, unit="h")
    )
    for col, values in _measure(rng, first["temperature_c"].to_numpy(), first["product"].to_numpy()).items():
        first[col] = values
    first = _apply_drift(first)
    first = assign_bins(first)

    # Retest a share of failing insertions once, on a different station, a few hours later
    fails = first[first["result"] == "FAIL"]
    retest = fails[rng.random(len(fails)) < retest_probability].copy()
    retest["station_id"] = [rng.choice([s for s in STATIONS if s != st]) for st in retest["station_id"]]
    retest["test_ts"] = retest["test_ts"] + pd.to_timedelta(rng.uniform(1, 6, len(retest)), unit="h")
    for col, values in _measure(
        rng, retest["temperature_c"].to_numpy(), retest["product"].to_numpy()
    ).items():
        retest[col] = values
    retest = _apply_drift(retest)
    retest = assign_bins(retest)

    tests = pd.concat([first, retest], ignore_index=True)
    tests = tests.sort_values("test_ts", kind="stable").reset_index(drop=True)
    tests.insert(0, "test_id", [f"T{i:07d}" for i in range(1, len(tests) + 1)])
    tests = tests.drop(columns=["product", "start_day"])
    tests[["supply_current_ma", "leakage_ua", "max_clock_mhz", "vdd_v"]] = tests[
        ["supply_current_ma", "leakage_ua", "max_clock_mhz", "vdd_v"]
    ].round(4)

    truth_rows: list[tuple[str, str]] = []
    if inject_issues:
        tests, truth_rows = _inject(tests, rng, days)

    lots = lots.drop(columns=["start_day"])
    truth = pd.DataFrame(truth_rows, columns=["test_id", "issue"])
    return GeneratedData(lots=lots, tests=tests, truth=truth, days=days)


def _inject(tests: pd.DataFrame, rng: np.random.Generator, days: int):
    tests = tests.copy()
    truth: list[tuple[str, str]] = []
    day = (tests["test_ts"] - START).dt.days

    # Unit error: one station logs leakage in nA for a whole day
    unit_err = tests.index[(tests["station_id"] == UNIT_ERROR_STATION) & (day == UNIT_ERROR_DAY)]
    tests.loc[unit_err, "leakage_ua"] = (tests.loc[unit_err, "leakage_ua"] * 1000).round(1)
    truth += [(tid, "implausible_leakage") for tid in tests.loc[unit_err, "test_id"]]

    # Pick disjoint rows for the other issues, away from the unit-error rows
    pool = rng.permutation(tests.index.difference(unit_err).to_numpy())
    pos = 0

    def take(k: int) -> np.ndarray:
        nonlocal pos
        idx = pool[pos : pos + k]
        pos += k
        return idx

    idx = take(INJECTED_COUNTS["missing_measurement"])
    cols = rng.choice(["supply_current_ma", "leakage_ua", "max_clock_mhz"], len(idx))
    for i, c in zip(idx, cols):
        tests.loc[i, c] = np.nan
    truth += [(tid, "missing_measurement") for tid in tests.loc[idx, "test_id"]]

    idx = take(INJECTED_COUNTS["invalid_temperature"])
    tests.loc[idx, "temperature_c"] = 250
    truth += [(tid, "invalid_temperature") for tid in tests.loc[idx, "test_id"]]

    idx = take(INJECTED_COUNTS["future_timestamp"])
    tests.loc[idx, "test_ts"] = tests.loc[idx, "test_ts"] + pd.DateOffset(years=5)
    truth += [(tid, "future_timestamp") for tid in tests.loc[idx, "test_id"]]

    idx = take(INJECTED_COUNTS["bin_result_mismatch"])
    idx = [i for i in idx]
    for i in idx:
        if tests.loc[i, "result"] == "PASS":
            tests.loc[i, "bin_code"] = 3
        else:
            tests.loc[i, "result"] = "PASS"
    truth += [(tid, "bin_result_mismatch") for tid in tests.loc[idx, "test_id"]]

    idx = take(INJECTED_COUNTS["unknown_lot"])
    tests.loc[idx, "lot_id"] = "L999"
    truth += [(tid, "unknown_lot") for tid in tests.loc[idx, "test_id"]]

    # Exact duplicate rows (e.g. a file uploaded twice), copied from untouched rows
    idx = take(INJECTED_COUNTS["duplicate_test_id"])
    dups = tests.loc[idx]
    truth += [(tid, "duplicate_test_id") for tid in dups["test_id"]]
    tests = pd.concat([tests, dups], ignore_index=True)
    tests = tests.sample(frac=1.0, random_state=int(rng.integers(0, 2**31 - 1))).reset_index(drop=True)
    return tests, truth
