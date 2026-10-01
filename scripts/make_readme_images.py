"""Save the README charts to docs/images/.  python scripts/make_readme_images.py"""

import base64
import re
from pathlib import Path

from mcu_analytics.pipeline import run

root = Path(__file__).resolve().parent.parent
out = root / "output"
run(out, seed=7)
imgs = re.findall(r'base64,([^"]+)"', (out / "report.html").read_text())
# order in the report: station yield, pareto, control charts T1..T4
names = ["station_yield.png", "bin_pareto.png", None, None, "spc_t3.png", None]
target = root / "docs" / "images"
target.mkdir(parents=True, exist_ok=True)
for name, data in zip(names, imgs):
    if name:
        (target / name).write_bytes(base64.b64decode(data))
        print("wrote", target / name)
