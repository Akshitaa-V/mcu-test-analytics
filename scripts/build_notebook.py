"""Build notebooks/exploration.ipynb. Run with:  python scripts/build_notebook.py
Then execute it:  jupyter nbconvert --to notebook --execute --inplace notebooks/exploration.ipynb
"""

from pathlib import Path

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell

cells = [
    md(
        "# Exploring MCU end-of-line test data\n\n"
        "This notebook walks through the same steps as the pipeline, one at a time, "
        "and asks one question at the end: **is the rise in hot leakage on station T3 a data "
        "problem or a process problem?**\n\n"
        "All data is synthetic (see `src/mcu_analytics/generate.py`)."
    ),
    code(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path.cwd().parent / 'src'))\n\n"
        "import numpy as np\nimport pandas as pd\nimport matplotlib.pyplot as plt\n\n"
        "from mcu_analytics.generate import generate, START, SPEC\n"
        "from mcu_analytics.validate import validate, clean\n"
        "from mcu_analytics.kpis import load, read_kpis, headline\n"
        "from mcu_analytics.spc import control_chart, first_alarm, capability_table\n\n"
        "pd.set_option('display.width', 140)\n"
        "data = generate(seed=7)\n"
        "as_of = START + pd.Timedelta(days=data.days + 1)\n"
        "print(f'{len(data.tests):,} test rows, {data.tests.unit_id.nunique():,} units, {len(data.lots)} lots')\n"
        "data.tests.head()"
    ),
    md(
        "## 1. First look at the raw data\n\nSummary statistics already hint at problems: look at the maximum leakage and the temperature values."
    ),
    code("data.tests.describe().T[['count', 'mean', 'min', '50%', 'max']].round(3)"),
    code("data.tests['temperature_c'].value_counts().sort_index()"),
    md(
        "## 2. Data quality rules\n\nEach rule flags rows and gives a likely cause, so the owner of the source system knows what to fix."
    ),
    code(
        "quality = validate(data.tests, data.lots, as_of)\nquality[['rule_id', 'rule', 'action', 'rows_flagged', 'likely_cause']]"
    ),
    md(
        "The leakage values flagged by R03 all come from one station on one day, and they are about "
        "1000 times too high. That pattern points to a unit change (nA instead of uA), not to bad parts."
    ),
    code(
        "c, quarantine, dropped = clean(data.tests, data.lots, as_of)\n"
        "r03 = quarantine[quarantine.reasons.str.contains('implausible_leakage')]\n"
        "print(r03.groupby(['station_id', r03.test_ts.dt.date]).size())\n"
        "print('median flagged leakage:', round(r03.leakage_ua.median(), 1))\n"
        "print(f'clean rows: {len(c):,} | quarantined: {len(quarantine)} | duplicates dropped: {dropped}')"
    ),
    md(
        "## 3. Distributions at each temperature\n\nLeakage grows strongly with temperature and is right-skewed, which is why the control chart later uses log values."
    ),
    code(
        "fig, axes = plt.subplots(1, 3, figsize=(13, 3.2))\n"
        "for ax, (param, lim) in zip(axes, SPEC.items()):\n"
        "    for t, g in c.groupby('temperature_c'):\n"
        "        ax.hist(g[param].dropna(), bins=60, alpha=0.5, label=f'{t} degC')\n"
        "    for v in (lim['lsl'], lim['usl']):\n"
        "        if v is not None:\n"
        "            ax.axvline(v, color='red', linestyle='--')\n"
        "    ax.set_title(param)\n"
        "axes[0].legend()\nplt.tight_layout()"
    ),
    md(
        "## 4. Yield KPIs from SQL\n\nThe KPI logic lives in `sql/kpis.sql` (window functions for retest attempts and rolling averages)."
    ),
    code(
        "con = load(c, data.lots)\nkpis = read_kpis(con)\n"
        "print(headline(con))\nkpis['v_yield_by_temperature']"
    ),
    code("kpis['v_bin_pareto']"),
    md("## 5. Is the T3 leakage rise a data problem or a process problem?"),
    code(
        "first = pd.read_sql_query('SELECT * FROM v_attempts WHERE attempt = 1', con)\n"
        "chart = control_chart(first[first.temperature_c == 125])\n"
        "first_alarm(chart)"
    ),
    code(
        "fig, ax = plt.subplots(figsize=(10, 3.5))\n"
        "for st, g in chart.groupby('station_id'):\n"
        "    ax.plot(pd.to_datetime(g.test_day), g.geo_mean_ua, marker='.', label=st)\n"
        "ax.set_ylabel('Geometric mean leakage at 125 degC (uA)')\nax.legend()\nax.grid(alpha=0.3)"
    ),
    code(
        "hot = first[first.temperature_c == 125].copy()\n"
        "hot['period'] = np.where(pd.to_datetime(hot.test_day) >= START + pd.Timedelta(days=18), 'from day 18', 'before')\n"
        "hot.pivot_table(index='station_id', columns='period', values='leakage_ua', aggfunc='median').round(2)"
    ),
    md(
        "**Reading the evidence**\n\n"
        "- The T3 rows passed every data quality rule: no missing values, plausible units, valid temperatures.\n"
        "- The rise is gradual and continues day after day, unlike the one-day jump of the unit error.\n"
        "- It appears on one station only, while the same products tested on other stations stay flat.\n\n"
        "That points to the test station or its setup (for example a drifting temperature chamber), so "
        "the next step would be to check T3's hardware and calibration, not the data feed.\n\n"
        "One caveat from the chart: a stable station can still raise a single-day alarm by chance. "
        "Running `scripts/evaluate_spc.py` over 20 simulated months measures how often that happens."
    ),
    md("## 6. Process capability"),
    code("capability_table(first).query('cpk < 1.33')"),
    md(
        "1.33 is a common minimum for a capable process. Supply current at 125 degC has the lowest Cpk, "
        "which matches it being the largest fail bin in the Pareto: improving its centering would recover "
        "more yield than any other single change."
    ),
]

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
path = Path(__file__).resolve().parent.parent / "notebooks" / "exploration.ipynb"
path.parent.mkdir(exist_ok=True)
nbf.write(nb, path)
print(f"wrote {path}")
