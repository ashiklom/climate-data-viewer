"""Open the PRISM Icechunk mirror as xarray datasets."""

from __future__ import annotations

from pathlib import Path

import icechunk
import numpy as np
import xarray as xr

from prism_mirror.catalog import DATA_DIR, VARIABLES

DEFAULT_STORE = DATA_DIR / "prism_subset.icechunk"


def open_prism(group: str = "daily", store: str | Path = DEFAULT_STORE, branch: str = "main") -> xr.Dataset:
    """Open one frequency group ("daily" or "monthly") lazily, with variables as float32.

    Packed variables are CF integers; xarray decodes them to float64 because zarr JSON attributes
    carry a float64 scale_factor. Casting back gives the harmonized float32 values (the float32
    nearest each PRISM decimal value) at half the memory.
    """
    repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(store)))
    # Dask-backed (store chunks) so the float32 cast below stays lazy; without it the cast loads every variable.
    ds = xr.open_zarr(repo.readonly_session(branch).store, group=group, consolidated=False, chunks={})
    for var in VARIABLES:
        if var in ds and ds[var].dtype != np.float32:
            ds[var] = ds[var].astype(np.float32, keep_attrs=True)
    return ds
