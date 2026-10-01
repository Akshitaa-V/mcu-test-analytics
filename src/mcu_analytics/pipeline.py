"""Run the whole pipeline: generate -> validate -> clean -> load -> KPIs -> SPC -> report -> export.

Usage:
    python -m mcu_analytics.pipeline --out output
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from .generate import START, generate
from .kpis import headline, load, read_kpis
from .report import build_report
from .spc import capability_table, control_chart, first_alarm
from .validate import clean, validate


def run(out_dir: str | Path = "output", seed: int = 7) -> dict:
    t0 = time.perf_counter()
    out = Path(out_dir)
    (out / "tableau").mkdir(parents=True, exist_ok=True)

    data = generate(seed=seed)
    as_of = START + pd.Timedelta(days=data.days + 1)

    quality = validate(data.tests, data.lots, as_of)
    clean_df, quarantine, dropped = clean(data.tests, data.lots, as_of)

    con = load(clean_df, data.lots, out / "mcu_tests.db")
    kpis = read_kpis(con)
    first = pd.read_sql_query("SELECT * FROM v_attempts WHERE attempt = 1", con)
    chart = control_chart(first[first["temperature_c"] == 125])
    alarms = first_alarm(chart)
    capability = capability_table(first)

    summary = {
        "seed": seed,
        "rows_in": len(data.tests),
        "duplicates_dropped": dropped,
        "rows_quarantined": len(quarantine),
        "rows_clean": len(clean_df),
        "issues_flagged_by_rule": dict(zip(quality["rule"], quality["rows_flagged"].astype(int))),
        "period_start": str(data.tests["test_ts"].min().date()),
        "period_end": str(clean_df["test_ts"].max().date()),
        **headline(con),
        "spc_alarms": alarms.to_dict("records"),
    }

    build_report(summary, quality, kpis, chart, alarms, capability, out / "report.html")

    # Tidy CSVs for Tableau (or any BI tool)
    tb = out / "tableau"
    pd.read_sql_query(
        """
        SELECT a.test_id, a.unit_id, a.lot_id, a.wafer_id, a.product, a.station_id,
               a.temperature_c, a.test_ts, a.test_day, a.attempt,
               a.supply_current_ma, a.leakage_ua, a.max_clock_mhz, a.vdd_v,
               a.bin_code, b.bin_name, a.result
        FROM v_attempts AS a JOIN bins AS b USING (bin_code)
        """,
        con,
    ).to_csv(tb / "test_results.csv", index=False)
    kpis["v_lot_yield"].to_csv(tb / "lot_yield.csv", index=False)
    kpis["v_station_daily"].to_csv(tb / "station_daily.csv", index=False)
    kpis["v_bin_pareto"].to_csv(tb / "bin_pareto.csv", index=False)
    chart.to_csv(tb / "spc_hot_leakage.csv", index=False)
    quality.to_csv(tb / "data_quality.csv", index=False)
    quarantine.to_csv(out / "quarantine.csv", index=False)
    capability.to_csv(out / "capability.csv", index=False)
    con.close()

    summary["runtime_s"] = round(time.perf_counter() - t0, 2)
    (out / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description="MCU end-of-line test analytics pipeline")
    p.add_argument("--out", default="output", help="output folder")
    p.add_argument("--seed", type=int, default=7, help="random seed for the synthetic data")
    args = p.parse_args()
    s = run(args.out, args.seed)
    print(
        f"Rows in: {s['rows_in']:,} | duplicates dropped: {s['duplicates_dropped']} | "
        f"quarantined: {s['rows_quarantined']} | clean: {s['rows_clean']:,}"
    )
    print(
        f"Units: {s['units']:,} | first-pass yield {s['first_pass_yield_pct']} % | "
        f"final yield {s['final_yield_pct']} %"
    )
    alarms = ", ".join(f"{a['station_id']} from {a['test_day']}" for a in s["spc_alarms"]) or "none"
    print(f"SPC alarms: {alarms}")
    print(f"Report: {Path(args.out) / 'report.html'}  ({s['runtime_s']} s)")


if __name__ == "__main__":
    main()
