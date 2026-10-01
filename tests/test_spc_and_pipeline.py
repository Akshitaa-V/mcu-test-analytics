import json

import numpy as np
import pandas as pd
import pytest

from mcu_analytics.generate import DRIFT_START_DAY, START
from mcu_analytics.pipeline import run
from mcu_analytics.spc import control_chart, cpk, first_alarm


def test_cpk_two_sided_and_one_sided():
    v = pd.Series([9.0, 10.0, 11.0] * 100)
    sd = v.std(ddof=1)
    assert cpk(v, 7.0, 13.0) == pytest.approx(3 / (3 * sd))
    assert cpk(v, None, 12.0) == pytest.approx(2 / (3 * sd))
    assert cpk(v, 9.5, None) == pytest.approx(0.5 / (3 * sd))


def _hot(days, shift_from=None, shift=0.0, n=60, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(days):
        mu = np.log(2.0) + (shift if shift_from is not None and d >= shift_from else 0.0)
        for v in np.exp(rng.normal(mu, 0.5, n)):
            rows.append(
                {"station_id": "T9", "test_day": str((START + pd.Timedelta(days=d)).date()), "leakage_ua": v}
            )
    return pd.DataFrame(rows)


def test_control_chart_catches_a_shift():
    chart = control_chart(_hot(25, shift_from=15, shift=0.4))
    alarm = first_alarm(chart)
    assert len(alarm) == 1
    assert alarm["test_day"].iloc[0] >= str((START + pd.Timedelta(days=15)).date())


def test_control_chart_quiet_on_stable_process():
    assert first_alarm(control_chart(_hot(25, seed=1))).empty


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    return out, run(out, seed=7)


def test_pipeline_writes_everything(outputs):
    out, _ = outputs
    for f in [
        "report.html",
        "run_summary.json",
        "quarantine.csv",
        "mcu_tests.db",
        "tableau/test_results.csv",
        "tableau/lot_yield.csv",
        "tableau/station_daily.csv",
        "tableau/bin_pareto.csv",
        "tableau/spc_hot_leakage.csv",
        "tableau/data_quality.csv",
    ]:
        assert (out / f).exists(), f
    html = (out / "report.html").read_text()
    for section in ["Data quality", "Yield", "Pareto", "Process control", "Process capability"]:
        assert section in html


def test_drifting_station_is_caught_after_drift_starts(outputs):
    out, summary = outputs
    t3 = [a for a in summary["spc_alarms"] if a["station_id"] == "T3"]
    assert t3, "T3 drift not detected"
    assert pd.Timestamp(t3[0]["test_day"]) >= START + pd.Timedelta(days=DRIFT_START_DAY)
    assert json.loads((out / "run_summary.json").read_text())["units"] == 12000


def test_tableau_extract_has_only_clean_rows(outputs):
    out, summary = outputs
    df = pd.read_csv(out / "tableau/test_results.csv")
    assert len(df) == summary["rows_clean"]
    assert df["test_id"].is_unique
    assert set(df["temperature_c"]) == {-40, 25, 125}
