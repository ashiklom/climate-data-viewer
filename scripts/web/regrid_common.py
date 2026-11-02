"""Regrid a dataset's daily canonical variables conservatively onto the common 0.25 deg grid
(the ERA5 grid: cell centers at multiples of 0.25 deg, lat 90..-90, lon -180..179.75) and write them
to group `common_0p25/daily` in that dataset's mirror (stores.toml).

Cells with more than half of their area missing in the source become missing (nan_threshold=0.5),
so coastlines and domain edges (PRISM CONUS, CHIRPS/IMERG latitude limits) stay honest.

  uv run python scripts/web/regrid_common.py --dataset merra2 --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import pandas as pd
import xarray as xr
import xarray_regrid  # noqa: F401  (registers .regrid)

from climate_mirror import era5, storage
from climate_mirror.derived import init_daily_group, write_days
from climate_mirror.web.daily_sources import DATASETS, DAY_WINDOW, open_daily

GROUP = "common_0p25/daily"
TARGET = xr.Dataset(coords={"lat": era5.GRID.lat, "lon": era5.GRID.lon})
WINDOW_DAYS = 32  # = PRISM's daily time chunk, so PRISM windows align with its chunks when started on a boundary


def regrid(ds: xr.Dataset) -> xr.Dataset:
    ds = ds.sortby("lat", ascending=False).sortby("lon")
    out = ds.regrid.conservative(TARGET, latitude_coord="lat", skipna=True, nan_threshold=0.5)
    return out.astype(np.float32)


def load_with_retry(name: str, d0: dt.date, d1: dt.date, attempts: int = 5) -> xr.Dataset:
    """Remote sources (NASA POWER, S3) occasionally drop connections; retry with backoff."""
    for i in range(attempts):
        try:
            return open_daily(name, d0, d1).load()
        except Exception as e:  # network errors surface as many exception types (aiohttp, OSError, ...)
            if i == attempts - 1:
                raise
            wait = 30 * 2**i
            print(f"  {name} {d0}..{d1}: {type(e).__name__}: {str(e)[:120]}; retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=DATASETS, required=True)
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = p.parse_args()

    probe = open_daily(args.dataset, args.start, args.start)
    variables = list(probe.data_vars)
    repo = storage.open_mirror(args.dataset, create=True)
    init_daily_group(
        repo, GROUP, era5.GRID, era5.RECORD[0], dt.date(2026, 12, 31), variables,
        attrs={
            "title": f"{args.dataset} daily canonical variables on the common 0.25 degree grid",
            "comment": "Conservative regridding (xarray-regrid, area-weighted; cells >50% missing are missing) "
                       "from the dataset's native grid. Grid = ERA5 0.25 degree cell centers.",
            "day_window": DAY_WINDOW[args.dataset],
        },
    )
    for w0 in pd.date_range(args.start, args.end, freq=f"{WINDOW_DAYS}D"):
        d0 = w0.date()
        d1 = min(d0 + dt.timedelta(days=WINDOW_DAYS - 1), args.end)
        t0 = time.time()
        src = load_with_retry(args.dataset, d0, d1)
        out = regrid(src)
        write_days(repo, GROUP, {v: out[v] for v in variables}, f"{GROUP}: {d0}..{d1}")
        print(f"{args.dataset} {d0}..{d1}: {src.sizes['time']} days in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
