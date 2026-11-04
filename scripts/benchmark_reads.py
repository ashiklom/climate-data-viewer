"""Cold-read benchmark of every store the comparison site and the mirrors use, from this machine.

For each source: open time (repo/store + metadata), one native-resolution map, and one point time series (2021 and,
where cheap enough, the full record), with chunks touched and compressed bytes fetched. Every repeat opens a fresh
repo/store (no in-process cache); local stores still benefit from the OS page cache. Reads go through zarr-python
(async concurrency 64), as the derive/regrid scripts do; xarray adds little on top.

  uv run python scripts/benchmark_reads.py            # writes results/read_benchmark.csv
"""

from __future__ import annotations

import argparse
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr
import zarr
from zarr.core.sync import sync
from zarr.storage import FsspecStore

from climate_mirror import credentials, era5land, storage
from climate_mirror.chunkstats import fetched_bytes
from climate_mirror.paths import RESULTS_DIR

POINT = (41.31, -72.93)  # New Haven
DAY = pd.Timestamp("2021-07-15")
YEAR = (pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31T23"))
REPEATS = 3


@dataclass
class Source:
    name: str
    location: str  # local / remote
    opener: Callable[[], tuple[object, str | None]]  # -> (zarr store, group)
    var: str
    role: str  # map / series
    hourly: bool = False
    full_record: bool = True
    lon360: bool = False


def mirror(name: str, group: str):
    return lambda: (storage.open_mirror(name).readonly_session("main").store, group)


def external(name: str, group: str | None):
    return lambda: (storage.open_external(name).readonly_session("main").store, group)


def http(url: str, headers: dict | None = None):
    opts = {"client_kwargs": {"headers": headers}} if headers else {}
    return lambda: (FsspecStore.from_url(url, read_only=True, storage_options=opts), None)


power = storage.config()["external"]
arco = era5land.ARCO["pressure-precipitation"]
cds = credentials.cds_headers()
SOURCES = [
    Source("PRISM daily (our mirror)", "local", mirror("prism", "daily"), "ppt", "map+series"),
    Source("CHIRPS pentads (our native mirror)", "local", mirror("chirps", "pentads"), "precip", "map+series"),
    Source("CHIRPS daily (our map copy of dynamical)", "local", mirror("chirps", "daily"), "pr", "map"),
    Source("CHIRPS daily (dynamical, Earthmover)", "remote", external("chirps_dynamical", None),
           "precipitation_surface", "series"),
    Source("ERA5 daily (our derived mirror)", "local", mirror("era5", "daily"), "pr", "map"),
    Source("ERA5 hourly spatial (Earthmover)", "remote", external("era5_earthmover", "single/spatial"), "tp", "map",
           hourly=True, lon360=True),
    Source("ERA5 hourly temporal (Earthmover)", "remote", external("era5_earthmover", "single/temporal"), "tp",
           "series", hourly=True, lon360=True),
    Source("ERA5-Land daily (our derived mirror)", "local", mirror("era5land", "daily"), "pr", "map"),
    Source("ERA5-Land hourly timeChunked (ARCO)", "remote", http(arco["time"], cds), "tp", "map", hourly=True),
    Source("ERA5-Land hourly geoChunked (ARCO)", "remote", http(arco["geo"], cds), "tp", "series", hourly=True),
    Source("MERRA-2 daily spatial (POWER)", "remote", http(power["merra2_power"]["spatial_url"]), "PRECTOTCORR", "map"),
    Source("MERRA-2 daily temporal (POWER)", "remote", http(power["merra2_power"]["temporal_url"]), "PRECTOTCORR",
           "series"),
    Source("IMERG daily spatial (POWER)", "remote", http(power["imerg_power"]["spatial_url"]), "IMERG_PRECTOT", "map"),
    Source("IMERG daily temporal (POWER)", "remote", http(power["imerg_power"]["temporal_url"]), "IMERG_PRECTOT",
           "series"),
    Source("Common 0.25 deg daily (our mirrors)", "local", mirror("merra2", "common_0p25/daily"), "pr", "map+series"),
]


def coords(store, group):
    ds = xr.open_zarr(store, group=group, consolidated=not group and isinstance(store, FsspecStore),
                      chunks=None, decode_times=True)
    names = {d: next(n for n in (d, {"lat": "latitude", "lon": "longitude", "time": "valid_time"}[d]) if n in ds.coords)
             for d in ("time", "lat", "lon")}
    return ds[names["time"]].values, ds[names["lat"]].values, ds[names["lon"]].values


def timed(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def bench(src: Source) -> list[dict]:
    store, group = src.opener()
    t, lat, lon = coords(store, group)
    t = pd.DatetimeIndex(t)
    j_lat = int(np.abs(lat - POINT[0]).argmin())
    j_lon = int(np.abs(lon - (POINT[1] % 360 if src.lon360 else POINT[1])).argmin())
    i_day = int(t.searchsorted(DAY + (pd.Timedelta(hours=12) if src.hourly else pd.Timedelta(0))))
    if not src.hourly and t[min(i_day, len(t) - 1)] != DAY:  # pentads: the period containing DAY
        i_day = int(t.searchsorted(DAY, side="right")) - 1
    y0, y1 = int(t.searchsorted(YEAR[0])), int(t.searchsorted(YEAR[1], side="right"))
    tasks = []
    if "map" in src.role:
        tasks.append(("map (one time step)", (i_day, slice(None), slice(None))))
    if "series" in src.role:
        tasks.append(("series 2021", (slice(y0, y1), j_lat, j_lon)))
        if src.full_record:
            tasks.append(("series full record", (slice(None), j_lat, j_lon)))

    rows = []
    for task, sel in tasks:
        times, opens = [], []
        n = 1 if task == "series full record" and src.location == "remote" else REPEATS
        for _ in range(n):
            t0 = time.perf_counter()
            store, group = src.opener()
            arr = zarr.open_array(store, path=f"{group}/{src.var}" if group else src.var, mode="r")
            opens.append(time.perf_counter() - t0)
            times.append(timed(lambda a=arr, s=sel: np.asarray(a[s])))
        n_chunks, nbytes = sync(fetched_bytes(arr, sel))  # zarr's event loop, which owns HTTP sessions
        values = int(np.prod([len(range(*s.indices(d))) if isinstance(s, slice) else 1 for s, d in zip(sel, arr.shape)]))
        rows.append({
            "source": src.name, "location": src.location, "task": task, "var": src.var,
            "array_chunks": "x".join(map(str, arr.chunks)), "values": values, "chunks_read": n_chunks,
            "mb_fetched": nbytes / 1e6, "mb_decoded": n_chunks * int(np.prod(arr.chunks)) * arr.dtype.itemsize / 1e6,
            "open_s": statistics.median(opens), "read_s_median": statistics.median(times), "read_s_min": min(times),
            "repeats": n,
        })
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", help="substrings of source names to run (results merged into the CSV)")
    args = p.parse_args()
    zarr.config.set({"async.concurrency": 64, "threading.max_workers": 16})
    rows = []
    for src in SOURCES:
        if args.only and not any(o in src.name for o in args.only):
            continue
        try:
            rows += bench(src)
        except Exception as e:  # noqa: BLE001 - keep going; report the failure
            print(f"FAILED {src.name}: {e!r}", flush=True)
    df = pd.DataFrame(rows)
    out = RESULTS_DIR / "read_benchmark.csv"
    if args.only and out.exists():  # replace only the re-run sources
        old = pd.read_csv(out)
        df = pd.concat([old[~old.source.isin(df.source)], df]).set_index("source").loc[
            [s.name for s in SOURCES if s.name in set(old.source) | set(df.source)]].reset_index()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, float_format="%.4g")
    print(df.to_string(float_format=lambda v: f"{v:.3g}"))


if __name__ == "__main__":
    main()
