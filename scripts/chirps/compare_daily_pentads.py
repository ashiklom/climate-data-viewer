"""Do dynamical.org's daily CHIRPS values (our `chirps/daily` copy, mm/day) sum to CHC's native pentads?

CHC's daily product splits each native pentad total into days with ERA5 rainfall; dynamical then rounds values
to 8 mantissa bits. Summing a pentad's days should therefore reproduce the pentad up to that rounding.
Compares every 2021 pentad in the mirror (`pentads` group, written by build_store.py) cell by cell.
Output: results/chirps/daily_vs_pentads.csv

  uv run python scripts/chirps/compare_daily_pentads.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from climate_mirror import storage
from climate_mirror.chirps.catalog import PENTAD, RESULTS_DIR


def main() -> None:
    repo = storage.open_mirror("chirps")
    store = repo.readonly_session("main").store
    daily = xr.open_zarr(store, group="daily", consolidated=False, chunks={})["pr"]
    pent = xr.open_zarr(store, group="pentads", consolidated=False, chunks={})["precip"]
    starts = PENTAD.dates(pd.Timestamp("2021-12-31").date())
    starts = starts[starts >= "2021-01-01"]
    rows = []
    for s, e in zip(starts, PENTAD.ends(starts)):
        p = pent.sel(time=s).values.astype(np.float64)
        d = daily.sel(time=slice(s, e - pd.Timedelta(days=1)))
        assert d.sizes["time"] == (e - s).days
        dsum = d.sum("time", skipna=False).values.astype(np.float64)
        both = np.isfinite(p) & np.isfinite(dsum)
        diff = dsum[both] - p[both]
        wet = p[both] >= 1.0
        rel = np.abs(diff[wet]) / p[both][wet]
        rows.append({
            "pentad": str(s.date()), "days": (e - s).days, "cells": int(both.sum()),
            "mask_agreement": float(np.mean(np.isfinite(p) == np.isfinite(dsum))),
            "total_ratio": float(dsum[both].sum() / p[both].sum()),
            "max_abs_diff_mm": float(np.abs(diff).max()),
            "p99_abs_diff_mm": float(np.quantile(np.abs(diff), 0.99)),
            "median_rel_diff_wet": float(np.median(rel)), "p99_rel_diff_wet": float(np.quantile(rel, 0.99)),
            "max_rel_diff_wet": float(rel.max()),
            "frac_exact": float(np.mean(np.float32(dsum[both]) == np.float32(p[both]))),
        })
        print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "daily_vs_pentads.csv", index=False)
    print(df.describe().T[["mean", "min", "max"]].to_string(float_format=lambda v: f"{v:.4g}"))


if __name__ == "__main__":
    main()
