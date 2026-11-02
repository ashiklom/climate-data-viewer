"""Write derived daily maps (canonical variables) into a mirror repo.

A derived group holds one canonical variable per array on a regular lat/lon grid over a full-record
daily time axis, chunked one day per chunk (map-optimized; large grids tiled spatially). Days are written incrementally, so a
group grows in place; unwritten days read as missing and cost no storage.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import icechunk
import numpy as np
import pandas as pd
import xarray as xr
import zarr

from climate_mirror.codecs import codec_kwargs
from climate_mirror.variables import CANONICAL

TIME_UNITS = "days since 1900-01-01"


@dataclass(frozen=True)
class Grid:
    """Regular lat/lon grid of cell centers: lat descending from `north`, lon ascending from `west`."""

    north: float  # center of the first row
    west: float  # center of the first column
    res: float
    ny: int
    nx: int
    crs: str = "EPSG:4326"

    @property
    def lat(self) -> np.ndarray:
        return self.north - np.arange(self.ny) * self.res

    @property
    def lon(self) -> np.ndarray:
        return self.west + np.arange(self.nx) * self.res

    def geozarr(self) -> dict:
        r = self.res
        return {
            "spatial:dimensions": ["lat", "lon"],
            "spatial:transform": [r, 0.0, self.west - r / 2, 0.0, -r, self.north + r / 2],
            "spatial:shape": [self.ny, self.nx],
            "spatial:registration": "pixel",
            "proj:code": self.crs,
        }


def init_daily_group(
    repo: icechunk.Repository, path: str, grid: Grid, start: dt.date, end: dt.date, variables: list[str],
    attrs: dict, codec: str = "pcodec8", var_attrs: dict[str, dict] | None = None,
    chunks: tuple[int, int, int] | None = None,
) -> None:
    """Create `path` with a daily time axis [start, end], coordinates, and empty arrays (if missing).

    `chunks` defaults to one whole map per day; large grids should use spatial tiles (e.g. (1, 1200, 1800))."""
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=path, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    dates = pd.date_range(start, end, freq="D")
    ds = xr.Dataset(coords={
        "time": ("time", dates, {"standard_name": "time", "axis": "T", "bounds": "time_bnds"}),
        "lat": ("lat", grid.lat, {"standard_name": "latitude", "units": "degrees_north", "axis": "Y"}),
        "lon": ("lon", grid.lon, {"standard_name": "longitude", "units": "degrees_east", "axis": "X"}),
    })
    ds["time_bnds"] = (("time", "nv"), np.stack([dates.values, (dates + pd.Timedelta(days=1)).values], axis=1))
    ds.attrs = {"Conventions": "CF-1.10", **attrs, **grid.geozarr()}
    enc = {k: {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"} for k in ("time", "time_bnds")}
    ds.to_zarr(session.store, group=path, mode="w", encoding=enc, consolidated=False, zarr_format=3)
    group = zarr.open_group(session.store, path=path, mode="r+")
    for name in variables:
        c = CANONICAL[name]
        a = {"long_name": c.long_name, "units": c.units, "cell_methods": c.cell_methods}
        if c.standard_name:
            a["standard_name"] = c.standard_name
        a.update((var_attrs or {}).get(name, {}))
        group.create_array(
            name, shape=(len(dates), grid.ny, grid.nx), dtype="float32", chunks=chunks or (1, grid.ny, grid.nx),
            fill_value=np.nan, dimension_names=["time", "lat", "lon"], attributes=a,
            config={"write_empty_chunks": False}, **codec_kwargs(codec, 4),
        )
    session.commit(f"{path}: daily axis {start}..{end}, empty {', '.join(variables)}", rebase_with=icechunk.ConflictDetector())


def write_days(repo: icechunk.Repository, path: str, values: dict[str, xr.DataArray], message: str) -> None:
    """Write (time, lat, lon) float32 DataArrays (consecutive days) into the group, one commit."""
    session = repo.writable_session("main")
    group = zarr.open_group(session.store, path=path, mode="r+")
    t0 = pd.Timestamp("1900-01-01") + pd.Timedelta(days=int(group["time"][0]))  # TIME_UNITS
    for name, da in values.items():
        i0 = (pd.Timestamp(da.time.values[0]) - t0).days
        group[name][i0 : i0 + da.sizes["time"]] = da.transpose("time", "lat", "lon").values.astype(np.float32)
    # Other writers may commit to other groups of the same repo meanwhile; rebase unless there is a real conflict.
    session.commit(message, rebase_with=icechunk.ConflictDetector())
