# Building the Tableau dashboard

The pipeline writes tidy CSVs to `output/tableau/`. This guide builds a one-page yield and quality dashboard on them in **Tableau Public** (free). Once it's published, add the link to the README under "Dashboard".

## 0. Get the data

```bash
mcu-analytics --out output
```

## 1. Install and connect

1. Download Tableau Public from public.tableau.com and create a free account.
2. Open it, choose **Connect > Text file**, and pick `output/tableau/test_results.csv`.
3. In the data source tab, check the types: `test_ts` should be Date & Time, `test_day` Date, `temperature_c` a Number (whole). Right-click `temperature_c` and `bin_code` and choose **Convert to Dimension**.
4. Add `lot_yield.csv`, `station_daily.csv`, `bin_pareto.csv` and `spc_hot_leakage.csv` as separate data sources (Data > New Data Source). Keeping them separate is simpler than joining them.

## 2. Calculated fields (on `test_results`)

Create these with Analysis > Create Calculated Field:

- `Is Pass` = `IF [result] = "PASS" THEN 1 ELSE 0 END`
- `First Attempt` = `[attempt] = 1`
- `First-Attempt Pass Rate` = `SUM(IF [attempt] = 1 THEN [Is Pass] END) / SUM(IF [attempt] = 1 THEN 1 END)` (format as percentage)

## 3. Five sheets

| Sheet | Source | How |
|---|---|---|
| KPI tiles | test_results | Text marks: `COUNTD([unit_id])`, `First-Attempt Pass Rate`, failed tests. One sheet per tile, or Measure Names / Measure Values. |
| Pass rate by station over time | station_daily | Columns `test_day` (exact date, continuous), Rows `pass_rate_7d_pct`, Color `station_id`. |
| Fail-bin Pareto | bin_pareto | Bars: `bin_name` sorted by `fails` descending. Dual axis with `cumulative_pct` as a line, synchronise off, right axis 0 to 100. |
| Hot leakage control chart | spc_hot_leakage | Columns `test_day`, Rows `geo_mean_ua`, Filter `station_id`. Add `ucl_ua` and `lcl_ua` on a shared axis as dashed lines, Color the points by `out_of_control`. |
| Lot yield table | lot_yield | Rows `lot_id`, `product`; text `first_pass_yield_pct`, `final_yield_pct`; sort ascending so the worst lots come first. |

## 4. Dashboard

1. New dashboard, size Automatic or 1200 x 800.
2. KPI tiles across the top, the control chart and pass-rate trend in the middle, Pareto and lot table at the bottom.
3. Add a `station_id` filter and choose **Apply to worksheets > All using related data sources** where it fits.
4. Add a short text box: "Synthetic data. T3 leakage drift starts on day 18 and is flagged by the control chart."
5. **File > Save to Tableau Public**. Copy the link into the README and your CV.

## 5. What to be ready to explain

- Why the pass-rate trend uses a 7-day rolling average, and where it is computed (SQL window function, `v_station_daily`).
- Why the control limits are not straight lines (they depend on each day's sample size).
- Why quarantined rows are not in the dashboard, and where to find them.
