"""Read cached PRISM grid packages into sanitized numpy arrays."""

from __future__ import annotations

import datetime as dt
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio

from climate_mirror.prism.catalog import NODATA, NORTH, NX, NY, RES, VARIABLES, WEST, Frequency, local_zip


@dataclass
class Grid:
    data: np.ndarray  # float32 (NY, NX), NaN where PRISM has no data
    info: dict[str, str]  # parsed .info.txt (dataset type/version/create date)
    zip_bytes: int


def lon_centers() -> np.ndarray:
    return WEST + (np.arange(NX) + 0.5) * RES


def lat_centers() -> np.ndarray:
    return NORTH - (np.arange(NY) + 0.5) * RES


def read_grid(var: str, freq: Frequency, d: dt.date, path: Path | None = None) -> Grid:
    path = path or local_zip(var, freq, d)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        tif = next(n for n in names if n.endswith(".tif"))
        info_name = next((n for n in names if n.endswith(".info.txt")), None)
        info = {}
        if info_name:
            for line in z.read(info_name).decode().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k.strip()] = v.strip()
    with rasterio.open(f"/vsizip/{path}/{tif}") as src:
        if (src.width, src.height) != (NX, NY):
            raise ValueError(f"{path}: unexpected grid {src.width}x{src.height}")
        t = src.transform
        if not (abs(t.c - WEST) < 1e-9 and abs(t.f - NORTH) < 1e-9 and abs(t.a - RES) < 1e-9):
            raise ValueError(f"{path}: unexpected transform {t}")
        if src.nodata != NODATA:
            raise ValueError(f"{path}: unexpected nodata {src.nodata}")
        data = src.read(1)
    return Grid(sanitize(data, var, path), info, path.stat().st_size)


def sanitize(data: np.ndarray, var: str, label: object = "") -> np.ndarray:
    """Map the -9999 sentinel to NaN and check nothing else looks like a sentinel."""
    if data.dtype != np.float32:
        raise TypeError(f"{label}: expected float32, got {data.dtype}")
    data = np.where(data == np.float32(NODATA), np.float32(np.nan), data)
    lo, hi = VARIABLES[var].valid_range
    valid = data[np.isfinite(data)]
    if valid.size and (valid.min() < lo or valid.max() > hi):
        raise ValueError(f"{label}: values outside plausible range [{lo}, {hi}]: {valid.min()}..{valid.max()}")
    if np.isinf(data).any():
        raise ValueError(f"{label}: contains inf")
    return data
