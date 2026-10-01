"""Statistical process control: control charts and process capability."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .generate import SPEC

MIN_POINTS_PER_DAY = 20


def control_chart(
    hot: pd.DataFrame,
    value_col: str = "leakage_ua",
    baseline_days: int = 10,
    run_length: int = 9,
) -> pd.DataFrame:
    """X-bar chart per station on the daily mean of log(leakage).

    ``hot`` holds individual first-attempt measurements at 125 degC with
    ``station_id`` and ``test_day``. Leakage is roughly log-normal, so the chart
    works on log values. Each day's limits use its own sample size
    (center +/- 3 * sigma / sqrt(n)), so quiet days with few tests do not raise
    false alarms. Center and sigma come from the station's first
    ``baseline_days`` days with at least MIN_POINTS_PER_DAY tests.

    Rules:
      rule 1 (alarm): a daily mean beyond the 3-sigma limits
      rule 2 (warning): ``run_length`` daily means in a row on one side of
      the center. Over 20 simulated months this rule fired on stable stations
      far more often than rule 1, because the center is estimated from only
      ten days, so it is reported as a warning and does not raise the alarm.
    """
    d = hot.dropna(subset=[value_col]).copy()
    d["log_value"] = np.log(d[value_col])
    out = []
    for station, g in d.groupby("station_id"):
        daily = (
            g.groupby("test_day")["log_value"]
            .agg(n="count", mean_log="mean", var_log="var")
            .reset_index()
            .sort_values("test_day")
        )
        daily = daily[daily["n"] >= MIN_POINTS_PER_DAY].reset_index(drop=True)
        if len(daily) <= baseline_days:
            continue
        base = daily.iloc[:baseline_days]
        center = np.average(base["mean_log"], weights=base["n"])
        sigma = np.sqrt(np.average(base["var_log"], weights=base["n"] - 1))  # pooled within-day sd
        half_width = 3 * sigma / np.sqrt(daily["n"])
        daily["station_id"] = station
        daily["center"] = center
        daily["ucl"] = center + half_width
        daily["lcl"] = center - half_width
        daily["rule1"] = (daily["mean_log"] > daily["ucl"]) | (daily["mean_log"] < daily["lcl"])

        side = np.sign(daily["mean_log"] - center).to_numpy()
        run = np.zeros(len(side), dtype=int)
        for i, s in enumerate(side):
            run[i] = run[i - 1] + 1 if i > 0 and s != 0 and s == side[i - 1] else 1
        daily["rule2"] = run >= run_length
        daily["out_of_control"] = daily["rule1"]
        daily["in_baseline"] = np.arange(len(daily)) < baseline_days
        # Back-transform for readable charts (geometric mean in uA)
        for c in ["mean_log", "center", "ucl", "lcl"]:
            daily[c.replace("mean_log", "geo_mean") + "_ua"] = np.exp(daily[c])
        out.append(daily)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def first_alarm(chart: pd.DataFrame) -> pd.DataFrame:
    """First out-of-control day per station (empty for stable stations)."""
    alarms = chart[chart["out_of_control"]]
    return (
        alarms.sort_values("test_day")
        .groupby("station_id", as_index=False)
        .first()[["station_id", "test_day", "rule1", "rule2"]]
    )


def cpk(values: pd.Series, lsl: float | None, usl: float | None) -> float:
    """Process capability index; one-sided if only one limit is given."""
    v = values.dropna()
    mu, sd = v.mean(), v.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    parts = []
    if usl is not None:
        parts.append((usl - mu) / (3 * sd))
    if lsl is not None:
        parts.append((mu - lsl) / (3 * sd))
    return float(min(parts))


def capability_table(first_attempts: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for param, lim in SPEC.items():
        for temp, g in first_attempts.groupby("temperature_c"):
            rows.append(
                {
                    "parameter": param,
                    "temperature_c": temp,
                    "n": int(g[param].notna().sum()),
                    "mean": round(g[param].mean(), 3),
                    "std": round(g[param].std(ddof=1), 3),
                    "lsl": lim["lsl"],
                    "usl": lim["usl"],
                    "cpk": round(cpk(g[param], lim["lsl"], lim["usl"]), 2),
                }
            )
    return pd.DataFrame(rows)
