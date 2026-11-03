"""Read and sanitize one CHIRPS v3 GeoTIFF."""

from __future__ import annotations

import datetime as dt

import numpy as np
import rasterio

from climate_mirror.chirps import GRID
from climate_mirror.chirps.catalog import NODATA, local_tif
from climate_mirror.timeaxis import Frequency


def read_grid(freq: Frequency, d: dt.date) -> np.ndarray:
    """(2400, 7200) float32 in mm, NaN where the source has the -9999 fill.

    Checks the grid against GRID: the header's pixel size is float32-rounded (0.050000000745), so coordinates
    come from exact 0.05 degree steps instead. Any other negative value is an error.
    """
    path = local_tif(freq, d)
    with rasterio.open(path) as r:
        t = r.transform
        if r.shape != (GRID.ny, GRID.nx) or r.crs.to_epsg() != 4326 or r.count != 1 or r.dtypes[0] != "float32":
            raise ValueError(f"{path.name}: unexpected grid {r.shape} {r.crs} {r.dtypes}")
        if not (np.isclose(t.c, GRID.west - GRID.res / 2) and np.isclose(t.f, GRID.north + GRID.res / 2)
                and np.isclose(t.a, GRID.res) and np.isclose(t.e, -GRID.res) and t.b == t.d == 0):
            raise ValueError(f"{path.name}: unexpected transform {t}")
        a = r.read(1)
    fill = a == NODATA
    bad = (a < 0) & ~fill | ~np.isfinite(a)
    if bad.any():
        raise ValueError(f"{path.name}: {int(bad.sum())} values are negative (not -9999) or non-finite, e.g. {a[bad][:5]}")
    a[fill] = np.nan
    return a
