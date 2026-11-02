"""Quantify the difference between PRISM source float32 values and harmonized decimal values.

PRISM grids hold exact decimal quantities (3 or 4 decimals) but were written to float32 in
different ways: float32(k / 10^d) ("div") or float32(k) * float32(10^-d) ("mul"). The mirror
stores the integer k (in 1e-4 units) and decodes to the canonical float32(k / 10^4), i.e. the
float32 nearest to the decimal value. This script measures, per sampled grid, what that changes:
absolute/relative/ulp differences, systematic bias, effect on accumulated totals, and how often
common thresholds (wet day, frost day, ...) would be classified differently.
Output: results/rounding_analysis.csv
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from prism_mirror.catalog import FREQUENCIES, RESULTS_DIR, VARIABLES, local_zip, sample_dates
from prism_mirror.io import read_grid
from prism_mirror.packing import canonical, classify_style

THRESHOLDS = {  # variable -> thresholds in native units (wet-day, heavy-rain, frost, heat, ...)
    "ppt": [0.01, 0.1, 0.254, 1.0, 10.0, 25.4, 50.8],
    "tmin": [0.0, -17.778],
    "tmax": [0.0, 32.222, 35.0],
    "tmean": [0.0, 5.0, 10.0],
    "tdmean": [0.0],
    "vpdmin": [1.0],
    "vpdmax": [10.0, 30.0],
    "soltotal": [5.0],
    "solslope": [5.0],
}


def analyze(job):
    var, fname, d = job
    F = FREQUENCIES[fname]
    if not local_zip(var, F, d).exists():
        return None
    x = read_grid(var, F, d).data
    ok = np.isfinite(x)
    xs = x[ok]
    c = canonical(xs, var)
    ulp = xs.view(np.int32).astype(np.int64) - c.view(np.int32).astype(np.int64)
    diff = xs.astype(np.float64) - c.astype(np.float64)
    nz = xs != 0
    rel = np.abs(diff[nz] / c[nz].astype(np.float64)) if nz.any() else np.zeros(1)
    row = {
        "var": var, "freq": fname, "date": str(d), "style": classify_style(xs),
        "n_valid": xs.size, "frac_changed": float(np.mean(ulp != 0)), "max_abs_ulp": int(np.abs(ulp).max()),
        "max_abs_diff": float(np.abs(diff).max()), "max_rel_diff": float(rel.max()),
        "mean_signed_rel_diff": float(np.mean(diff[nz] / c[nz])) if nz.any() else 0.0,
        "frac_up": float(np.mean(ulp > 0)), "frac_down": float(np.mean(ulp < 0)),
        # Domain total (e.g. CONUS-summed precipitation), summed in float64.
        "domain_sum_rel_diff": float(xs.astype(np.float64).sum() / c.astype(np.float64).sum() - 1) if c.any() else 0.0,
        "zero_preserved": bool(np.array_equal(xs == 0, c == 0)),
    }
    flips = 0
    for t in THRESHOLDS[var]:
        t32 = np.float32(t)
        flips += int(np.sum((xs >= t32) != (c >= t32)))
    row["threshold_flips"] = flips
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    args = p.parse_args()
    jobs = [(v, f, d.date()) for f in args.freq for d in sample_dates(FREQUENCIES[f]) for v in VARIABLES]
    with ProcessPoolExecutor(12) as ex:
        rows = [r for r in ex.map(analyze, jobs, chunksize=4) if r]
    df = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(exist_ok=True)
    df.to_csv(RESULTS_DIR / "rounding_analysis.csv", index=False)

    pd.set_option("display.width", 250)
    g = df.groupby(["freq", "var", "style"])
    print(g.agg(
        grids=("date", "size"), frac_changed=("frac_changed", "mean"), max_ulp=("max_abs_ulp", "max"),
        max_abs_diff=("max_abs_diff", "max"), max_rel_diff=("max_rel_diff", "max"),
        mean_signed_rel=("mean_signed_rel_diff", "mean"), domain_sum_rel=("domain_sum_rel_diff", "mean"),
        flips=("threshold_flips", "sum"), zeros_ok=("zero_preserved", "all"),
    ).to_string(float_format=lambda v: f"{v:.3g}"))


if __name__ == "__main__":
    main()
