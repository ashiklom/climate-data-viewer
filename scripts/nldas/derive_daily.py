"""Derive daily canonical variables (UTC days) from the NLDAS-2 hourly mirror into group `daily` of the same repo.

Layout: one-day 56 x 116 tiles in 32-day shards (maps read 32 small chunks of one shard, point series one small
chunk per day). Rows run north to south (climate_mirror.derived.Grid). Rerunning overwrites the same days.

    uv run python scripts/nldas/derive_daily.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import pandas as pd
import xarray as xr

from climate_mirror import nldas, storage
from climate_mirror.derived import init_daily_group, write_days

WINDOW = 32


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = p.parse_args()
    repo = storage.open_mirror("nldas")
    src = xr.open_zarr(repo.readonly_session("main").store, group="hourly", consolidated=False, chunks=None)
    vars_ = ["Tair", "Qair", "PSurf", "Wind_E", "Wind_N", "Rainf", "SWdown", "SoilM_0_10cm", "SoilM_10_40cm"]
    init_daily_group(
        repo, "daily", nldas.GRID, *nldas.RECORD, nldas.CANONICAL_VARS,
        attrs={
            "title": "NLDAS-2 daily canonical variables (UTC days), derived from the hourly mirror (group hourly)",
            "references": nldas.CITATION,
            "license": "CC-BY-4.0 (NASA EOSDIS open data)",
            "comment": "pr sums FORA Rainf over hours ending (D 00, D+1 00] UTC; other fields aggregate hours 00..23 "
                       "UTC. tdps: mean of hourly dew points from Qair and PSurf (IFS saturation formula). rsds: "
                       "mean of hourly SWdown x 0.0864. sm1/sm2: Noah SoilM 0-10 cm / 10-40 cm (total water) "
                       "divided by layer depth (1000 kg m-3).",
            "day_window": "UTC day (00-24 UTC)",
        },
        chunks=(1, 56, 116), shards=(32, nldas.NY, nldas.NX),
    )
    for w0 in pd.date_range(args.start, args.end, freq=f"{WINDOW}D"):
        d0 = w0.date()
        d1 = min(d0 + dt.timedelta(days=WINDOW - 1), args.end)
        ndays = (d1 - d0).days + 1
        t0 = time.time()
        h = src[vars_].sel(time=slice(np.datetime64(d0), np.datetime64(d1 + dt.timedelta(days=1)))).load()
        if h.sizes["time"] != 24 * ndays + 1:
            raise ValueError(f"{d0}..{d1}: {h.sizes['time']} hours, need {24 * ndays + 1}")
        out = nldas.daily({v: h[v].values.astype(np.float64) for v in vars_}, ndays)
        times = pd.date_range(d0, d1, freq="D")
        coords = {"time": times, "lat": h.lat.values, "lon": h.lon.values}
        das = {k: xr.DataArray(v.astype(np.float32), coords, ("time", "lat", "lon")).sortby("lat", ascending=False)
               for k, v in out.items()}
        write_days(repo, "daily", das, f"daily: {d0}..{d1} from hourly")
        print(f"{d0}..{d1}: {ndays} days in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
