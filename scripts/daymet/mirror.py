"""Mirror Daymet V4R1 daily CONUS data into group `daily` of the daymet Icechunk repo (stores.toml).

For each variable and 32-day window, fetches only the (10, 300, 300) HDF5 chunks of the remote NetCDF file that lie
inside the CONUS window (HTTP Range), decodes them here (shuffle + deflate),
and writes the window as int32 counts of 0.01 (-9999 -> missing). Values off the 0.01 grid (float32 noise) move by
less than half a quantum; how many and by how much is recorded in results/daymet/packing.csv. No source file is
kept on disk. Store layout: one-day 256 x 256 chunks in 32 x 1024 x 1024 shards on the native full grid.

Sources (identical files): `--source ornl` (default): ORNL DAAC via Earthdata login; ranged reads go to a signed
CloudFront URL (re-signed when it expires), chunk offsets come from the file's DMR++ index. `--source gdex`: NCAR GDEX,
anonymous, chunk offsets from the HDF5 B-tree (slow) and its server throttles parallel connections.

    uv run python scripts/daymet/mirror.py --year 2021
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import io
import re
import time
import zlib

import h5py
import icechunk
import numpy as np
import pandas as pd
import requests
import xarray as xr
import zarr
from numcodecs import Shuffle
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from climate_mirror import daymet, storage
from climate_mirror.codecs import codec_kwargs
from climate_mirror.earthdata import EarthdataSession
from climate_mirror.paths import RESULTS_DIR

GROUP = "daily"
TIME_UNITS = "days since 1980-01-01"
CHUNKS, SHARDS = (1, 256, 256), (32, 1024, 1024)
WINDOW = 32
SRC_T = 10  # source chunk length in days


def http_session(pool: int) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=8, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    s.mount("https://", HTTPAdapter(pool_connections=pool, pool_maxsize=pool, max_retries=retry))
    return s


class RangeFile(io.RawIOBase):
    """Read-only file over HTTP Range requests with a block cache. (GDEX's Content-Range omits the total size,
    which fsspec relies on.)"""

    def __init__(self, http: requests.Session, url: str, block: int = 4 << 20):
        self.http, self.url, self.block, self.pos = http, url, block, 0
        r = http.get(url, headers={"Range": "bytes=0-0"}, timeout=60)
        r.raise_for_status()
        total = r.headers.get("content-range", "*").rsplit("/", 1)[-1]
        if total == "*":  # GDEX omits the total; HEAD has it (signed CloudFront URLs reject HEAD instead)
            h = http.head(url, timeout=60, allow_redirects=True)
            h.raise_for_status()
            total = h.headers["content-length"]
        self.size = int(total)
        self.cache: dict[int, bytes] = {}

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def _block(self, i: int) -> bytes:
        if i not in self.cache:
            lo, hi = i * self.block, min((i + 1) * self.block, self.size) - 1
            r = self.http.get(self.url, headers={"Range": f"bytes={lo}-{hi}"}, timeout=120)
            r.raise_for_status()
            assert len(r.content) == hi - lo + 1
            self.cache[i] = r.content
        return self.cache[i]

    def readinto(self, buf) -> int:
        n = min(len(buf), self.size - self.pos)
        out, done = memoryview(buf), 0
        while done < n:
            i, off = divmod(self.pos + done, self.block)
            piece = self._block(i)[off : off + n - done]
            out[done : done + len(piece)] = piece
            done += len(piece)
        self.pos += n
        return n


ORNL = "https://data.ornldaac.earthdata.nasa.gov/protected/daymet/Daymet_Daily_V4R1/data/daymet_v4_daily_na_{var}_{year}.nc"


class Signed:
    """A source URL whose data is read from a signed redirect target (Earthdata -> CloudFront), re-signed on age."""

    def __init__(self, edl, url: str, max_age: float = 1800):
        self.edl, self.src, self.max_age, self.at, self.url = edl, url, max_age, 0.0, ""
        self.refresh()

    def refresh(self) -> None:
        r = self.edl.get(self.src, headers={"Range": "bytes=0-0"}, timeout=120)
        r.raise_for_status()
        self.url, self.at = r.url, time.time()

    def get(self) -> str:
        if time.time() - self.at > self.max_age:
            self.refresh()
        return self.url


class Plain:
    def __init__(self, url: str):
        self.url = url

    def get(self) -> str:
        return self.url

    def refresh(self) -> None:
        pass


def dmrpp_index(edl, url: str, var: str) -> tuple[dict[tuple[int, int, int], tuple[int, int]], int]:
    """Chunk offsets for the CONUS window from the file's DMR++ sidecar, and the number of days."""
    r = edl.get(url + ".dmrpp", timeout=300)
    r.raise_for_status()
    text = r.text
    ndays = int(re.search(r'<Dimension name="time" size="(\d+)"/>', text).group(1))
    block = text[text.index(f'<Float32 name="{var}">') :]
    block = block[: block.index("</Float32>")]
    head = re.search(r"<dmrpp:chunks ([^>]*)>", block).group(1)
    assert 'compressionType="shuffle deflate"' in head, head
    assert re.search(r"<dmrpp:chunkDimensionSizes>10 300 300<", block)
    index = {}
    for m in re.finditer(r'offset="(\d+)" nBytes="(\d+)" chunkPositionInArray="\[(\d+),(\d+),(\d+)\]"', block):
        t, y, x = int(m.group(3)), int(m.group(4)), int(m.group(5))
        if daymet.WINDOW_Y[0] <= y < daymet.WINDOW_Y[1] and daymet.WINDOW_X[0] <= x < daymet.WINDOW_X[1]:
            index[(t, y, x)] = (int(m.group(1)), int(m.group(2)))
    return index, ndays


