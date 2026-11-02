"""Check the subset Icechunk store against the source GeoTIFFs and time typical reads."""

from __future__ import annotations

import argparse
import time

import numpy as np
import rasterio
import rioxarray  # noqa: F401  (registers .rio)

from prism_mirror.catalog import FREQUENCIES, NODATA, VARIABLES, local_zip, sample_dates
from prism_mirror.io import read_grid
from prism_mirror.packing import canonical
from prism_mirror.store import open_prism

from build_store import STORE


def same_bits(a: np.ndarray, b: np.ndarray) -> bool:
    nan = np.isnan(a)
    return bool(np.array_equal(nan, np.isnan(b)) and np.array_equal(a.view(np.uint32)[~nan], b.view(np.uint32)[~nan]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--store", default=str(STORE))
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    args = p.parse_args()
    for fname in args.freq:
        F = FREQUENCIES[fname]
        ds = open_prism(fname, args.store)
        assert all(ds[v].dtype == np.float32 for v in VARIABLES)
        dates = sample_dates(F)
        assert (ds.time.values == dates.values).all(), "time axis mismatch"
        assert ds.rio.crs.to_epsg() == 4269, ds.rio.crs

        # Coordinates vs. the GeoTIFF transform.
        d0 = dates[0].date()
        tif = f"/vsizip/{local_zip('ppt', F, d0)}/{local_zip('ppt', F, d0).stem}.tif"
        with rasterio.open(tif) as src:
            t = src.transform
        lon_ref = t.c + (np.arange(ds.sizes["lon"]) + 0.5) * t.a
        lat_ref = t.f + (np.arange(ds.sizes["lat"]) + 0.5) * t.e
        print(f"[{fname}] max coord diff vs GeoTIFF transform: lon {np.abs(ds.lon.values - lon_ref).max():.2e}, "
              f"lat {np.abs(ds.lat.values - lat_ref).max():.2e} deg")
        assert np.abs(ds.lon.values - lon_ref).max() < 1e-6 and np.abs(ds.lat.values - lat_ref).max() < 1e-6

        # Values: first, a middle and last date of each block, every variable.
        check_idx = sorted({i for k in range(0, len(dates), F.time_chunk) for i in (k, k + F.time_chunk // 2, k + F.time_chunk - 1)})
        for var in VARIABLES:
            da = ds[var]
            packed = "+" in ds.attrs["prism_mirror_codec"]  # cf-* integer packing
            worst = 0.0
            for i in check_idx:
                got = da.isel(time=i).values
                src = read_grid(var, F, dates[i].date()).data
                ref = canonical(src, var) if packed else src
                if not same_bits(ref, got):
                    raise AssertionError(f"{fname}/{var} {dates[i].date()}: values differ from expected")
                ok = ~np.isnan(src)
                worst = max(worst, float(np.abs(got[ok].astype(np.float64) - src[ok]).max(initial=0)))
                assert not (got == np.float32(NODATA)).any()
            print(f"[{fname}] {var}: {len(check_idx)} dates match {'harmonized source' if packed else 'source bit-for-bit'} "
                  f"(max |stored - source| {worst:.2g}); decoded {da.dtype}")

        # Read timing on the local store (no network): one full map vs one pixel's sampled series.
        var = "tmax"
        t0 = time.perf_counter()
        ds[var].isel(time=0).values
        t_map = time.perf_counter() - t0
        t0 = time.perf_counter()
        ds[var].sel(lat=41.31, lon=-72.92, method="nearest").values  # New Haven, CT
        t_series = time.perf_counter() - t0
        print(f"[{fname}] {var}: one full map {t_map:.2f}s, one pixel series ({len(dates)} steps) {t_series:.3f}s")
    print("OK")


if __name__ == "__main__":
    main()
