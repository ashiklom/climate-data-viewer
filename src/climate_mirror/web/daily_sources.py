"""Open each dataset's daily data as canonical variables (see climate_mirror.variables).

Every reader returns a lazy xr.Dataset with dims (time, lat, lon), daily `time` (period start, as
labelled by the source), lat/lon cell centers in degrees (Daymet: (time, y, x) on its projected grid, with
`crs_wkt` in the attributes), and canonical names and units. Day
definitions differ by source and are recorded in DAY_WINDOW (the website shows them).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import xarray as xr

from climate_mirror import storage

DATASETS = ["prism", "chirps", "era5", "era5land", "merra2", "imerg", "gridmet", "nldas", "daymet"]

DAY_WINDOW = {
    "prism": "24 h ending 12:00 UTC on the labelled date",
    "chirps": "UTC day (dynamical.org CHIRPS v3 final daily; CHIRPS pentad totals split into days with ERA5)",
    "era5": "UTC day (00-24 UTC)",
    "era5land": "UTC day (00-24 UTC)",
    "merra2": "UTC day (NASA POWER, MERRA-2)",
    "imerg": "UTC day (NASA POWER, IMERG Final)",
    "gridmet": "calendar day ending at midnight MST (07 UTC the next day)",
    "nldas": "UTC day (00-24 UTC; precipitation is CPC daily gauge analysis, 12-12 UTC, split into hours)",
    "daymet": "24-hour day based on local time (Daymet)",
}

PRISM_CROSSWALK = {"pr": "ppt", "tas": "tmean", "tasmax": "tmax", "tasmin": "tmin", "tdps": "tdmean", "rsds": "soltotal"}
MERRA2_CROSSWALK = {
    "pr": "PRECTOTCORR", "tas": "T2M", "tasmax": "T2M_MAX", "tasmin": "T2M_MIN", "tdps": "T2MDEW", "ps": "PS",
    "sfcWind": "WS10M", "sm1": "GWETTOP", "sm2": "GWETROOT",
}


def _sel(ds: xr.Dataset, start: dt.date, end: dt.date) -> xr.Dataset:
    return ds.sel(time=slice(np.datetime64(start), np.datetime64(end)))


def _mirror_group(name: str, group: str) -> xr.Dataset:
    repo = storage.open_mirror(name)
    return xr.open_zarr(repo.readonly_session("main").store, group=group, consolidated=False, chunks={})


def prism(start: dt.date, end: dt.date) -> xr.Dataset:
    from climate_mirror.prism.store import open_prism

    ds = open_prism("daily")
    out = xr.Dataset({c: ds[v] for c, v in PRISM_CROSSWALK.items()})
    return _sel(out, start, end)


def chirps(start: dt.date, end: dt.date) -> xr.Dataset:
    """Our map-optimized copy of dynamical.org's CHIRPS daily (scripts/chirps/rechunk_dynamical.py), mm/day."""
    return _sel(_mirror_group("chirps", "daily").drop_vars("time_bnds"), start, end)


def era5(start: dt.date, end: dt.date) -> xr.Dataset:
    return _sel(_mirror_group("era5", "daily").drop_vars("time_bnds"), start, end)


def era5land(start: dt.date, end: dt.date) -> xr.Dataset:
    return _sel(_mirror_group("era5land", "daily").drop_vars("time_bnds"), start, end)


def _power(name: str, crosswalk: dict[str, str], start: dt.date, end: dt.date) -> xr.Dataset:
    url = storage.config()["external"][name]["spatial_url"]
    ds = xr.open_zarr(url, consolidated=True, chunks={})
    out = xr.Dataset({c: ds[v] for c, v in crosswalk.items() if v in ds})
    return _sel(out, start, end)


def merra2(start: dt.date, end: dt.date) -> xr.Dataset:
    return _power("merra2_power", MERRA2_CROSSWALK, start, end)


def imerg(start: dt.date, end: dt.date) -> xr.Dataset:
    return _power("imerg_power", {"pr": "IMERG_PRECTOT"}, start, end)


def gridmet(start: dt.date, end: dt.date) -> xr.Dataset:
    """Our gridMET mirror (scripts/gridmet/build_store.py): canonical variables, CF-decoded to float32."""
    repo = storage.open_mirror("gridmet")
    ds = xr.open_zarr(repo.readonly_session("main").store, group="daily", consolidated=False, chunks=None)
    return _sel(ds.drop_vars("time_bnds"), start, end).astype(np.float32)


def nldas(start: dt.date, end: dt.date) -> xr.Dataset:
    """Daily canonical variables derived from our NLDAS-2 hourly mirror (scripts/nldas/derive_daily.py)."""
    return _sel(_mirror_group("nldas", "daily").drop_vars("time_bnds"), start, end)


def daymet(start: dt.date, end: dt.date) -> xr.Dataset:
    """Daymet mirror (scripts/daymet/mirror.py), CONUS window, canonical variables on the native LCC grid:
    dims (time, y, x) in metres, with `crs_wkt` in the attributes (regrid_common reprojects it)."""
    from climate_mirror import daymet as dm

    repo = storage.open_mirror("daymet")
    ds = xr.open_zarr(repo.readonly_session("main").store, group="daily", consolidated=False, chunks=None)
    ds = _sel(ds, start, end).isel(y=slice(*dm.WINDOW_Y), x=slice(*dm.WINDOW_X))
    native = {v: ds[v].astype(np.float32) for v in dm.VARIABLES}
    out = xr.Dataset({c: dm.canonical(c, native).astype(np.float32) for c in dm.CANONICAL_VARS})
    out.attrs["crs_wkt"] = dm.crs_wkt()
    return out


READERS = {"prism": prism, "chirps": chirps, "era5": era5, "era5land": era5land, "merra2": merra2, "imerg": imerg, "gridmet": gridmet, "nldas": nldas, "daymet": daymet}


def open_daily(name: str, start: dt.date, end: dt.date) -> xr.Dataset:
    """Daily canonical variables with only (time, lat, lon) coordinates."""
    return READERS[name](start, end).reset_coords(drop=True)
