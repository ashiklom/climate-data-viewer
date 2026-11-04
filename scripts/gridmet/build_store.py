"""Build or extend the gridMET Icechunk mirror (stores.toml [mirrors.gridmet]) from the cached NKN NetCDF files.

Group `daily`: canonical variables (pr, tasmax, tasmin, tas, rsds, sfcWind) on (time, lat, lon) over the full
record (1979-01-01 .. 2026-12-31; unwritten days read as missing). Values are the source's own uint16 counts,
copied without decoding (lossless); only the CF scale_factor/add_offset change so that values decode to canonical
units. tas = (tasmax + tasmin) / 2 is stored exactly as the count sum (scale 0.05).

Layout: 32-day shards of the whole grid, holding one-day 117 x 154 chunks (45 per day): a map is one object,
a point series reads one small chunk per day.

    uv run python scripts/gridmet/build_store.py --years 2021
"""

from __future__ import annotations

import argparse
import datetime as dt

import h5py
import icechunk
import numpy as np
import pandas as pd
import xarray as xr
import zarr

from climate_mirror import gridmet, storage
from climate_mirror.codecs import codec_kwargs
from climate_mirror.variables import CANONICAL

MIRROR = "gridmet"
GROUP = "daily"
RECORD = (dt.date(1979, 1, 1), dt.date(2026, 12, 31))
TIME_UNITS = "days since 1900-01-01"  # as in the source files
SHARDS = (32, 585, 1386)
CHUNKS = (1, 117, 154)
CODEC = "pcodec8"


def read_counts(source: str, year: int, nc_var: str, expect: tuple[float, float]) -> tuple[np.ndarray, dict]:
    """Raw uint16 counts (day, lat, lon) and coordinates, checking the packing is the expected one."""
    with h5py.File(gridmet.local(source, year), "r") as f:
        v = f[nc_var]
        sf = float(np.ravel(v.attrs.get("scale_factor", 1.0))[0])
        ao = float(np.ravel(v.attrs.get("add_offset", 0.0))[0])
        if not np.isclose(sf, expect[0]) or not np.isclose(ao, expect[1]):
            raise ValueError(f"{source} {year}: unexpected packing scale={sf} offset={ao}")
        if v.dtype != np.uint16 and v.dtype != np.int16:
            raise ValueError(f"{source} {year}: unexpected dtype {v.dtype}")
        counts = v[...].view(np.uint16)
        coords = {"day": f["day"][...], "lat": f["lat"][...], "lon": f["lon"][...],
                  "note": {k: (a.decode() if isinstance(a, bytes) else str(a)) for k, a in f.attrs.items() if k.startswith("note")}}
    return counts, coords


# source packing (scale_factor, add_offset) in source units
SOURCE_PACKING = {"pr": (0.1, 0.0), "tmmx": (0.1, 220.0), "tmmn": (0.1, 210.0), "srad": (0.1, 0.0), "vs": (0.1, 0.0)}


