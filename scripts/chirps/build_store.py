"""Build or extend the native CHIRPS v3 groups (`pentads`, `dekads`, `monthly`) of the `chirps` mirror
(location from stores.toml, [mirrors.chirps]; the same repo also holds `daily` and `common_0p25/daily`).

Each group holds `precip` on (time, lat, lon) over the **full record** (1981- through catalog.RECORD_END).
Only the whole time chunks selected here are written (--sample and/or --start/--end); everything else reads as
missing and costs no storage, so the repo grows into a full mirror in place.

Values: the undeclared -9999 ocean fill becomes missing. With an integer codec (cf-uint/cf-int32) values are
rounded to the nearest 1e-4 mm and stored as integers (CF scale_factor/_FillValue); see climate_mirror/packing.py
and results/chirps/rounding_analysis.csv for the effect. Metadata: CF-1.10 plus GeoZarr group attributes.

  uv run python scripts/chirps/build_store.py --sample
  uv run python scripts/chirps/build_store.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt

import icechunk
import numpy as np
import xarray as xr
import zarr

from climate_mirror import storage
from climate_mirror.chirps import GRID
from climate_mirror.chirps.catalog import (
    BASE_URL, FREQUENCIES, GROUPS, RECORD_END, VARIABLES, Frequency, sample_chunks,
)
from climate_mirror.chirps.io import read_grid
from climate_mirror.codecs import CODEC_NAMES, codec_kwargs, split_name
from climate_mirror.packing import SCALE, cf_attrs, pack

MIRROR = "chirps"
TIME_UNITS = "days since 1981-01-01"
VAR = "precip"
PACKED_COMMENT = (
    f"Stored as integers in units of {SCALE:g} mm (CF scale_factor/_FillValue): source float32 values are rounded "
    f"to the nearest {SCALE:g} mm (|change| <= {SCALE / 2:g} mm, unbiased; see the mirror's rounding analysis)."
)
CITATION = (
    "Climate Hazards Center, UC Santa Barbara: CHIRPS v3.0, https://www.chc.ucsb.edu/data/chirps3 "
    "(see that page for the citation and terms of use)."
)


def coordinate_dataset(freq: Frequency) -> xr.Dataset:
    dates = freq.dates(RECORD_END[freq.name])
    lat, lon, r = GRID.lat, GRID.lon, GRID.res
    period = {"pentad": "pentad (days 1-5, 6-10, 11-15, 16-20, 21-25, 26-end of month)",
              "dekad": "dekad (days 1-10, 11-20, 21-end of month)", "monthly": "calendar month"}[freq.name]
    return xr.Dataset(
        coords={
            "time": ("time", dates, {"standard_name": "time", "axis": "T", "bounds": "time_bnds",
                                      "comment": f"Start of each {period}; time_bnds give the interval."}),
            "lat": ("lat", lat, {"standard_name": "latitude", "long_name": "latitude of pixel center",
                                 "units": "degrees_north", "axis": "Y", "bounds": "lat_bnds",
                                 "comment": "Rows run north to south, as in the source grids."}),
            "lon": ("lon", lon, {"standard_name": "longitude", "long_name": "longitude of pixel center",
                                 "units": "degrees_east", "axis": "X", "bounds": "lon_bnds"}),
            "crs": xr.DataArray(np.int32(0), attrs={"grid_mapping_name": "latitude_longitude",
                                                    "semi_major_axis": 6378137.0, "inverse_flattening": 298.257223563,
                                                    "geographic_crs_name": "WGS 84", "epsg_code": "EPSG:4326"}),
        },
        data_vars={
            "time_bnds": (("time", "nv"), np.stack([dates.values, freq.ends(dates).values], axis=1)),
            "lat_bnds": (("lat", "nv"), np.stack([lat + r / 2, lat - r / 2], axis=1)),
            "lon_bnds": (("lon", "nv"), np.stack([lon - r / 2, lon + r / 2], axis=1)),
        },
    )


def group_attrs(freq: Frequency, codec: str) -> dict:
    return {
        "Conventions": "CF-1.10",
        "title": f"CHIRPS v3.0 {freq.name} precipitation, 0.05 degree, 60N-60S land",
        "institution": "Climate Hazards Center, UC Santa Barbara",
        "source": f"{BASE_URL}/{GROUPS[freq.name]}/global/tifs/ (GeoTIFF)",
        "references": "https://www.chc.ucsb.edu/data/chirps3",
        "acknowledgement": CITATION,
        "history": (
            f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} created by scripts/chirps/build_store.py: -9999 fill -> "
            "missing; pixel-center coordinates computed exactly from 0.05 degree spacing (the GeoTIFF pixel size is "
            "float32-rounded); values rounded to 1e-4 mm when an integer codec is used."
        ),
        "comment": "Partial mirror: only some whole time chunks are written; other times read as missing.",
        "mirror_codec": codec,
        **GRID.geozarr(),
    }


def var_attrs(packing: str | None) -> tuple[np.dtype, object, dict]:
    meta = VARIABLES[VAR]
    attrs = {"long_name": meta.long_name, "units": meta.units, "standard_name": meta.standard_name,
             "cell_methods": "time: sum", "grid_mapping": "crs"}
    if not packing:
        return np.dtype("float32"), np.nan, attrs
    dtype, pack_attrs = cf_attrs(meta.valid_range, packing)
    # zarr v3 readers (xarray) mask on the CF _FillValue attribute, not on the array fill_value.
    attrs |= {"_FillValue": int(pack_attrs["_FillValue"]), "scale_factor": pack_attrs["scale_factor"],
              "comment": PACKED_COMMENT}
    if "add_offset" in pack_attrs:
        attrs["add_offset"] = pack_attrs["add_offset"]
    return dtype, pack_attrs["_FillValue"], attrs


def init_group(repo: icechunk.Repository, freq: Frequency, codec: str) -> None:
    """Create the group (full time axis, coordinates, empty `precip`) if it does not exist yet."""
    path = GROUPS[freq.name]
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=path, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    ds = coordinate_dataset(freq)
    ds.attrs = group_attrs(freq, codec)
    enc = {k: {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"} for k in ("time", "time_bnds")}
    ds.to_zarr(session.store, group=path, mode="w", encoding=enc, consolidated=False, zarr_format=3)
    group = zarr.open_group(session.store, path=path, mode="r+")
    dtype, fill, attrs = var_attrs(split_name(codec)[0])
    group.create_array(
        VAR, shape=(ds.sizes["time"], GRID.ny, GRID.nx), dtype=dtype,
        chunks=(freq.time_chunk, freq.space_chunk, freq.space_chunk), fill_value=fill,
        dimension_names=["time", "lat", "lon"], attributes=attrs, config={"write_empty_chunks": False},
        **codec_kwargs(codec, dtype.itemsize),
    )
    session.commit(f"{path}: full-record time axis through {RECORD_END[freq.name]}, empty precip ({codec})",
                   rebase_with=icechunk.ConflictDetector())


def write_chunks(repo: icechunk.Repository, freq: Frequency, chunk_indices: list[int]) -> None:
    path = GROUPS[freq.name]
    for ci in chunk_indices:  # one commit per time chunk keeps memory to one block (~1.2 GB)
        session = repo.writable_session("main")
        group = zarr.open_group(session.store, path=path, mode="r+")
        arr = group[VAR]
        packing = split_name(group.attrs["mirror_codec"])[0]
        i0, i1 = ci * freq.time_chunk, min((ci + 1) * freq.time_chunk, arr.shape[0])
        dates = freq.chunk_dates(ci)[: i1 - i0]
        block = np.stack([read_grid(freq, d.date()) for d in dates])
        if packing:
            block, _ = pack(block, VARIABLES[VAR].valid_range, packing, label=f"{path} {ci}")  # raises if > SCALE/2 + 1 ulp
        arr[i0:i1] = block
        session.commit(f"{path}/{VAR}: write time chunk {ci} ({dates[0].date()}..{dates[-1].date()})",
                       rebase_with=icechunk.ConflictDetector())
        print(f"  wrote {path}/{VAR} chunk {ci} ({dates[0].date()}..{dates[-1].date()})", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--codec", default="cf-uint+pcodec8", choices=CODEC_NAMES, help="only used when creating groups")
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--sample", action="store_true", help="write the representative sample chunks")
    p.add_argument("--start", type=dt.date.fromisoformat, help="write whole chunks overlapping [start, end]")
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--drop", action="store_true", help="delete these groups first (to rebuild with another codec)")
    args = p.parse_args()
    zarr.config.set({"threading.max_workers": 18, "async.concurrency": 64})

    repo = storage.open_mirror(MIRROR, create=True)
    for fname in args.freq:
        freq = FREQUENCIES[fname]
        if args.drop:
            session = repo.writable_session("main")
            root = zarr.open_group(session.store, mode="r+")
            if GROUPS[fname] in root:
                del root[GROUPS[fname]]
                session.commit(f"drop {GROUPS[fname]}", rebase_with=icechunk.ConflictDetector())
        init_group(repo, freq, args.codec)
        chunks = set(sample_chunks(freq)) if args.sample else set()
        if args.start:
            chunks |= set(freq.chunk_indices(args.start, args.end or args.start))
        if chunks:
            print(f"{fname}: writing chunks {sorted(chunks)}", flush=True)
            write_chunks(repo, freq, sorted(chunks))


if __name__ == "__main__":
    main()
