"""Write the CDS-sourced ERA5-Land daily variables (all but pr; see climate_mirror.era5land) from cached NetCDFs
into the `era5land` mirror (group `daily`).

  uv run python scripts/era5land/derive_daily.py --start 2021-01 --end 2021-12
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import xarray as xr

from climate_mirror import era5land, storage
from climate_mirror.derived import init_daily_group, write_days


def load_field(f: era5land.Field, month: pd.Period) -> xr.DataArray:
    """One field for one calendar month as (time, lat, lon) in canonical units, lon rolled to -180..180."""
    if f.statistic:
        ds = xr.open_dataset(era5land.cache_file(f, str(month)))
        da = ds[next(iter(ds.data_vars))]
        da = da.rename(valid_time="time")
    else:
        # 00 UTC accumulations: value at D+1 00:00 is the total over day D.
        both = xr.concat(
            [xr.open_dataset(era5land.cache_file(f, str(m)))[["ssrd"]]
             for m in (month, month + 1)],
            dim="valid_time",
        )
        da = next(iter(both.data_vars.values()))
        da = da.assign_coords(valid_time=da.valid_time - np.timedelta64(1, "D")).rename(valid_time="time")
        da = da.sel(time=slice(month.start_time, month.end_time))
    da = da.drop_vars([c for c in da.coords if c not in ("time", "latitude", "longitude")])
    da = (da * f.scale + f.offset).astype(np.float32)
    da = da.rename(latitude="lat", longitude="lon").roll(lon=era5land.GRID.nx // 2, roll_coords=False)
    return da.assign_coords(lat=era5land.GRID.lat, lon=era5land.GRID.lon, time=da.time.dt.floor("D"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM")
    p.add_argument("--end", required=True, help="YYYY-MM")
    args = p.parse_args()
    repo = storage.open_mirror("era5land", create=True)
    init_daily_group(repo, "daily", era5land.GRID, *era5land.RECORD, era5land.CANONICAL_VARS, chunks=era5land.CHUNKS,
                     attrs=era5land.GROUP_ATTRS)
    for month in pd.period_range(args.start, args.end, freq="M"):
        # write whatever fields are cached (CDS requests finish at different times); rerun later for the rest
        ready = [f for f in era5land.FIELDS
                 if era5land.cache_file(f, str(month)).exists()
                 and (f.statistic or era5land.cache_file(f, str(month + 1)).exists())]
        if not ready:
            print(f"{month}: nothing cached yet", flush=True)
            continue
        fields = {f.canonical: load_field(f, month) for f in ready}
        write_days(repo, "daily", fields, f"daily: {month} ({', '.join(fields)}) from CDS")
        print(f"{month}: wrote {', '.join(fields)}", flush=True)


if __name__ == "__main__":
    main()
