"""Quantify the difference between PRISM source float32 values and harmonized decimal values.

Written for PRISM (below); runs on any registered dataset via --dataset.
PRISM grids hold exact decimal quantities (3 or 4 decimals) but were written to float32 in
different ways: float32(k / 10^d) ("div") or float32(k) * float32(10^-d) ("mul"); some older
daily ppt grids also hold unrounded values ("other"), which get rounded to 1e-4. The mirror
stores the integer k (in 1e-4 units) and decodes to the canonical float32(k / 10^4), i.e. the
float32 nearest to the decimal value. This script measures, per sampled grid, what that changes:
absolute/relative/ulp differences, systematic bias, effect on accumulated totals, and how often
common thresholds (wet day, frost day, ...) would be classified differently.
Output: results/<dataset>/rounding_analysis.csv
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from climate_mirror import datasets
from climate_mirror.packing import canonical, classify_style


def analyze(job):
    dsname, var, fname, d = job
    ds = datasets.get(dsname)
    F = ds.frequencies[fname]
    if not ds.source_exists(var, F, d):
        return None
    x = ds.read_grid(var, F, d)
    ok = np.isfinite(x)
    xs = x[ok]
    c = canonical(xs, ds.variables[var].valid_range)
    ulp = xs.view(np.int32).astype(np.int64) - c.view(np.int32).astype(np.int64)
    diff = xs.astype(np.float64) - c.astype(np.float64)
    nz = (xs != 0) & (c != 0)  # relative differences only where both are nonzero (tiny values may round to 0)
    rel = np.abs(diff[nz] / c[nz].astype(np.float64)) if nz.any() else np.zeros(1)
    row = {
        "var": var, "freq": fname, "date": str(d), "style": classify_style(xs),
        "n_valid": xs.size, "frac_changed": float(np.mean(ulp != 0)), "max_abs_ulp": int(np.abs(ulp).max()),
        "max_abs_diff": float(np.abs(diff).max()), "max_rel_diff": float(rel.max()),
        "mean_signed_rel_diff": float(np.mean(diff[nz] / c[nz])) if nz.any() else 0.0,
        "mean_signed_abs_diff": float(np.mean(diff)),
        "frac_quantized": float(np.mean(np.abs(ulp) > 1)),  # moved by more than float32 noise
        "frac_up": float(np.mean(ulp > 0)), "frac_down": float(np.mean(ulp < 0)),
        # Domain total (e.g. CONUS-summed precipitation), summed in float64.
        "domain_sum_rel_diff": float(xs.astype(np.float64).sum() / c.astype(np.float64).sum() - 1) if c.any() else 0.0,
        "zero_preserved": bool(np.array_equal(xs == 0, c == 0)),
        "n_to_zero": int(np.sum((xs != 0) & (c == 0))),
    }
    flips = 0
    for t in ds.thresholds.get(var, []):
        t32 = np.float32(t)
        flips += int(np.sum((xs >= t32) != (c >= t32)))
    row["threshold_flips"] = flips
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=list(datasets.DATASETS), default="prism")
    p.add_argument("--freq", nargs="*")
    args = p.parse_args()
    ds = datasets.get(args.dataset)
    jobs = [
        (args.dataset, v, f, d.date())
        for f in args.freq or list(ds.frequencies)
        for d in datasets.sample_dates(ds, ds.frequencies[f])
        for v in ds.variables
    ]
    with ProcessPoolExecutor(12) as ex:
        rows = [r for r in ex.map(analyze, jobs, chunksize=4) if r]
    df = pd.DataFrame(rows)
    out = ds.results_dir / "rounding_analysis.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():  # keep rows for frequencies not analyzed in this run
        old = pd.read_csv(out)
        df = pd.concat([old[~old.freq.isin(df.freq.unique())], df], ignore_index=True)
    df.to_csv(out, index=False)

    pd.set_option("display.width", 250)
    g = df.groupby(["freq", "var", "style"])
    print(g.agg(
        grids=("date", "size"), frac_changed=("frac_changed", "mean"), max_ulp=("max_abs_ulp", "max"),
        max_abs_diff=("max_abs_diff", "max"), max_rel_diff=("max_rel_diff", "max"),
        frac_quantized=("frac_quantized", "mean"), mean_signed_abs=("mean_signed_abs_diff", "mean"),
        mean_signed_rel=("mean_signed_rel_diff", "mean"), domain_sum_rel=("domain_sum_rel_diff", "mean"),
        flips=("threshold_flips", "sum"), zeros_ok=("zero_preserved", "all"), to_zero=("n_to_zero", "sum"),
    ).to_string(float_format=lambda v: f"{v:.3g}"))


if __name__ == "__main__":
    main()
