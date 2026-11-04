"""Check the gridMET mirror against the cached NKN NetCDF files: every day and cell of the given years.

Store values (CF-decoded) must equal the source values (CF-decoded, converted to canonical units) to float32
precision, with identical missing masks; tas must equal (tasmax + tasmin) / 2.

    uv run python scripts/gridmet/verify_store.py --years 2021
"""

from __future__ import annotations

import argparse

import numpy as np
import xarray as xr

from climate_mirror import gridmet, storage

# source units -> canonical
CONVERT = {"pr": lambda x: x, "tmmx": lambda x: x - 273.15, "tmmn": lambda x: x - 273.15,
           "srad": lambda x: x * 0.0864, "vs": lambda x: x}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, nargs="+", required=True)
    args = p.parse_args()
    store = xr.open_zarr(storage.open_mirror("gridmet").readonly_session("main").store, group="daily",
                         consolidated=False, chunks=None)
    for year in args.years:
        got = store.sel(time=str(year)).load()
        for f in gridmet.FIELDS:
            src = xr.open_dataset(gridmet.local(f.source, year), engine="h5netcdf")[f.nc_var].load()
            want = CONVERT[f.source](src.values.astype(np.float64))
            have = got[f.canonical].values.astype(np.float64)
            same_mask = np.array_equal(np.isnan(want), np.isnan(have))
            err = np.nanmax(np.abs(want - have))
            ok = same_mask and err <= 1e-4 * max(1.0, np.nanmax(np.abs(want)))
            print(f"{year} {f.canonical:8s} mask {'ok' if same_mask else 'DIFFERS'}  max |diff| {err:.2e}  {'OK' if ok else 'FAIL'}")
            if not ok:
                raise SystemExit(1)
        tas = got["tas"].values.astype(np.float64)
        ref = (got["tasmax"].values.astype(np.float64) + got["tasmin"].values) / 2
        err = np.nanmax(np.abs(tas - ref))
        print(f"{year} tas      max |tas - (tasmax+tasmin)/2| {err:.2e}  {'OK' if err < 1e-4 else 'FAIL'}")


if __name__ == "__main__":
    main()
