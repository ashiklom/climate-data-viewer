"""Check the PRISM Icechunk mirror against the source GeoTIFFs and time typical reads."""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import rasterio
import rioxarray  # noqa: F401  (registers .rio)

from climate_mirror.prism.catalog import FREQUENCIES, NODATA, RECORD_END, VARIABLES, local_zip, sample_chunks
from climate_mirror.prism.io import read_grid
from climate_mirror.packing import canonical
from climate_mirror.prism.store import open_prism


def same_bits(a: np.ndarray, b: np.ndarray) -> bool:
    nan = np.isnan(a)
    return bool(np.array_equal(nan, np.isnan(b)) and np.array_equal(a.view(np.uint32)[~nan], b.view(np.uint32)[~nan]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--store", help="local store path (default: the mirror in stores.toml)")
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--start", type=dt.date.fromisoformat, help="check chunks overlapping [start, end] instead of the sample")
    p.add_argument("--end", type=dt.date.fromisoformat)
    args = p.parse_args()
    for fname in args.freq:
        F = FREQUENCIES[fname]
        ds = open_prism(fname, args.store)
        assert all(ds[v].dtype == np.float32 for v in VARIABLES)
        assert (ds.time.values == F.dates(RECORD_END[fname]).values).all(), "time axis is not the full record"
        assert ds.rio.crs.to_epsg() == 4269, ds.rio.crs
        chunks = F.chunk_indices(args.start, args.end or args.start) if args.start else sample_chunks(F)
        dates = ds.indexes["time"]

        T = F.time_chunk
        check_idx = sorted({min(i, len(dates) - 1) for c in chunks for i in (c * T, c * T + T // 2, c * T + T - 1)})
        # Coordinates vs. the GeoTIFF transform.
        d0 = dates[check_idx[0]].date()
        tif = f"/vsizip/{local_zip('ppt', F, d0)}/{local_zip('ppt', F, d0).stem}.tif"
        with rasterio.open(tif) as src:
            t = src.transform
        lon_ref = t.c + (np.arange(ds.sizes["lon"]) + 0.5) * t.a
        lat_ref = t.f + (np.arange(ds.sizes["lat"]) + 0.5) * t.e
        print(f"[{fname}] max coord diff vs GeoTIFF transform: lon {np.abs(ds.lon.values - lon_ref).max():.2e}, "
              f"lat {np.abs(ds.lat.values - lat_ref).max():.2e} deg")
        assert np.abs(ds.lon.values - lon_ref).max() < 1e-6 and np.abs(ds.lat.values - lat_ref).max() < 1e-6
        a, b, c, d, e, f = ds.attrs["spatial:transform"]
        assert np.allclose([a, b, c, d, e, f], [t.a, t.b, t.c, t.d, t.e, t.f], atol=1e-9), "GeoZarr transform"
        assert ds.attrs["spatial:shape"] == [ds.sizes["lat"], ds.sizes["lon"]] and ds.attrs["proj:code"] == "EPSG:4269"

        # Values: first, a middle and last date of each written chunk, every variable with source files.
        # Values: first, a middle and last date of each written chunk, every variable with source files.
        packed = "+" in ds.attrs["mirror_codec"]  # cf-* integer packing
        for var in VARIABLES:
            da = ds[var]
            worst, n = 0.0, 0
            for i in check_idx:
                if not local_zip(var, F, dates[i].date()).exists():
                    continue
                n += 1
                got = da.isel(time=i).values
                src = read_grid(var, F, dates[i].date()).data
                ref = canonical(src, VARIABLES[var].valid_range) if packed else src
                if not same_bits(ref, got):
                    raise AssertionError(f"{fname}/{var} {dates[i].date()}: values differ from expected")
                ok = ~np.isnan(src)
                worst = max(worst, float(np.abs(got[ok].astype(np.float64) - src[ok]).max(initial=0)))
                assert not (got == np.float32(NODATA)).any()
            if n:
                print(f"[{fname}] {var}: {n} dates match {'harmonized source' if packed else 'source bit-for-bit'} "
                      f"(max |stored - source| {worst:.2g}); decoded {da.dtype}")
        written = {c * T + k for c in chunks for k in range(T)}
        outside = next(i for i in range(len(dates)) if i not in written)
        assert np.isnan(ds["ppt"].isel(time=outside).values).all(), "unwritten time should read as missing"

        # Read timing on the local store (no network): one full map vs one pixel's full-record series.
        var = "tmax"
        t0 = time.perf_counter()
        ds[var].isel(time=check_idx[0]).values
        t_map = time.perf_counter() - t0
        t0 = time.perf_counter()
        ds[var].sel(lat=41.31, lon=-72.92, method="nearest").values  # New Haven, CT
        t_series = time.perf_counter() - t0
        print(f"[{fname}] {var}: one full map {t_map:.2f}s, one pixel series ({len(dates)} steps) {t_series:.3f}s")
    print("OK")


if __name__ == "__main__":
    main()
