"""Open the PRISM Icechunk mirror as xarray datasets."""

from __future__ import annotations

from functools import partial
from pathlib import Path

import icechunk
import numpy as np
import xarray as xr
from xarray.coding.common import lazy_elemwise_func

from climate_mirror import storage
from climate_mirror.prism.catalog import VARIABLES


def open_prism(group: str = "daily", store: str | Path | None = None, branch: str = "main") -> xr.Dataset:
    """Open one frequency group ("daily" or "monthly") lazily, with variables as float32.

    Packed variables are CF integers; xarray decodes them to float64 because zarr JSON attributes
    carry a float64 scale_factor. Casting back gives the harmonized float32 values (the float32
    nearest each PRISM decimal value) at half the memory.
    """
    if store is None:  # the mirror configured in stores.toml
        repo = storage.open_mirror("prism")
    else:
        repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store)))
    ds = xr.open_zarr(repo.readonly_session(branch).store, group=group, consolidated=False, chunks=None)
    for var in VARIABLES:
        if var not in ds:
            continue
        v = ds[var].variable
        if v.dtype != np.float32:
            # Lazy elementwise cast: indexing still reaches the store, so a point or one map reads only the chunks it
            # needs. (A dask astype would decode whole dask chunks; a plain astype would load the array.)
            data = lazy_elemwise_func(v._data, partial(np.asarray, dtype=np.float32), np.dtype(np.float32))
            v = xr.Variable(v.dims, data, v.attrs, v.encoding)
        # One dask chunk per shard: the daily group's one-day inner chunks would make ~6 million dask tasks.
        enc = v.encoding
        ds[var] = v.chunk(dict(zip(v.dims, enc.get("shards") or enc["chunks"], strict=True)))
    return ds