def chunk_index(http: requests.Session, url: str, var: str) -> tuple[dict[tuple[int, int, int], tuple[int, int]], dict, np.ndarray]:
    """{(t, y, x) chunk origin: (byte offset, size)} for the CONUS window, the variable's attributes, yearday."""
    f = RangeFile(http, url)
    index: dict[tuple[int, int, int], tuple[int, int]] = {}
    with h5py.File(f, "r") as h5:
        d = h5[var]
        assert d.chunks == (SRC_T, 300, 300) and d.dtype == np.float32, (d.chunks, d.dtype)
        assert d.shape[1:] == (daymet.NY, daymet.NX), d.shape
        assert np.isclose(h5["x"][0], daymet.X0) and np.isclose(h5["y"][0], daymet.Y0)
        filters = list(d._filters)
        assert filters == ["shuffle", "gzip"], filters  # HDF5 deflate (zlib stream)

        def keep(info):
            t, y, x = info.chunk_offset
            if daymet.WINDOW_Y[0] <= y < daymet.WINDOW_Y[1] and daymet.WINDOW_X[0] <= x < daymet.WINDOW_X[1]:
                assert info.filter_mask == 0
                index[(t, y, x)] = (info.byte_offset, info.size)

        d.id.chunk_iter(keep)
        attrs = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in d.attrs.items()
                 if k in ("long_name", "units", "cell_methods")}
        yearday = h5["yearday"][...]
    return index, attrs, yearday


def fetch_block(http: requests.Session, src: Signed | Plain, index: dict, t0: int, pool: cf.Executor) -> np.ndarray:
    """Source days [t0, t0+10) over the CONUS window as float32 with NaN for missing."""
    wy, wx = daymet.WINDOW_Y, daymet.WINDOW_X
    out = np.full((SRC_T, wy[1] - wy[0], wx[1] - wx[0]), np.nan, dtype=np.float32)
    unshuffle = Shuffle(elementsize=4)

    def one(key):
        off, size = index[key]
        for attempt in range(4):
            r = http.get(src.get(), headers={"Range": f"bytes={off}-{off + size - 1}"}, timeout=120)
            if r.status_code != 403 or attempt == 3:
                break
            src.refresh()  # expired signature
        r.raise_for_status()
        if len(r.content) != size:
            raise OSError(f"short read {len(r.content)} != {size}")
        a = np.frombuffer(unshuffle.decode(zlib.decompress(r.content)), dtype="<f4").reshape(SRC_T, 300, 300)
        _, y, x = key
        out[:, y - wy[0] : y - wy[0] + 300, x - wx[0] : x - wx[0] + 300] = np.where(a == daymet.SOURCE_FILL, np.nan, a)
        return size

    keys = [k for k in index if k[0] == t0]
    nbytes = sum(pool.map(one, keys))
    fetch_block.bytes += nbytes
    return out


