"""Derive ERA5-Land daily precipitation (pr, mm/day) from the ARCO time-chunked Zarr store into the `era5land`
mirror (group `daily`).

ARCO stores hourly, de-accumulated `tp` labelled at the end of each hour, so the UTC-day total for day D is the
sum over valid times (D 00:00, D+1 00:00]. This reproduces the CDS 00 UTC daily accumulations exactly (checked at
four points). Reads 24 hourly global maps (8 tiles of 1024x1024 each, ~2.7 MB per map) per day.

  uv run python scripts/era5land/derive_pr_arco.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import fsspec
import numpy as np
import pandas as pd
import xarray as xr
import zarr

from climate_mirror import credentials, era5land, storage
from climate_mirror.derived import init_daily_group, write_days

WINDOW_DAYS = 7


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = p.parse_args()
    zarr.config.set({"async.concurrency": 64, "threading.max_workers": 32})

    url = era5land.ARCO["pressure-precipitation"]["time"]
    fs = fsspec.filesystem("https", client_kwargs={"headers": credentials.cds_headers()})
    src = xr.open_zarr(fs.get_mapper(url), consolidated=True, chunks=None)
    hours = src.time.values
    assert src.latitude.values[0] < src.latitude.values[-1] and np.isclose(src.longitude.values[-1], 180.0), "ARCO grid changed"
    tp = zarr.open_array(fs.get_mapper(f"{url}/tp"), mode="r", zarr_format=2)

    repo = storage.open_mirror("era5land", create=True)
    init_daily_group(repo, "daily", era5land.GRID, *era5land.RECORD, era5land.CANONICAL_VARS, chunks=era5land.CHUNKS,
                     attrs=era5land.GROUP_ATTRS)
    for w0 in pd.date_range(args.start, args.end, freq=f"{WINDOW_DAYS}D"):
        t0 = time.time()
        days = pd.date_range(w0, min(w0 + pd.Timedelta(days=WINDOW_DAYS - 1), pd.Timestamp(args.end)), freq="D")
        out = np.empty((len(days), era5land.GRID.ny, era5land.GRID.nx), dtype=np.float32)
        for k, d in enumerate(days):
            h0 = int(np.searchsorted(hours, (d + pd.Timedelta(hours=1)).to_datetime64()))  # first hour ending in day d
            assert hours[h0] == (d + pd.Timedelta(hours=1)).to_datetime64(), (d, hours[h0])
            day = np.asarray(tp[h0 : h0 + 24], dtype=np.float64).sum(axis=0) * 1000.0  # m -> mm
            # ARCO latitude ascends (-90..90) and longitude runs -179.9..180.0; GRID is lat 90..-90, lon -180.0..179.9.
            out[k] = np.roll(day[::-1], 1, axis=-1)
        da = xr.DataArray(out, dims=("time", "lat", "lon"),
                          coords={"time": days, "lat": era5land.GRID.lat, "lon": era5land.GRID.lon})
        write_days(repo, "daily", {"pr": da}, f"daily: pr {days[0].date()}..{days[-1].date()} from ARCO (tp hourly sums)")
        print(f"pr {days[0].date()}..{days[-1].date()}: {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