def init(repo: icechunk.Repository, lat: np.ndarray, lon: np.ndarray, notes: dict) -> None:
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=GROUP, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    res = 1 / 24
    dates = pd.date_range(*RECORD, freq="D")
    ds = xr.Dataset(coords={
        "time": ("time", dates, {"standard_name": "time", "axis": "T", "bounds": "time_bnds",
                                 "comment": "gridMET day: see the group's day_window attribute"}),
        "lat": ("lat", lat, {"standard_name": "latitude", "units": "degrees_north", "axis": "Y",
                             "comment": "cell centers as in the source files (1/24 degree)"}),
        "lon": ("lon", lon, {"standard_name": "longitude", "units": "degrees_east", "axis": "X"}),
    })
    ds["time_bnds"] = (("time", "nv"), np.stack([dates.values, (dates + pd.Timedelta(days=1)).values], axis=1))
    ds.attrs = {
        "Conventions": "CF-1.10",
        "title": "gridMET daily surface meteorology, CONUS 1/24 degree (canonical variables)",
        "institution": "University of California Merced / Northwest Knowledge Network",
        "source": f"{gridmet.BASE}<var>_<year>.nc",
        "references": "Abatzoglou, J. T. (2013), Int. J. Climatol. 33, 121-131, doi:10.1002/joc.3413",
        "license": "CC0 1.0",
        "day_window": "calendar day ending at midnight MST (about 07 UTC the next day); see source_notes",
        "source_notes": "; ".join(f"{k}: {v}" for k, v in sorted(notes.items())),
        "history": f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} scripts/gridmet/build_store.py: source uint16 counts "
                   "copied unchanged; CF scale/offset converted to canonical units",
        "comment": "Partial mirror: only some years are written; other days read as missing.",
        "spatial:dimensions": ["lat", "lon"],
        "spatial:transform": [res, 0.0, float(lon[0]) - res / 2, 0.0, -res, float(lat[0]) + res / 2],
        "spatial:shape": [len(lat), len(lon)],
        "spatial:registration": "pixel",
        "proj:code": "EPSG:4326",
    }
    enc = {k: {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"} for k in ("time", "time_bnds")}
    ds.to_zarr(session.store, group=GROUP, mode="w", encoding=enc, consolidated=False, zarr_format=3)
    group = zarr.open_group(session.store, path=GROUP, mode="r+")
    for f in [*gridmet.FIELDS, gridmet.TAS]:
        c = CANONICAL[f.canonical]
        attrs = {"long_name": c.long_name, "units": c.units, "standard_name": c.standard_name,
                 "cell_methods": c.cell_methods, "scale_factor": f.scale, "add_offset": f.offset,
                 "_FillValue": gridmet.FILL, "gridmet_source": f.source}
        if f.canonical == "tas":
            attrs["comment"] = "(tasmax + tasmin) / 2, stored exactly as the sum of the source counts"
        group.create_array(
            f.canonical, shape=(len(dates), len(lat), len(lon)), dtype="uint16", chunks=CHUNKS, shards=SHARDS,
            fill_value=gridmet.FILL, dimension_names=["time", "lat", "lon"], attributes=attrs,
            config={"write_empty_chunks": False}, **codec_kwargs(CODEC, 2),
        )
    session.commit(f"{GROUP}: daily axis {RECORD[0]}..{RECORD[1]}, empty arrays", rebase_with=icechunk.ConflictDetector())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, nargs="+", required=True)
    args = p.parse_args()
    repo = storage.open_mirror(MIRROR, create=True)
    for year in args.years:
        counts, coords = {}, None
        for f in gridmet.FIELDS:
            counts[f.canonical], c = read_counts(f.source, year, f.nc_var, SOURCE_PACKING[f.source])
            if coords is None:
                coords = c
            elif not (np.array_equal(c["lat"], coords["lat"]) and np.array_equal(c["lon"], coords["lon"])
                      and np.array_equal(c["day"], coords["day"])):
                raise ValueError(f"{f.source} {year}: grid or days differ from {gridmet.FIELDS[0].source}")
        mx, mn = counts["tasmax"].astype(np.uint32), counts["tasmin"].astype(np.uint32)
        missing = (mx == gridmet.FILL) | (mn == gridmet.FILL)
        counts["tas"] = np.where(missing, gridmet.FILL, mx + mn).astype(np.uint16)
        assert int((mx + mn)[~missing].max()) < gridmet.FILL
        init(repo, coords["lat"], coords["lon"], coords["note"])
        session = repo.writable_session("main")
        group = zarr.open_group(session.store, path=GROUP, mode="r+")
        i0 = int(coords["day"][0]) - (RECORD[0] - dt.date(1900, 1, 1)).days
        assert np.array_equal(np.diff(coords["day"]), np.ones(len(coords["day"]) - 1)), "days not contiguous"
        for name, a in counts.items():
            group[name][i0 : i0 + a.shape[0]] = a
        session.commit(f"{GROUP}: {year}", rebase_with=icechunk.ConflictDetector())
        print(f"gridmet {year}: {a.shape[0]} days, {len(counts)} variables written", flush=True)


if __name__ == "__main__":
    main()