fetch_block.bytes = 0
STATS: dict[str, dict[str, float]] = {}


def encode(var: str, x: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x)
    k = np.round(x.astype(np.float64) * 10**daymet.DECIMALS)
    back = (k * 10.0**-daymet.DECIMALS).astype(np.float32)
    d = (back - x)[ok].astype(np.float64)
    s = STATS.setdefault(var, {"values": 0, "moved_gt_1ulp": 0, "max_abs_change": 0.0, "sum_change": 0.0})
    s["values"] += int(ok.sum())
    s["moved_gt_1ulp"] += int((np.abs(d) > np.spacing(np.abs(x[ok]))).sum())
    s["max_abs_change"] = max(s["max_abs_change"], float(np.abs(d).max(initial=0)))
    s["sum_change"] += float(d.sum())
    return np.where(ok, k, daymet.INT_FILL).astype(np.int32)


def init(repo: icechunk.Repository, attrs_by_var: dict[str, dict]) -> None:
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=GROUP, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    dates = pd.date_range(*daymet.RECORD, freq="D")
    x = daymet.X0 + np.arange(daymet.NX) * daymet.RES
    y = daymet.Y0 - np.arange(daymet.NY) * daymet.RES
    crs = xr.DataArray(np.int32(0), attrs={
        "grid_mapping_name": "lambert_conformal_conic", "standard_parallel": [25.0, 60.0],
        "longitude_of_central_meridian": -100.0, "latitude_of_projection_origin": 42.5,
        "false_easting": 0.0, "false_northing": 0.0, "semi_major_axis": 6378137.0,
        "inverse_flattening": 298.257223563, "crs_wkt": daymet.crs_wkt(), "proj4": daymet.PROJ4})
    ds = xr.Dataset(coords={
        "time": ("time", dates, {"standard_name": "time", "axis": "T",
                                 "comment": "calendar date; in leap years Daymet has no December 31 (missing here)"}),
        "y": ("y", y, {"standard_name": "projection_y_coordinate", "units": "m", "axis": "Y"}),
        "x": ("x", x, {"standard_name": "projection_x_coordinate", "units": "m", "axis": "X"}),
        "crs": crs,
    })
    r = daymet.RES
    ds.attrs = {
        "Conventions": "CF-1.10",
        "title": "Daymet V4 R1 daily surface weather, 1 km, North America grid (CONUS window written)",
        "source": "NetCDF files from NCAR GDEX d682806 (https://data.gdex.ucar.edu/d682806/), identical to ORNL DAAC",
        "references": daymet.CITATION,
        "license": "CC BY 4.0",
        "day_window": "24-hour day based on local time",
        "history": f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} scripts/daymet/mirror.py: CONUS source chunks "
                   "copied, -9999 -> missing, values stored as int32 counts of 0.01",
        "comment": "Partial mirror: only the CONUS window (source chunk rows 12-23, columns 6-26) of some years is "
                   "written; everything else reads as missing.",
        "spatial:dimensions": ["y", "x"],
        "spatial:transform": [r, 0.0, daymet.X0 - r / 2, 0.0, -r, daymet.Y0 + r / 2],
        "spatial:shape": [daymet.NY, daymet.NX],
        "spatial:registration": "pixel",
        "proj:wkt2": daymet.crs_wkt(),
    }
    ds.to_zarr(session.store, group=GROUP, mode="w", consolidated=False, zarr_format=3,
               encoding={"time": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"}})
    group = zarr.open_group(session.store, path=GROUP, mode="r+")
    for v in daymet.VARIABLES:
        units, long_name = daymet.VARIABLES[v]
        a = {"units": units, "long_name": long_name, **attrs_by_var.get(v, {}), "grid_mapping": "crs",
             "scale_factor": 10.0**-daymet.DECIMALS, "_FillValue": daymet.INT_FILL}
        group.create_array(
            v, shape=(len(dates), daymet.NY, daymet.NX), dtype="int32", chunks=CHUNKS, shards=SHARDS,
            fill_value=daymet.INT_FILL, dimension_names=["time", "y", "x"], attributes=a,
            config={"write_empty_chunks": False}, **codec_kwargs("pcodec8", 4),
        )
    session.commit(f"{GROUP}: daily axis {daymet.RECORD[0]}..{daymet.RECORD[1]}, empty arrays",
                   rebase_with=icechunk.ConflictDetector())


def written(repo: icechunk.Repository, var: str, i0: int) -> bool:
    """Whether day index i0 of `var` holds data at a Kansas land cell (38.5 N, 98 W)."""
    try:
        a = zarr.open_group(repo.readonly_session("main").store, path=GROUP, mode="r")[var]
    except (FileNotFoundError, zarr.errors.GroupNotFoundError, KeyError):
        return False
    return a[i0, 5406, 4727] != a.fill_value


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--vars", nargs="*", default=list(daymet.VARIABLES))
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--source", choices=["ornl", "gdex"], default="ornl")
    args = p.parse_args()
    repo = storage.open_mirror("daymet", create=True)
    http = http_session(args.workers)
    year0 = (dt.date(args.year, 1, 1) - daymet.RECORD[0]).days
    with cf.ThreadPoolExecutor(args.workers) as pool:
        for var in args.vars:
            t = time.time()
            if args.source == "ornl":
                edl = EarthdataSession()
                url = ORNL.format(var=var, year=args.year)
                index, ndays = dmrpp_index(edl, url, var)
                src = Signed(edl, url)
                attrs = {}
            else:
                url = daymet.url(var, args.year)
                index, attrs, yearday = chunk_index(http, url, var)
                ndays = len(yearday)
                assert np.array_equal(yearday, np.arange(1, ndays + 1)), "yearday not 1..N"
                src = Plain(url)
            print(f"{var}: {len(index)} CONUS chunks, {sum(s for _, s in index.values()) / 1e9:.2f} GB, index in "
                  f"{time.time() - t:.0f}s", flush=True)
            init(repo, {var: attrs})
            blocks: dict[int, np.ndarray] = {}
            for w0 in range(0, ndays, WINDOW):
                w1 = min(w0 + WINDOW, ndays)
                if written(repo, var, year0 + w0) and written(repo, var, year0 + w1 - 1):
                    continue
                t = time.time()
                b0 = fetch_block.bytes
                parts = []
                for s0 in range(w0 // SRC_T * SRC_T, w1, SRC_T):
                    if s0 not in blocks:
                        blocks[s0] = fetch_block(http, src, index, s0, pool)
                    blk = blocks[s0]
                    parts.append(blk[max(w0 - s0, 0) : min(w1 - s0, SRC_T)])
                for s0 in [s for s in blocks if s + SRC_T <= w1]:  # keep only a block that straddles w1
                    del blocks[s0]
                data = encode(var, np.concatenate(parts))
                session = repo.writable_session("main")
                arr = zarr.open_group(session.store, path=GROUP, mode="r+")[var]
                wy, wx = daymet.WINDOW_Y, daymet.WINDOW_X
                # yearday n is January 1 + n - 1 (Daymet drops December 31 in leap years)
                arr[year0 + w0 : year0 + w1, wy[0] : wy[1], wx[0] : wx[1]] = data
                session.commit(f"{GROUP}/{var}: {args.year} days {w0 + 1}..{w1}", rebase_with=icechunk.ConflictDetector())
                print(f"  {var} days {w0 + 1}..{w1}: {(fetch_block.bytes - b0) / 1e6:.0f} MB in {time.time() - t:.0f}s",
                      flush=True)
    if STATS:
        out = RESULTS_DIR / "daymet" / "packing.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = pd.DataFrame([{"variable": n, "year": args.year, **s, "mean_change": s["sum_change"] / max(s["values"], 1)}
                             for n, s in STATS.items()]).drop(columns="sum_change")
        if out.exists():
            rows = pd.concat([pd.read_csv(out), rows])
        rows.to_csv(out, index=False, float_format="%.3g")
        print(rows.to_string(index=False))


if __name__ == "__main__":
    main()
