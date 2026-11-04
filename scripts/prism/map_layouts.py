"""Compare PRISM daily chunk layouts for map-heavy use (the website) against the mirror's 32x256x256 layout.

Copies two 32-day blocks of 2021 (January, July) of `ppt` and `tmean` from the mirror's `daily` group, as the
packed integers (no re-rounding), into scratch Zarr stores with each candidate layout, then reports storage per
day and the requests and bytes for typical reads (from stored chunk sizes, shard-index aware):

- whole-CONUS map of one day; a zoomed map (about 1 x 1.5 degrees around New Haven) of one day;
- one point series for a year (scaled from the 64 sampled days) and for the full record (scaled likewise).

`overviews` keeps the 32-day native array for series and zoomed maps and adds one-day-chunk overview levels
(4x and 16x coarser, means of the finite native cells) for wide maps.

  uv run python scripts/prism/map_layouts.py      # results/prism/map_layouts.csv
"""

from __future__ import annotations

import shutil

import numpy as np
import pandas as pd
import zarr
from zarr.core.sync import sync

from climate_mirror import storage
from climate_mirror.chunkstats import fetched_bytes
from climate_mirror.codecs import codec_kwargs
from climate_mirror.packing import decode, pack
from climate_mirror.paths import REPO_ROOT, RESULTS_DIR
from climate_mirror.prism.catalog import VARIABLES

SCRATCH = REPO_ROOT / "data" / "scratch" / "prism_map_layouts"
VARS = ["ppt", "tmean"]
BLOCK_DATES = ["2021-01-01", "2021-07-15"]  # the 32-day mirror chunks containing these dates
N_RECORD = 16741  # days in the full daily record (1981-)
OVERVIEW_FACTORS = [4, 16]
POINT = (41.31, -72.93)
ZOOM_BOX = (40.8, 41.8, -73.7, -72.2)  # lat0, lat1, lon0, lon1

# name -> (chunks, shards)
LAYOUTS = {
    "32x256x256 (mirror)": ((32, 256, 256), None),
    "8x256x256": ((8, 256, 256), None),
    "1x256x256": ((1, 256, 256), None),
    "1x512x512": ((1, 512, 512), None),
    "shards 32x512x512 of 1x256x256": ((1, 256, 256), (32, 512, 512)),
}


def create(store, name: str, shape, dtype, chunks, shards, attrs) -> zarr.Array:
    """Packed uint32 + pcodec8, as in the mirror; with `shards`, pcodec applies inside each inner chunk."""
    return zarr.create_array(store, name=name, shape=shape, dtype=dtype, chunks=chunks, shards=shards,
                             fill_value=np.iinfo(np.uint32).max, attributes=attrs,
                             **codec_kwargs("cf-uint+pcodec8", 4))


