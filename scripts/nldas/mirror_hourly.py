"""Mirror NLDAS-2 hourly data into group `hourly` of the nldas Icechunk repo (stores.toml [mirrors.nldas]).

For each UTC day, downloads the 24 FORA files (all 11 forcing variables) and the 24 Noah soil-moisture subsets
(OPeNDAP, 2 variables) into a temporary directory, writes them as one (24, 224, 464) chunk per variable, checks
the written values against the files, then deletes the files. Encoding (nldas.DECIMALS): decimal int32 counts with
CF scale_factor (harmonized: values off the decimal grid, GRIB binary-scaling noise, move by less than half a
quantum; how many and by how much is recorded in results/nldas/hourly_packing.csv), float32 for Qair; time-last +
pcodec. -9999 -> missing. The hourly
axis covers the full record; unwritten hours read as missing.

    uv run python scripts/nldas/mirror_hourly.py --start 2021-01-01 --end 2021-12-31   # also mirrors 2022-01-01
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import shutil
import time

import h5py
import icechunk
import numpy as np
import pandas as pd
import requests
import xarray as xr
import zarr

from climate_mirror import nldas, storage
from climate_mirror.codecs import codec_kwargs
from climate_mirror.earthdata import EarthdataSession
from climate_mirror.paths import DATA_DIR, RESULTS_DIR

GROUP = "hourly"
TMP = DATA_DIR / "tmp" / "nldas"
TIME_UNITS = "hours since 1979-01-01 00:00:00"  # as in the source files


def init(repo: icechunk.Repository, attrs_by_var: dict[str, dict]) -> None:
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=GROUP, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    times = pd.date_range(nldas.RECORD[0], pd.Timestamp(nldas.RECORD[1]) + pd.Timedelta(hours=23), freq="h")
    lat = nldas.SOUTH + np.arange(nldas.NY) * nldas.RES
    lon = nldas.WEST + np.arange(nldas.NX) * nldas.RES
    ds = xr.Dataset(coords={
        "time": ("time", times, {"standard_name": "time", "axis": "T",
                                 "comment": "file hour: instantaneous fields valid at this time; sums cover the preceding hour"}),
        "lat": ("lat", lat, {"standard_name": "latitude", "units": "degrees_north", "axis": "Y", "comment": "south to north"}),
        "lon": ("lon", lon, {"standard_name": "longitude", "units": "degrees_east", "axis": "X"}),
    })
    r = nldas.RES
    ds.attrs = {
        "Conventions": "CF-1.10",
        "title": "NLDAS-2 hourly primary forcing (FORA0125_H v2.0) and Noah soil moisture (NOAH0125_H v2.0), mirror",
        "source": "NASA GES DISC (Earthdata Cloud): FORA NetCDF files; Noah SoilM via Cloud OPeNDAP subsets",
        "references": nldas.CITATION,
        "history": f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} scripts/nldas/mirror_hourly.py: values stored as "
                   "decimal integers (within 1 ulp of the source float32) or float32; -9999 -> missing",
        "comment": "Partial mirror: only some days are written; other hours read as missing.",
        "spatial:dimensions": ["lat", "lon"],
        "spatial:transform": [r, 0.0, nldas.WEST - r / 2, 0.0, r, nldas.SOUTH - r / 2],
        "spatial:shape": [nldas.NY, nldas.NX],
        "spatial:registration": "pixel",
        "proj:code": "EPSG:4326",
    }
    ds.to_zarr(session.store, group=GROUP, mode="w", consolidated=False, zarr_format=3,
               encoding={"time": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"}})
    group = zarr.open_group(session.store, path=GROUP, mode="r+")
    for v in nldas.FORA_VARS + nldas.NOAH_VARS:
        nd = nldas.DECIMALS[v]
        attrs = dict(attrs_by_var[v])
        if nd is not None:
            attrs.update(scale_factor=10.0**-nd, _FillValue=nldas.INT_FILL)
        group.create_array(
            v, shape=(len(times), nldas.NY, nldas.NX), dtype="float32" if nd is None else "int32",
            chunks=(24, nldas.NY, nldas.NX), fill_value=np.nan if nd is None else nldas.INT_FILL,
            dimension_names=["time", "lat", "lon"], attributes=attrs,
            config={"write_empty_chunks": False}, **codec_kwargs("T-pcodec8", 4),
        )
    session.commit(f"{GROUP}: hourly axis, empty arrays", rebase_with=icechunk.ConflictDetector())


def download(session: EarthdataSession, url: str, dest, params=None, attempts: int = 5) -> None:
    if dest.exists():
        return
    for i in range(attempts):
        # transient failures: 403 from expired CloudFront signatures, HTML error pages with status 200, resets
        try:
            r = session.get(url, params=params, timeout=300)
            ok = r.status_code == 200 and r.content[:8] == b"\x89HDF\r\n\x1a\n"
            problem = f"HTTP {r.status_code} {r.headers.get('content-type')}"
        except requests.RequestException as e:
            ok, problem = False, type(e).__name__
        if ok:
            break
        if i == attempts - 1:
            raise OSError(f"{url.split('?')[0]}: {problem} after {attempts} attempts")  # no signed query strings
        time.sleep(5 * 2**i)
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(r.content)
    with h5py.File(tmp, "r"):  # truncated files fail here
        pass
    tmp.rename(dest)


def read(path, names: list[str], t: dt.datetime) -> tuple[dict[str, np.ndarray], dict[str, dict]]:
    out, attrs = {}, {}
    with h5py.File(path, "r") as f:
        # OPeNDAP has returned a different hour's granule for the first requests of a new session: check the time
        hours = float(np.ravel(f["time"][...])[0])
        if dt.datetime(1979, 1, 1) + dt.timedelta(hours=hours) != t:
            raise ValueError(f"{path.name}: time {hours} h since 1979-01-01 is not {t}")
        assert np.allclose(f["lat"][...], nldas.SOUTH + np.arange(nldas.NY) * nldas.RES)
        assert np.allclose(f["lon"][...], nldas.WEST + np.arange(nldas.NX) * nldas.RES)
        for n in names:
            v = f[n]
            a = v[0].astype(np.float32)
            fill = float(np.asarray(v.attrs.get("_FillValue", nldas.FILL)).ravel()[0])
            out[n] = np.where(a == fill, np.float32(np.nan), a)
            attrs[n] = {k: (x.decode() if isinstance(x, bytes) else str(x)) for k, x in v.attrs.items()
                        if k in ("units", "long_name", "standard_name", "cell_methods")}
    return out, attrs


STATS: dict[str, dict[str, float]] = {}


def encode(name: str, x: np.ndarray) -> np.ndarray:
    """Stored representation of float32 values (NaN = missing), accumulating harmonization statistics."""
    nd = nldas.DECIMALS[name]
    if nd is None:
        return x
    ok = np.isfinite(x)
    k = np.round(x.astype(np.float64) * 10**nd)
    back = (k * 10.0**-nd).astype(np.float32)
    d = (back - x)[ok].astype(np.float64)
    moved = np.abs(d) > np.spacing(np.abs(x[ok]))  # more than 1 ulp
    s = STATS.setdefault(name, {"values": 0, "moved_gt_1ulp": 0, "max_abs_change": 0.0, "sum_change": 0.0})
    s["values"] += int(ok.sum())
    s["moved_gt_1ulp"] += int(moved.sum())
    s["max_abs_change"] = max(s["max_abs_change"], float(np.abs(d).max(initial=0)))
    s["sum_change"] += float(d.sum())
    return np.where(ok, k, nldas.INT_FILL).astype(np.int32)


def write_stats(start: dt.date, end: dt.date) -> None:
    out = RESULTS_DIR / "nldas" / "hourly_packing.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = pd.DataFrame([{"variable": n, "decimals": nldas.DECIMALS[n], **s,
                          "mean_change": s["sum_change"] / max(s["values"], 1), "start": start, "end": end}
                         for n, s in STATS.items()]).drop(columns="sum_change")
    if out.exists():
        rows = pd.concat([pd.read_csv(out), rows])
    rows.to_csv(out, index=False, float_format="%.3g")


def day_files(day: dt.date) -> list[tuple[str, object, dict | None]]:
    jobs = []
    for h in range(24):
        t = dt.datetime.combine(day, dt.time(h))
        jobs.append((nldas.fora_url(t), TMP / f"fora_{t:%Y%m%d%H}.nc", None))
        jobs.append((nldas.noah_url(t), TMP / f"noah_{t:%Y%m%d%H}.nc4",
                     {"dap4.ce": ";".join(f"/{v}" for v in nldas.NOAH_VARS + ["lat", "lon", "time"])}))
    return jobs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--batch-days", type=int, default=4, help="days per download batch and commit")
    p.add_argument("--force", action="store_true", help="rewrite days that are already written")
    args = p.parse_args()
    TMP.mkdir(parents=True, exist_ok=True)
    http = EarthdataSession(pool=args.workers)
    repo = storage.open_mirror("nldas", create=True)
    t_axis0 = pd.Timestamp(nldas.RECORD[0])

    # plus the day after --end: daily sums for the last day need its 00 UTC hour
    days = [d.date() for d in pd.date_range(args.start, args.end + dt.timedelta(days=1), freq="D")]
    # skip days already written (resumable)
    try:
        g = zarr.open_group(repo.readonly_session("main").store, path=GROUP, mode="r")
        tair = g["Tair"]  # a land cell (37.6 N, 87.4 W); unwritten chunks read as the fill value
        done = {d for d in days if tair[int((pd.Timestamp(d) - t_axis0) / pd.Timedelta(hours=1)), 100, 300] != tair.fill_value}
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        done = set()
    todo = days if args.force else [d for d in days if d not in done]
    print(f"{len(days)} days, {len(done)} already written, {len(todo)} to do", flush=True)

    # log in once (URS redirects, cookies) before requests run in parallel
    download(http, *day_files(todo[0])[1]) if todo else None
    with cf.ThreadPoolExecutor(args.workers) as pool:
        for b in range(0, len(todo), args.batch_days):
            batch = todo[b : b + args.batch_days]
            t0 = time.time()
            jobs = [j for d in batch for j in day_files(d)]
            list(pool.map(lambda j: download(http, *j), jobs))
            t1 = time.time()
            session = repo.writable_session("main")
            for d in batch:
                hours = [dt.datetime.combine(d, dt.time(h)) for h in range(24)]
                fora = [read(TMP / f"fora_{t:%Y%m%d%H}.nc", nldas.FORA_VARS, t) for t in hours]
                noah = [read(TMP / f"noah_{t:%Y%m%d%H}.nc4", nldas.NOAH_VARS, t) for t in hours]
                if b == 0 and d == batch[0]:
                    init(repo, {**fora[0][1], **noah[0][1]})
                    session = repo.writable_session("main")
                group = zarr.open_group(session.store, path=GROUP, mode="r+")
                i0 = int((pd.Timestamp(d) - t_axis0) / pd.Timedelta(hours=1))
                for src, names in ((fora, nldas.FORA_VARS), (noah, nldas.NOAH_VARS)):
                    for n in names:
                        block = encode(n, np.stack([hour[0][n] for hour in src]))
                        group[n][i0 : i0 + 24] = block
                        back = group[n][i0 : i0 + 24]
                        if not np.array_equal(back, block, equal_nan=block.dtype.kind == "f"):
                            raise AssertionError(f"{n} {d}: written values differ from the source")
            session.commit(f"{GROUP}: {batch[0]}..{batch[-1]}", rebase_with=icechunk.ConflictDetector())
            for _, dest, _ in jobs:
                dest.unlink(missing_ok=True)
            mb = sum(1 for _ in jobs)
            print(f"{batch[0]}..{batch[-1]}: {mb} files in {t1 - t0:.0f}s, written in {time.time() - t1:.0f}s", flush=True)
    shutil.rmtree(TMP, ignore_errors=True)
    if STATS:
        write_stats(todo[0], todo[-1])
        for n, st in STATS.items():
            print(f"  {n}: {st['moved_gt_1ulp'] / max(st['values'], 1):.2%} moved > 1 ulp, max |change| "
                  f"{st['max_abs_change']:.3g}, mean change {st['sum_change'] / max(st['values'], 1):.3g}")


if __name__ == "__main__":
    main()
