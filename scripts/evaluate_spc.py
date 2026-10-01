"""Measure how well the SPC alarm works over many simulated months.

For each seed: generate a month of data, clean it, run the control chart and
record (a) the day the drifting station T3 is first flagged and (b) whether
any of the three stable stations raises a false alarm.

    python scripts/evaluate_spc.py --seeds 20
"""

import argparse
import statistics

import pandas as pd

from mcu_analytics.generate import DRIFT_START_DAY, DRIFT_STATION, START, generate
from mcu_analytics.kpis import load
from mcu_analytics.spc import control_chart
from mcu_analytics.validate import clean


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20)
    n = p.parse_args().seeds

    delays, missed, false_alarm_months, stable_months = [], 0, 0, 0
    for seed in range(n):
        d = generate(seed=seed)
        c, _, _ = clean(d.tests, d.lots, START + pd.Timedelta(days=d.days + 1))
        con = load(c, d.lots)
        hot = pd.read_sql_query(
            "SELECT station_id, test_day, leakage_ua FROM v_attempts WHERE attempt = 1 AND temperature_c = 125",
            con,
        )
        chart = control_chart(hot)
        for station, g in chart.groupby("station_id"):
            alarms = g[g["out_of_control"]]
            if station == DRIFT_STATION:
                if alarms.empty:
                    missed += 1
                else:
                    first = (pd.Timestamp(alarms["test_day"].min()) - START).days
                    delays.append(first - DRIFT_START_DAY)
            else:
                stable_months += 1
                false_alarm_months += int(not alarms.empty)

    print(f"Seeds: {n}")
    print(f"Drift on {DRIFT_STATION} detected: {n - missed}/{n}")
    if delays:
        print(
            f"Days from drift start to first alarm: median {statistics.median(delays)}, range {min(delays)}-{max(delays)}"
        )
    print(f"Stable station-months with at least one false alarm: {false_alarm_months}/{stable_months}")


if __name__ == "__main__":
    main()
