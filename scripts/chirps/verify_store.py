"""Check the native CHIRPS groups of the `chirps` mirror against the source GeoTIFFs and time typical reads.

  uv run python scripts/chirps/verify_store.py                       # the sample chunks
  uv run python scripts/chirps/verify_store.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import rasterio
import xarray as xr

from climate_mirror import storage
from climate_mirror.chirps.catalog import FREQUENCIES, GROUPS, RECORD_END, VARIABLES, local_tif, sample_chunks
from climate_mirror.chirps.io import read_grid
from climate_mirror.packing import canonical


def same_bits(a: np.ndarray, b: np.ndarray) -> bool:
    nan = np.isnan(a)
    return bool(np.array_equal(nan, np.isnan(b)) and np.array_equal(a.view(np.uint32)[~nan], b.view(np.uint32)[~nan]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--start", type=dt.date.fromisoformat, help="check chunks overlapping [start, end] instead of the sample")
    p.add_argument("--end", type=dt.date.fromisoformat)
    args = p.parse_args()
    repo = storage.open_mirror("chirps")
    for fname in args.freq:
        F = FREQUENCIES[fname]
        ds = xr.open_zarr(repo.readonly_session("main").store, group=GROUPS[fname], consolidated=False, chunks={})
        da = ds["precip"].astype(np.float32)
        assert (ds.time.values == F.dates(RECORD_END[fname]).values).all(), "time axis is not the full record"
        chunks = F.chunk_indices(args.start, args.end or args.start) if args.start else sample_chunks(F)
        dates = ds.indexes["time"]
        T = F.time_chunk
        check_idx = sorted({min(i, len(dates) - 1) for c in chunks for i in (c * T, c * T + T // 2, c * T + T - 1)})

        # Coordinates and GeoZarr transform vs. the GeoTIFF (whose pixel size is float32-rounded: compare loosely).
        with rasterio.open(local_tif(F, dates[check_idx[0]].date())) as src:
            t = src.transform
        lon_ref = t.c + (np.arange(ds.sizes["lon"]) + 0.5) * t.a
        lat_ref = t.f + (np.arange(ds.sizes["lat"]) + 0.5) * t.e
        dlon, dlat = np.abs(ds.lon.values - lon_ref).max(), np.abs(ds.lat.values - lat_ref).max()
        print(f"[{fname}] max coord diff vs GeoTIFF transform: lon {dlon:.2e}, lat {dlat:.2e} deg (header float32 rounding)")
        assert dlon < 1e-4 and dlat < 1e-4
        assert np.allclose(ds.attrs["spatial:transform"], [t.a, t.b, t.c, t.d, t.e, t.f], atol=1e-6), "GeoZarr transform"
        assert ds.attrs["spatial:shape"] == [ds.sizes["lat"], ds.sizes["lon"]] and ds.attrs["proj:code"] == "EPSG:4326"

        # Values: first, a middle and last period of each written chunk.
        packed = "+" in ds.attrs["mirror_codec"]
        worst, total_diff, total_src, n = 0.0, 0.0, 0.0, 0
        for i in check_idx:
            src = read_grid(F, dates[i].date())
            got = da.isel(time=i).values
            ref = canonical(src, VARIABLES["precip"].valid_range) if packed else src
            if not same_bits(ref, got):
                raise AssertionError(f"{fname} {dates[i].date()}: values differ from expected")
            ok = ~np.isnan(src)
            diff = got[ok].astype(np.float64) - src[ok]
            worst, total_diff, total_src = max(worst, float(np.abs(diff).max())), total_diff + diff.sum(), total_src + src[ok].sum(dtype=np.float64)
            n += 1
        print(f"[{fname}] precip: {n} periods match {'packed source' if packed else 'source bit-for-bit'} "
              f"(max |stored - source| {worst:.2g} mm; summed change {total_diff / total_src:+.1e} of the total)")
        written = {c * T + k for c in chunks for k in range(T)}
        outside = next(i for i in range(len(dates)) if i not in written)
        assert np.isnan(da.isel(time=outside).values).all(), "unwritten time should read as missing"

        t0 = time.perf_counter()
        da.isel(time=check_idx[0]).values
        t_map = time.perf_counter() - t0
        t0 = time.perf_counter()
        da.sel(lat=-1.29, lon=36.82, method="nearest").values  # Nairobi
        t_series = time.perf_counter() - t0
        print(f"[{fname}] one full map {t_map:.2f}s, one pixel series ({len(dates)} steps) {t_series:.3f}s")
    print("OK")


if __name__ == "__main__":
    main()
