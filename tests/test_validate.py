import pandas as pd
import pytest

from mcu_analytics.generate import INJECTED_COUNTS, START, generate
from mcu_analytics.validate import SchemaError, clean, validate


@pytest.fixture(scope="module")
def data():
    return generate(seed=7)


def as_of(d):
    return START + pd.Timedelta(days=d.days + 1)


def test_generation_is_reproducible():
    a, b = generate(seed=3), generate(seed=3)
    pd.testing.assert_frame_equal(a.tests, b.tests)


def test_every_unit_tested_at_three_temperatures():
    d = generate(seed=1, inject_issues=False)
    per_unit = d.tests.groupby("unit_id")["temperature_c"].nunique()
    assert (per_unit == 3).all()
    assert len(per_unit) == 40 * 5 * 60


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_each_rule_finds_exactly_the_injected_rows(seed):
    d = generate(seed=seed)
    found = validate(d.tests, d.lots, as_of(d)).set_index("rule")["rows_flagged"]
    expected = d.truth["issue"].value_counts()
    for rule, n in found.items():
        assert n == expected.get(rule, 0), rule


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_flagged_rows_are_the_injected_ones(seed):
    d = generate(seed=seed)
    _, quarantine, _ = clean(d.tests, d.lots, as_of(d))
    injected = set(d.truth.loc[d.truth["issue"] != "duplicate_test_id", "test_id"])
    assert set(quarantine["test_id"]) == injected


def test_clean_data_raises_no_flags():
    d = generate(seed=5, inject_issues=False)
    assert validate(d.tests, d.lots, as_of(d))["rows_flagged"].sum() == 0


def test_clean_keeps_every_row_somewhere(data):
    c, q, dropped = clean(data.tests, data.lots, as_of(data))
    assert len(c) + len(q) + dropped == len(data.tests)
    assert dropped == INJECTED_COUNTS["duplicate_test_id"]
    assert c["test_id"].is_unique
    assert q["reasons"].str.len().gt(0).all()


def test_missing_column_raises(data):
    with pytest.raises(SchemaError):
        validate(data.tests.drop(columns=["leakage_ua"]), data.lots, as_of(data))
