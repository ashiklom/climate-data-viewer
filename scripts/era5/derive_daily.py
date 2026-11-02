"""Derive daily canonical variables from Earthmover's hourly ERA5 into our `era5` mirror (group `daily`).

Reads `single/spatial` (one hourly global map per chunk) in 7-day windows (~7 GB in memory),
aggregates to UTC days (see climate_mirror.era5), and writes one commit per window. Re-running skips nothing: it overwrites the
same days with identical values, so interrupted runs can simply be restarted with a later --start.

  uv run python scripts/era5/derive_daily.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import pandas as pd
import xarray as xr
import zarr

from climate_mirror import era5, storage
from climate_mirror.derived import init_daily_group, write_days

LISTING = "Earthmover ERA5 exchange listing 6a19bcfe9aa6e97720a2fad2 (s3://earthmover-icechunk-era5/icechunkV2)"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = p.parse_args()
    zarr.config.set({"async.concurrency": 128, "threading.max_workers": 32})

    src_repo = storage.open_external("era5_earthmover")
    snapshot = next(src_repo.ancestry(branch="main")).id
    src = xr.open_zarr(src_repo.readonly_session(snapshot_id=snapshot).store, group=era5.SOURCE_GROUP,
                       consolidated=False, chunks=None)[era5.SOURCE_VARS]

    repo = storage.open_mirror("era5", create=True)
    init_daily_group(
        repo, "daily", era5.GRID, *era5.RECORD, era5.CANONICAL_VARS,
        attrs={
            "title": "ERA5 daily canonical variables (UTC days), derived from hourly ERA5",
            "source": LISTING,
            "source_snapshot": snapshot,
            "institution": "ECMWF / Copernicus Climate Change Service; hourly data via NSF NCAR and Earthmover",
            "license": "CC-BY-4.0",
            "comment": "Accumulated fields (pr, rsds) sum hourly values ending in (D 00:00, D+1 00:00] UTC; "
                       "instantaneous fields aggregate hours 00..23 UTC. Longitudes rolled to -180..180.",
        },
    )
    for w0 in pd.date_range(args.start, args.end, freq="7D"):
        d0 = w0.date()
        d1 = min(d0 + dt.timedelta(days=6), args.end)
        ndays = (d1 - d0).days + 1
        t0 = time.time()
        hourly = src.sel(valid_time=slice(np.datetime64(d0), np.datetime64(d1 + dt.timedelta(days=1)))).load()
        out = era5.daily(hourly, np.datetime64(d0), ndays)
        write_days(repo, "daily", out, f"daily: {d0}..{d1} from Earthmover snapshot {snapshot}")
        print(f"{d0}..{d1}: {ndays} days in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
