import numpy as np
import pandas as pd
import pytest

from mcu_analytics.generate import START, generate
from mcu_analytics.kpis import headline, load, read_kpis
from mcu_analytics.validate import clean


def _row(test_id, unit, temp, ts, result, station="T1", lot="L001"):
    return {
        "test_id": test_id,
        "unit_id": unit,
        "lot_id": lot,
        "wafer_id": f"{lot}-W01",
        "temperature_c": temp,
        "station_id": station,
        "test_ts": pd.Timestamp(ts),
        "supply_current_ma": 25.0,
        "leakage_ua": 1.0,
        "max_clock_mhz": 330.0,
        "vdd_v": 3.3,
        "bin_code": 1 if result == "PASS" else 2,
        "result": result,
    }


@pytest.fixture
def tiny():
    lots = pd.DataFrame({"lot_id": ["L001"], "product": ["MCU-A32"], "fab_out_date": ["2026-07-01"]})
    rows = [
        # unit A passes everything first time
        _row("t1", "A", 25, "2026-08-01 08:00", "PASS"),
        _row("t2", "A", 125, "2026-08-01 09:00", "PASS"),
        # unit B fails hot first time, passes on retest
        _row("t3", "B", 25, "2026-08-01 08:00", "PASS"),
        _row("t4", "B", 125, "2026-08-01 09:00", "FAIL"),
        _row("t5", "B", 125, "2026-08-01 12:00", "PASS", station="T2"),
        # unit C fails hot and the retest fails too
        _row("t6", "C", 25, "2026-08-02 08:00", "PASS"),
        _row("t7", "C", 125, "2026-08-02 09:00", "FAIL"),
        _row("t8", "C", 125, "2026-08-02 13:00", "FAIL", station="T3"),
        # unit D only has a cold insertion, which fails
        _row("t9", "D", 25, "2026-08-02 08:00", "FAIL"),
    ]
    return load(pd.DataFrame(rows), lots)


def test_first_pass_and_final_yield(tiny):
    h = headline(tiny)
    assert h["units"] == 4
    assert h["first_pass_yield_pct"] == 25.0  # only A
    assert h["final_yield_pct"] == 50.0  # A and B


def test_attempt_numbering_uses_timestamps(tiny):
    att = pd.read_sql_query("SELECT test_id, attempt FROM v_attempts ORDER BY test_id", tiny)
    assert dict(zip(att.test_id, att.attempt))["t5"] == 2
    assert dict(zip(att.test_id, att.attempt))["t4"] == 1


def test_lot_yield_recovered_by_retest(tiny):
    lot = read_kpis(tiny)["v_lot_yield"].iloc[0]
    assert lot["recovered_by_retest_pct"] == 25.0


def test_pareto_shares_add_up(tiny):
    p = read_kpis(tiny)["v_bin_pareto"]
    assert p["share_pct"].sum() == pytest.approx(100.0)
    assert p["cumulative_pct"].iloc[-1] == pytest.approx(100.0)


def test_rolling_average_window_is_seven_days():
    lots = pd.DataFrame({"lot_id": ["L001"], "product": ["MCU-A32"], "fab_out_date": ["2026-07-01"]})
    rows = []
    for day in range(10):
        result = "FAIL" if day == 0 else "PASS"  # only day 0 fails
        rows.append(_row(f"t{day}", f"U{day}", 25, START + pd.Timedelta(days=day, hours=8), result))
    daily = read_kpis(load(pd.DataFrame(rows), lots))["v_station_daily"].sort_values("test_day")
    rolling = daily["pass_rate_7d_pct"].to_numpy()
    assert rolling[0] == 0.0
    assert rolling[6] == pytest.approx(100 * 6 / 7, abs=0.01)  # day 0 still in the window
    assert rolling[7] == 100.0  # day 0 has dropped out


def test_kpis_on_generated_data_are_sane():
    d = generate(seed=7)
    c, _, _ = clean(d.tests, d.lots, START + pd.Timedelta(days=d.days + 1))
    h = headline(load(c, d.lots))
    assert 80 < h["first_pass_yield_pct"] < h["final_yield_pct"] < 100
    assert np.isclose(h["units"], 12000)
