-- KPI views over the cleaned test data (SQLite, needs window function support).
-- Tables expected: tests (cleaned rows), lots, bins.

DROP VIEW IF EXISTS v_attempts;
CREATE VIEW v_attempts AS
SELECT
    t.*,
    l.product,
    date(t.test_ts) AS test_day,
    ROW_NUMBER() OVER (PARTITION BY t.unit_id, t.temperature_c ORDER BY t.test_ts) AS attempt,
    COUNT(*)     OVER (PARTITION BY t.unit_id, t.temperature_c)                    AS n_attempts
FROM tests AS t
JOIN lots  AS l USING (lot_id);

-- One row per unit and temperature insertion: did it pass first time, and in the end?
DROP VIEW IF EXISTS v_unit_insertion;
CREATE VIEW v_unit_insertion AS
SELECT
    unit_id, lot_id, product, temperature_c,
    MAX(CASE WHEN attempt = 1          THEN result = 'PASS' END) AS first_pass,
    MAX(CASE WHEN attempt = n_attempts THEN result = 'PASS' END) AS final_pass,
    MAX(n_attempts) AS attempts
FROM v_attempts
GROUP BY unit_id, lot_id, product, temperature_c;

-- A unit passes only if every insertion it was tested at passes.
DROP VIEW IF EXISTS v_unit;
CREATE VIEW v_unit AS
SELECT
    unit_id, lot_id, product,
    MIN(first_pass) AS first_pass,
    MIN(final_pass) AS final_pass,
    COUNT(*)        AS insertions_tested
FROM v_unit_insertion
GROUP BY unit_id, lot_id, product;

DROP VIEW IF EXISTS v_lot_yield;
CREATE VIEW v_lot_yield AS
SELECT
    lot_id, product,
    COUNT(*)                          AS units,
    ROUND(100.0 * AVG(first_pass), 2) AS first_pass_yield_pct,
    ROUND(100.0 * AVG(final_pass), 2) AS final_yield_pct,
    ROUND(100.0 * (AVG(final_pass) - AVG(first_pass)), 2) AS recovered_by_retest_pct
FROM v_unit
GROUP BY lot_id, product;

DROP VIEW IF EXISTS v_yield_by_temperature;
CREATE VIEW v_yield_by_temperature AS
SELECT
    temperature_c,
    COUNT(*)                          AS insertions,
    ROUND(100.0 * AVG(first_pass), 2) AS first_pass_yield_pct,
    ROUND(100.0 * AVG(final_pass), 2) AS final_yield_pct
FROM v_unit_insertion
GROUP BY temperature_c;

-- Daily first-attempt pass rate per station with a 7-day rolling average,
-- plus the daily mean hot (125 degC) leakage used for SPC.
DROP VIEW IF EXISTS v_station_daily;
CREATE VIEW v_station_daily AS
WITH daily AS (
    SELECT
        station_id, test_day,
        COUNT(*)                     AS tests,
        AVG(result = 'PASS')         AS pass_rate,
        AVG(CASE WHEN temperature_c = 125 THEN leakage_ua END) AS mean_hot_leakage_ua,
        SUM(temperature_c = 125)     AS hot_tests
    FROM v_attempts
    WHERE attempt = 1
    GROUP BY station_id, test_day
)
SELECT
    station_id, test_day, tests, hot_tests,
    ROUND(100.0 * pass_rate, 2) AS pass_rate_pct,
    ROUND(100.0 * AVG(pass_rate) OVER (
        PARTITION BY station_id ORDER BY test_day
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW), 2) AS pass_rate_7d_pct,
    ROUND(mean_hot_leakage_ua, 4) AS mean_hot_leakage_ua
FROM daily;

-- Fail bins ranked, with share and cumulative share (Pareto)
DROP VIEW IF EXISTS v_bin_pareto;
CREATE VIEW v_bin_pareto AS
WITH f AS (
    SELECT a.bin_code, b.bin_name, COUNT(*) AS fails
    FROM v_attempts AS a
    JOIN bins AS b USING (bin_code)
    WHERE a.result = 'FAIL'
    GROUP BY a.bin_code, b.bin_name
)
SELECT
    bin_code, bin_name, fails,
    ROUND(100.0 * fails / SUM(fails) OVER (), 2) AS share_pct,
    ROUND(100.0 * SUM(fails) OVER (ORDER BY fails DESC ROWS UNBOUNDED PRECEDING)
          / SUM(fails) OVER (), 2) AS cumulative_pct
FROM f
ORDER BY fails DESC;