def coarsen(packed: np.ndarray, attrs: dict, factor: int, var: str) -> np.ndarray:
    """Mean of the finite native cells in each factor x factor block (NaN where none), re-packed."""
    x = decode(packed, attrs).astype(np.float64)
    t, ny, nx = x.shape
    py, px = -ny % factor, -nx % factor
    x = np.pad(x, ((0, 0), (0, py), (0, px)), constant_values=np.nan)
    x = x.reshape(t, (ny + py) // factor, factor, (nx + px) // factor, factor)
    with np.errstate(invalid="ignore"):
        n = np.isfinite(x).sum(axis=(2, 4))
        m = np.where(n > 0, np.nansum(x, axis=(2, 4)) / np.maximum(n, 1), np.nan)
    return pack(m.astype(np.float32), VARIABLES[var].valid_range, "cf-uint", label=f"{var} /{factor}")[0]


def index_of(coord: np.ndarray, x: float) -> int:
    return int(np.abs(coord - x).argmin())


def main() -> None:
    zarr.config.set({"async.concurrency": 64, "threading.max_workers": 16})
    src = zarr.open_group(storage.open_mirror("prism").readonly_session("main").store, path="daily", mode="r")
    times = src["time"][:]  # days since the group's epoch
    units = src["time"].attrs["units"].split(" since ")[1]
    t = pd.Timestamp(units) + pd.to_timedelta(times, unit="D")
    lat, lon = src["lat"][:], src["lon"][:]
    blocks = [(int(t.searchsorted(pd.Timestamp(d))) // 32) * 32 for d in BLOCK_DATES]
    n_days = 32 * len(blocks)

    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    stores = {name: zarr.storage.LocalStore(SCRATCH / f"{k}.zarr") for k, name in enumerate(LAYOUTS)}
    ov_store = zarr.storage.LocalStore(SCRATCH / "overviews.zarr")
    rows = []
    for var in VARS:
        a = src[var]
        attrs = dict(a.attrs)
        data = np.concatenate([a[b : b + 32] for b in blocks])  # packed uint32
        shape = data.shape
        arrays = {}
        for name, (chunks, shards) in LAYOUTS.items():
            arrays[name] = create(stores[name], var, shape, data.dtype, chunks, shards, attrs)
            arrays[name][:] = data
        levels = {}
        for f in OVERVIEW_FACTORS:
            c = coarsen(data, attrs, f, var)
            levels[f] = create(ov_store, f"{var}_{f}", c.shape, c.dtype, (1, 256, 256), None, attrs)
            levels[f][:] = c

        # Selections (sampled time indices: one day per block for maps; all 64 days for the series).
        y, x = index_of(lat, POINT[0]), index_of(lon, POINT[1])
        zy = sorted(index_of(lat, v) for v in ZOOM_BOX[:2])
        zx = sorted(index_of(lon, v) for v in ZOOM_BOX[2:])
        maps = [(i, slice(None), slice(None)) for i in (0, 32 + 15)]
        zooms = [(i, slice(zy[0], zy[1] + 1), slice(zx[0], zx[1] + 1)) for i in (0, 32 + 15)]
        series = (slice(None), y, x)

        def cost(arr, sels):
            res = [sync(fetched_bytes(arr, s)) for s in sels]
            return np.mean([r[0] for r in res]), np.mean([r[1] for r in res]) / 1e6

        def total_mb(arr):
            return sync(fetched_bytes(arr, tuple(slice(None) for _ in arr.shape)))[1] / 1e6

        base = arrays["32x256x256 (mirror)"]
        for name, arr in arrays.items():
            m_req, m_mb = cost(arr, maps)
            z_req, z_mb = cost(arr, zooms)
            s_req, s_mb = cost(arr, [series])
            rows.append({"var": var, "layout": name, "storage_mb_per_day": total_mb(arr) / n_days,
                         "map_requests": m_req, "map_mb": m_mb, "zoom_requests": z_req, "zoom_mb": z_mb,
                         "series_year_requests": s_req * 365 / n_days, "series_year_mb": s_mb * 365 / n_days,
                         "series_record_requests": s_req * N_RECORD / n_days, "series_record_mb": s_mb * N_RECORD / n_days})
        # mirror layout + overviews: wide maps from the 16x level, zoomed maps and series from the native array
        ov_mb = sum(total_mb(lv) for lv in levels.values()) / n_days
        m_req, m_mb = cost(levels[16], [(i, slice(None), slice(None)) for i in (0, 47)])
        m4_req, m4_mb = cost(levels[4], [(i, slice(None), slice(None)) for i in (0, 47)])
        z_req, z_mb = cost(base, zooms)
        s_req, s_mb = cost(base, [series])
        rows.append({"var": var, "layout": "mirror + overviews 4x,16x (1-day chunks)",
                     "storage_mb_per_day": total_mb(base) / n_days + ov_mb,
                     "map_requests": m_req, "map_mb": m_mb, "zoom_requests": z_req, "zoom_mb": z_mb,
                     "series_year_requests": s_req * 365 / n_days, "series_year_mb": s_mb * 365 / n_days,
                     "series_record_requests": s_req * N_RECORD / n_days, "series_record_mb": s_mb * N_RECORD / n_days,
                     "map_4x_requests": m4_req, "map_4x_mb": m4_mb})
        for r in rows[-len(arrays) - 1 :]:
            print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, flush=True)

    df = pd.DataFrame(rows)
    base = df[df.layout == "32x256x256 (mirror)"].set_index("var").storage_mb_per_day
    df["storage_vs_mirror"] = df.storage_mb_per_day / df["var"].map(base)
    RESULTS_DIR.joinpath("prism").mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_DIR / "prism" / "map_layouts.csv", index=False, float_format="%.4g")
    print(df.drop(columns=["map_4x_requests", "map_4x_mb"]).to_string(float_format=lambda v: f"{v:.3g}"))


if __name__ == "__main__":
    main()
