"""Build or extend the PRISM 800m Icechunk mirror (location from stores.toml, [mirrors.prism]).

Layout: groups `daily/` and `monthly/`, each with the PRISM variables on (time, lat, lon) over the
**full record** (daily 1981-, monthly 1895- through catalog.RECORD_END). Only the whole time chunks
selected here are written (--sample and/or --start/--end); everything else reads as missing and
costs no storage, so the repo grows into a full mirror in place.

Values: -9999 becomes missing. With an integer codec (cf-uint/cf-int32) values are stored as
harmonized decimal integers (CF scale_factor/add_offset/_FillValue); see climate_mirror/packing.py.
Metadata: CF-1.10 plus GeoZarr (spatial:*, proj:code) group attributes for map clients.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import zipfile

import icechunk
import numpy as np
import pandas as pd
import xarray as xr
import zarr
from rasterio.crs import CRS

from climate_mirror import storage
from climate_mirror.codecs import CODEC_NAMES, codec_kwargs, split_name
from climate_mirror.packing import cf_attrs, pack
from climate_mirror.prism.catalog import (
    BASE_URL, FREQUENCIES, NORTH, NX, NY, RECORD_END, RES, VARIABLES, WEST, Frequency, local_zip, sample_chunks,
)
from climate_mirror.prism.io import lat_centers, lon_centers, read_grid

MIRROR = "prism"
TIME_UNITS = "days since 1895-01-01"
INFO_FIELDS = {
    "PRISM_DATASET_TYPE": "prism_dataset_type",
    "PRISM_DATASET_VERSION": "prism_dataset_version",
    "PRISM_DATASET_CREATE_DATE": "prism_dataset_create_date",
}
INFO_DTYPE = "<U16"
HARMONIZED_COMMENT = (
    "Stored as integer decimal values (CF scale_factor/add_offset). PRISM source grids encode the same "
    "decimal values in float32 in slightly different ways (float32(k/1000) vs float32(k)*float32(0.001)); "
    "decoding here yields one consistent float32 per decimal value, within 1 ulp (<=1.2e-7 relative) "
    "of the source float32. Unrounded source values are rounded to the nearest 1e-4."
)
CITATION = (
    "PRISM Group, Oregon State University, https://prism.oregonstate.edu. "
    "See https://prism.oregonstate.edu/terms/ for terms of use and required acknowledgement."
)


def read_info(var: str, freq: Frequency, d: dt.date) -> dict[str, str]:
    with zipfile.ZipFile(local_zip(var, freq, d)) as z:
        name = next((n for n in z.namelist() if n.endswith(".info.txt")), None)
        text = z.read(name).decode() if name else ""
    return {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in text.splitlines() if ":" in l)}


def coordinate_dataset(freq: Frequency, dates: pd.DatetimeIndex, variables: list[str]) -> xr.Dataset:
    lat, lon = lat_centers(), lon_centers()
    wkt = CRS.from_epsg(4269).to_wkt()
    crs = xr.DataArray(
        np.int32(0),
        attrs={
            "grid_mapping_name": "latitude_longitude",
            "longitude_of_prime_meridian": 0.0,
            "semi_major_axis": 6378137.0,
            "inverse_flattening": 298.257222101,
            "geographic_crs_name": "NAD83",
            "horizontal_datum_name": "North American Datum 1983",
            "crs_wkt": wkt,
            "spatial_ref": wkt,
            "GeoTransform": f"{WEST!r} {RES!r} 0 {NORTH!r} 0 {-RES!r}",
        },
    )
    period = "day ending 12:00 UTC on the labelled date" if freq.name == "daily" else "calendar month"
    ds = xr.Dataset(
        coords={
            "time": ("time", dates, {"standard_name": "time", "axis": "T", "bounds": "time_bnds",
                                      "comment": f"Each value is the {period}; time_bnds give the interval."}),
            "lat": ("lat", lat, {"standard_name": "latitude", "long_name": "latitude of pixel center",
                                 "units": "degrees_north", "axis": "Y", "bounds": "lat_bnds",
                                 "comment": "Rows run north to south, as in the source grids."}),
            "lon": ("lon", lon, {"standard_name": "longitude", "long_name": "longitude of pixel center",
                                 "units": "degrees_east", "axis": "X", "bounds": "lon_bnds"}),
            "crs": crs,
        },
        data_vars={
            "time_bnds": (("time", "nv"), np.stack([dates.values, freq.ends(dates).values], axis=1)),
            "lat_bnds": (("lat", "nv"), np.stack([lat + RES / 2, lat - RES / 2], axis=1)),
            "lon_bnds": (("lon", "nv"), np.stack([lon - RES / 2, lon + RES / 2], axis=1)),
        },
    )
    # Per-grid PRISM provenance (dataset version / creation date), filled in as chunks are written.
    for var in variables:
        for name in INFO_FIELDS.values():
            ds.coords[f"{var}_{name}"] = ("time", np.full(len(dates), "", dtype=INFO_DTYPE))
    return ds


def group_attrs(freq: Frequency, codec: str) -> dict:
    return {
        "Conventions": "CF-1.10",
        "title": f"PRISM 800m (30 arc-second) {freq.name} climate grids, CONUS",
        "institution": "PRISM Group, Oregon State University",
        "source": f"{BASE_URL} (COG grid packages)",
        "references": "https://prism.oregonstate.edu/documents/PRISM_datasets.pdf",
        "acknowledgement": CITATION,
        "history": (
            f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} created by scripts/prism/build_store.py: "
            "-9999 nodata -> missing; pixel-center coordinates computed exactly from 1/120 degree spacing; "
            "values harmonized to exact decimal integers when an integer codec is used."
        ),
        "comment": "Partial mirror: only some whole time chunks are written; other times read as missing.",
        "mirror_codec": codec,
        # GeoZarr (zarr-conventions spatial + geo-proj) for map clients; affine in rasterio order (a, b, c, d, e, f).
        "spatial:dimensions": ["lat", "lon"],
        "spatial:transform": [RES, 0.0, WEST, 0.0, -RES, NORTH],
        "spatial:shape": [NY, NX],
        "spatial:registration": "pixel",
        "proj:code": "EPSG:4269",
    }


def var_attrs(var: str, freq: Frequency, packing: str | None) -> tuple[np.dtype, object, dict]:
    meta = VARIABLES[var]
    attrs = {
        "long_name": meta.long_name,
        "units": meta.units,
        "cell_methods": meta.daily_cell_method if freq.name == "daily" else meta.monthly_cell_method,
        "grid_mapping": "crs",
        "coordinates": " ".join(f"{var}_{n}" for n in INFO_FIELDS.values()),
    }
    if meta.standard_name:
        attrs["standard_name"] = meta.standard_name
    if not packing:
        return np.dtype("float32"), np.nan, attrs
    dtype, pack_attrs = cf_attrs(meta.valid_range, packing)
    # zarr v3 readers (xarray) mask on the CF _FillValue attribute, not on the array fill_value.
    attrs["_FillValue"] = int(pack_attrs["_FillValue"])
    attrs["scale_factor"] = pack_attrs["scale_factor"]
    if "add_offset" in pack_attrs:
        attrs["add_offset"] = pack_attrs["add_offset"]
    attrs["comment"] = HARMONIZED_COMMENT
    return dtype, pack_attrs["_FillValue"], attrs


def init_group(repo: icechunk.Repository, freq: Frequency, codec: str) -> None:
    """Create the group (full time axis, coordinates, empty variables) if it does not exist yet."""
    session = repo.writable_session("main")
    try:
        zarr.open_group(session.store, path=freq.name, mode="r")
        return
    except (FileNotFoundError, zarr.errors.GroupNotFoundError):
        pass
    variables = list(VARIABLES)
    dates = freq.dates(RECORD_END[freq.name])
    ds = coordinate_dataset(freq, dates, variables)
    ds.attrs = group_attrs(freq, codec)
    encoding = {
        "time": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"},
        "time_bnds": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"},
    }
    ds.to_zarr(session.store, group=freq.name, mode="w", encoding=encoding, consolidated=False, zarr_format=3)
    group = zarr.open_group(session.store, path=freq.name, mode="r+")
    packing, _ = split_name(codec)
    for var in variables:
        dtype, fill, attrs = var_attrs(var, freq, packing)
        group.create_array(
            var,
            shape=(len(dates), NY, NX),
            dtype=dtype,
            chunks=(freq.time_chunk, freq.space_chunk, freq.space_chunk),
            fill_value=fill,
            dimension_names=["time", "lat", "lon"],
            attributes=attrs,
            config={"write_empty_chunks": False},
            **codec_kwargs(codec, dtype.itemsize),
        )
    session.commit(f"{freq.name}: full-record time axis {dates[0].date()}..{dates[-1].date()}, empty variables ({codec})")


def write_chunks(repo: icechunk.Repository, freq: Frequency, var: str, chunk_indices: list[int]) -> None:
    session = repo.writable_session("main")
    group = zarr.open_group(session.store, path=freq.name, mode="r+")
    arr = group[var]
    packing, _ = split_name(group.attrs["mirror_codec"])
    meta = VARIABLES[var]
    n = arr.shape[0]
    for ci in chunk_indices:
        i0, i1 = ci * freq.time_chunk, min((ci + 1) * freq.time_chunk, n)
        dates = freq.chunk_dates(ci)[: i1 - i0]
        block = np.stack([read_grid(var, freq, d.date()).data for d in dates])
        if packing:
            block, _ = pack(block, meta.valid_range, packing, label=var)  # raises if a value would move > SCALE/2 + 1 ulp
        arr[i0:i1] = block
        infos = [read_info(var, freq, d.date()) for d in dates]
        for key, name in INFO_FIELDS.items():
            group[f"{var}_{name}"][i0:i1] = np.array([i.get(key, "") for i in infos], dtype=INFO_DTYPE)
    session.commit(f"{freq.name}/{var}: write time chunks {chunk_indices}")
    print(f"  wrote {freq.name}/{var}: {len(chunk_indices)} chunks", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--codec", default="cf-uint+pcodec8", choices=CODEC_NAMES, help="only used when creating groups")
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--vars", nargs="*", default=list(VARIABLES))
    p.add_argument("--sample", action="store_true", help="write the representative sample chunks")
    p.add_argument("--start", type=dt.date.fromisoformat, help="write whole chunks overlapping [start, end]")
    p.add_argument("--end", type=dt.date.fromisoformat)
    p.add_argument("--overwrite", action="store_true", help="delete a local mirror first")
    args = p.parse_args()
    zarr.config.set({"threading.max_workers": 18, "async.concurrency": 64})

    if args.overwrite:
        path = storage.local_path(MIRROR)
        if path is None:
            raise SystemExit("--overwrite only deletes local mirrors")
        shutil.rmtree(path, ignore_errors=True)
    repo = storage.open_mirror(MIRROR, create=True)
    for fname in args.freq:
        freq = FREQUENCIES[fname]
        init_group(repo, freq, args.codec)
        chunks = set(sample_chunks(freq)) if args.sample else set()
        if args.start:
            chunks |= set(freq.chunk_indices(args.start, args.end or args.start))
        if not chunks:
            continue
        print(f"{fname}: writing chunks {sorted(chunks)}", flush=True)
        for var in args.vars:
            write_chunks(repo, freq, var, sorted(chunks))


if __name__ == "__main__":
    main()
