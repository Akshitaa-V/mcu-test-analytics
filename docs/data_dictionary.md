# Data dictionary

## Raw test rows (`tests`, before cleaning)

| Column | Type | Meaning |
|---|---|---|
| test_id | text | One test of one unit at one temperature. Unique in clean data. |
| unit_id | text | Device, `<lot>-W<wafer>-U<unit>` |
| lot_id | text | Production lot, must exist in `lots` |
| wafer_id | text | Wafer within the lot |
| temperature_c | int | Test insertion: -40, 25 or 125 degC |
| station_id | text | Tester T1 to T4 |
| test_ts | datetime | When the test ran |
| supply_current_ma | float | Supply current, spec 18 to 32 mA |
| leakage_ua | float | Leakage current in uA, spec at most 5 uA |
| max_clock_mhz | float | Highest passing clock, spec at least 300 MHz |
| vdd_v | float | Supply voltage during the test (informational) |
| bin_code | int | 1 pass, 2 supply current, 3 leakage, 4 clock (first failing test wins) |
| result | text | PASS or FAIL, must agree with bin_code |

## Lots (`lots`)

| Column | Meaning |
|---|---|
| lot_id | Lot identifier |
| product | MCU-A32 or MCU-B64 (placeholder names) |
| fab_out_date | Date the lot left the fab |

## Views and exports

| View / file | Grain | Key columns |
|---|---|---|
| `v_attempts` / `tableau/test_results.csv` | one test | `attempt` (1 = first test of that unit at that temperature), `n_attempts`, `test_day`, `product`, `bin_name` |
| `v_unit_insertion` | unit x temperature | `first_pass`, `final_pass` (last attempt), `attempts` |
| `v_unit` | unit | passes only if every tested insertion passes |
| `v_lot_yield` / `lot_yield.csv` | lot | `first_pass_yield_pct`, `final_yield_pct`, `recovered_by_retest_pct` |
| `v_yield_by_temperature` | temperature | first-pass and final yield |
| `v_station_daily` / `station_daily.csv` | station x day | first-attempt `pass_rate_pct`, `pass_rate_7d_pct`, `mean_hot_leakage_ua` |
| `v_bin_pareto` / `bin_pareto.csv` | fail bin | `fails`, `share_pct`, `cumulative_pct` |
| `spc_hot_leakage.csv` | station x day | `geo_mean_ua`, `center_ua`, `ucl_ua`, `lcl_ua`, `out_of_control`, `rule2` (warning) |
| `data_quality.csv` | rule | `rows_flagged`, `action`, `likely_cause` |
| `quarantine.csv` | test | original row plus `reasons` |

## Definitions

- **First-pass yield**: share of units that passed every insertion on the first attempt.
- **Final yield**: share of units whose last attempt passed at every insertion they were tested at.
- **Recovered by retest**: final yield minus first-pass yield.
- **Cpk**: distance from the mean to the nearest spec limit in units of 3 standard deviations; 1.33 is a common minimum.
