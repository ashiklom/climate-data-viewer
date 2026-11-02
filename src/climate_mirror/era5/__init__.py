"""ERA5 from Earthmover's public ERA5 Icechunk store (stores.toml [external.era5_earthmover]).

Hourly, 0.25 deg, 1940-. We derive daily canonical variables (UTC days) into our `era5` mirror:
- instantaneous fields (t2m, d2m, sp, u10/v10, swvl*): aggregate the 24 values at 00..23 UTC;
- accumulated fields (tp, ssrd; GRIB stepType "accum", one hour each, ending at valid_time):
  sum the 24 values ending at 01..24 UTC, i.e. valid_time in (D 00:00, D+1 00:00].
Longitudes are rolled from 0..359.75 to -180..179.75.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import xarray as xr

from climate_mirror.derived import Grid

SOURCE_GROUP = "single/spatial"
GRID = Grid(north=90.0, west=-180.0, res=0.25, ny=721, nx=1440)
RECORD = (dt.date(1940, 1, 1), dt.date(2026, 6, 29))  # last full UTC day in the source (ends 2026-06-30T23)
SOURCE_VARS = ["tp", "t2m", "d2m", "sp", "ssrd", "u10", "v10", "swvl1", "swvl2"]
ACCUMULATED = {"tp", "ssrd"}
CANONICAL_VARS = ["pr", "tas", "tasmax", "tasmin", "tdps", "ps", "rsds", "sfcWind", "sm1", "sm2"]


def daily(hourly: xr.Dataset, day0: np.datetime64, ndays: int) -> dict[str, xr.DataArray]:
    """Canonical daily fields for `ndays` UTC days starting at day0, from hourly data covering
    [day0 00:00, day0 + ndays 00:00] (inclusive end, needed for accumulations)."""
    t = hourly.valid_time
    inst = hourly.sel(valid_time=(t >= day0) & (t < day0 + np.timedelta64(ndays, "D")))
    acc = hourly.sel(valid_time=(t > day0) & (t <= day0 + np.timedelta64(ndays, "D")))
    # Label accumulations by the day they fall in: shift back 1 h so (D 00:00, D+1 00:00] -> [D 00:00, D+1 00:00).
    acc = acc.assign_coords(valid_time=acc.valid_time - np.timedelta64(1, "h"))
    di = inst.resample(valid_time="1D")
    da = acc.resample(valid_time="1D")
    wind = np.hypot(inst.u10, inst.v10).resample(valid_time="1D").mean()
    out = {
        "pr": da.sum().tp * 1000.0,  # m -> mm
        "rsds": da.sum().ssrd / 1e6,  # J m-2 -> MJ m-2
        "tas": di.mean().t2m - 273.15,
        "tasmax": di.max().t2m - 273.15,
        "tasmin": di.min().t2m - 273.15,
        "tdps": di.mean().d2m - 273.15,
        "ps": di.mean().sp / 100.0,
        "sfcWind": wind,
        "sm1": di.mean().swvl1,
        "sm2": di.mean().swvl2,
    }
    for k, v in out.items():
        v = v.rename(valid_time="time", latitude="lat", longitude="lon")
        v = v.roll(lon=GRID.nx // 2, roll_coords=False).assign_coords(lat=GRID.lat, lon=GRID.lon)
        out[k] = v
    return out
