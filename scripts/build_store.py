"""Build the native Icechunk store holding the representative PRISM 800m sample.

Layout: groups `daily/` and `monthly/`, each with the 9 PRISM variables on (time, lat, lon).
The time axis is compact (only the sampled dates), and each sampled block fills exactly
one time chunk. Coordinates and attributes follow CF-1.10; -9999 is stored as NaN (float
codecs) or as the integer _FillValue of a CF-packed array (cf-uint/cf-int32 codecs). Packed
arrays hold harmonized decimal values: CF readers get the float32 nearest each decimal value,
within 1 ulp of the source float32 (see prism_mirror/packing.py).
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

from prism_mirror.catalog import (
    BASE_URL, DATA_DIR, FREQUENCIES, NX, NY, RES, VARIABLES, Frequency, local_zip, sample_chunks, sample_dates,
)
from prism_mirror.codecs import CODEC_NAMES, codec_kwargs, split_name
from prism_mirror.io import lat_centers, lon_centers, read_grid
from prism_mirror.packing import cf_attrs, pack

STORE = DATA_DIR / "prism_subset.icechunk"
TIME_UNITS = "days since 1895-01-01"
INFO_FIELDS = {
    "PRISM_DATASET_TYPE": "prism_dataset_type",
    "PRISM_DATASET_VERSION": "prism_dataset_version",
    "PRISM_DATASET_CREATE_DATE": "prism_dataset_create_date",
}
HARMONIZED_COMMENT = (
    "Stored as integer decimal values (CF scale_factor/add_offset). PRISM source grids encode the same "
    "decimal values in float32 in slightly different ways (float32(k/1000) vs float32(k)*float32(0.001)); "
    "decoding here yields one consistent float32 per decimal value, within 1 ulp (<=1.2e-7 relative) "
    "of the source float32."
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


def time_bounds(freq: Frequency, dates: pd.DatetimeIndex) -> np.ndarray:
    end = dates + (pd.Timedelta(days=1) if freq.name == "daily" else pd.offsets.MonthBegin(1))
    return np.stack([dates.values, end.values], axis=1)


def coordinate_dataset(freq: Frequency, dates: pd.DatetimeIndex) -> xr.Dataset:
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
            "GeoTransform": f"{lon[0] - RES / 2!r} {RES!r} 0 {lat[0] + RES / 2!r} 0 {-RES!r}",
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
            "time_bnds": (("time", "nv"), time_bounds(freq, dates)),
            "lat_bnds": (("lat", "nv"), np.stack([lat + RES / 2, lat - RES / 2], axis=1)),
            "lon_bnds": (("lon", "nv"), np.stack([lon - RES / 2, lon + RES / 2], axis=1)),
        },
    )
    return ds


def global_attrs(freq: Frequency, codec: str) -> dict:
    return {
        "Conventions": "CF-1.10",
        "title": f"PRISM 800m (30 arc-second) {freq.name} climate grids, CONUS - representative subset",
        "institution": "PRISM Group, Oregon State University",
        "source": f"{BASE_URL} (COG grid packages)",
        "references": "https://prism.oregonstate.edu/documents/PRISM_datasets.pdf",
        "acknowledgement": CITATION,
        "history": (
            f"{dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ} converted from PRISM COGs by prism_mirror/build_store.py: "
            "-9999 nodata -> NaN; pixel-center coordinates recomputed exactly from 1/120 degree spacing; "
            "values harmonized to exact decimal integers when an integer codec is used."
        ),
        "comment": "Subset: only whole sampled time chunks are present; the time axis is not contiguous.",
        "prism_mirror_codec": codec,
    }


def build_group(repo: icechunk.Repository, freq: Frequency, variables: list[str], codec: str) -> None:
    dates = sample_dates(freq)
    chunks = (freq.time_chunk, freq.space_chunk, freq.space_chunk)

    session = repo.writable_session("main")
    ds = coordinate_dataset(freq, dates)
    ds.attrs = global_attrs(freq, codec)
    # Per-grid PRISM provenance (dataset version / creation date) as auxiliary time coordinates.
    for key, name in INFO_FIELDS.items():
        for var in variables:
            vals = [read_info(var, freq, d.date()).get(key, "") for d in dates]
            ds.coords[f"{var}_{name}"] = ("time", np.array(vals, dtype="U"))
    encoding = {
        "time": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"},
        "time_bnds": {"units": TIME_UNITS, "calendar": "proleptic_gregorian", "dtype": "int32"},
    }
    ds.to_zarr(session.store, group=freq.name, mode="w", encoding=encoding, consolidated=False, zarr_format=3)
    session.commit(f"{freq.name}: coordinates ({codec})")

    packing, _ = split_name(codec)
    for var in variables:
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

        dtype, fill = np.dtype("float32"), np.nan
        if packing:
            dtype, pack_attrs = cf_attrs(var, packing)
            fill = pack_attrs["_FillValue"]
            # zarr v3 readers (xarray) mask on the CF _FillValue attribute, not on the array fill_value.
            attrs["_FillValue"] = int(fill)
            attrs["scale_factor"] = pack_attrs["scale_factor"]
            if "add_offset" in pack_attrs:
                attrs["add_offset"] = pack_attrs["add_offset"]
            attrs["comment"] = HARMONIZED_COMMENT

        session = repo.writable_session("main")
        group = zarr.open_group(session.store, path=freq.name, mode="r+")
        arr = group.create_array(
            var,
            shape=(len(dates), NY, NX),
            dtype=dtype,
            chunks=chunks,
            fill_value=fill,
            dimension_names=["time", "lat", "lon"],
            attributes=attrs,
            config={"write_empty_chunks": False},
            **codec_kwargs(codec, dtype.itemsize),
        )
        for k, ci in enumerate(sample_chunks(freq)):
            block = np.stack([read_grid(var, freq, d.date()).data for d in freq.chunk_dates(ci)])
            if packing:
                block, _ = pack(block, var, packing)  # raises if any value would move > 1 ulp
            arr[k * freq.time_chunk : (k + 1) * freq.time_chunk] = block
        session.commit(f"{freq.name}/{var}: write {len(dates)} sampled time steps")
        print(f"  wrote {freq.name}/{var} ({arr.dtype})", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--codec", default="cf-uint+pcodec8", choices=CODEC_NAMES)
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--vars", nargs="*", default=list(VARIABLES))
    p.add_argument("--store", default=str(STORE))
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()
    zarr.config.set({"threading.max_workers": 18, "async.concurrency": 64})

    if args.overwrite:
        shutil.rmtree(args.store, ignore_errors=True)
    storage = icechunk.local_filesystem_storage(args.store)
    repo = icechunk.Repository.open_or_create(storage)
    for fname in args.freq:
        print(f"building {fname} with {args.codec}", flush=True)
        build_group(repo, FREQUENCIES[fname], args.vars, args.codec)


if __name__ == "__main__":
    main()
