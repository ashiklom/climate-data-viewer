"""Harmonized CF integer packing (scale_factor / add_offset) of PRISM float32 grids.

PRISM values are exact decimal quantities (3 decimals, a few tmin grids 4), but individual
grids were written to float32 in different ways:
  * "div-3":  x == float32(k / 1000)
  * "mul-3":  x == float32(k) * float32(0.001)   (float32(0.001) is ~4.7e-8 too large)
  * "mul-4":  x == float32(k) * float32(0.0001)
The "mul" forms differ from the float32 nearest the decimal value by at most 1 ulp.
We store the decimal integer k (in 1e-4 units) and let CF decoding return one consistent
float32 per decimal value. pack() refuses any grid where that would move a value by more than
1 ulp, so the harmonization never touches information above float32 noise level
(see scripts/rounding_analysis.py for the measured effect).
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from xarray.conventions import decode_cf_variable

from prism_mirror.catalog import VARIABLES

DECIMALS = 4
SCALE = 10.0**-DECIMALS
MAX_ULP = 1


def _ulp_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a.view(np.int32).astype(np.int64) - b.view(np.int32).astype(np.int64)


def cf_attrs(var: str, kind: str = "cf-uint") -> tuple[np.dtype, dict]:
    """Integer dtype and CF packing attributes for a variable (identical for every grid)."""
    if kind == "cf-int32":
        dtype = np.dtype(np.int32)
        return dtype, {"scale_factor": SCALE, "_FillValue": dtype.type(np.iinfo(dtype).min)}
    if kind != "cf-uint":
        raise ValueError(kind)
    lo, hi = VARIABLES[var].valid_range
    span = round((hi - lo) / SCALE)
    dtype = np.dtype(np.uint16 if span < np.iinfo(np.uint16).max else np.uint32)
    attrs = {"scale_factor": SCALE, "_FillValue": dtype.type(np.iinfo(dtype).max)}
    if lo:
        attrs["add_offset"] = float(lo)
    return dtype, attrs


def encode(data: np.ndarray, var: str, kind: str = "cf-uint") -> np.ndarray:
    dtype, attrs = cf_attrs(var, kind)
    nan = np.isnan(data)
    k = np.rint((data.astype(np.float64) - attrs.get("add_offset", 0.0)) / SCALE)
    k[nan] = attrs["_FillValue"]
    return k.astype(dtype)


def decode(ints: np.ndarray, attrs: dict) -> np.ndarray:
    """Decode exactly as a CF reader (xarray) does, returned as float32."""
    out = decode_cf_variable("x", xr.Variable(tuple(f"d{i}" for i in range(ints.ndim)), ints, dict(attrs))).values
    return out.astype(np.float32)


def canonical(data: np.ndarray, var: str = "ppt", kind: str = "cf-uint") -> np.ndarray:
    """The harmonized float32 values a reader of the mirror sees for `data`."""
    return decode(encode(data, var, kind), cf_attrs(var, kind)[1])


def pack(data: np.ndarray, var: str, kind: str = "cf-uint") -> tuple[np.ndarray, dict]:
    """Encode float32 `data` (NaN = missing) to integers, guaranteeing |decoded - data| <= 1 ulp."""
    _, attrs = cf_attrs(var, kind)
    ints = encode(data, var, kind)
    back = decode(ints, attrs)
    nan = np.isnan(data)
    if not np.array_equal(nan, np.isnan(back)):
        raise ValueError(f"{var}: missing-value mask changed by packing")
    worst = np.abs(_ulp_diff(data[~nan], back[~nan])).max(initial=0)
    if worst > MAX_ULP:
        raise ValueError(f"{var}: harmonized packing would move a value by {worst} ulp (> {MAX_ULP})")
    return ints, attrs


def classify_style(x: np.ndarray) -> str:
    """Which float32 construction a grid's (finite) values follow."""
    x = x[np.isfinite(x)]
    for d in (3, 4):
        k = np.rint(x.astype(np.float64) * 10**d)
        if np.array_equal((k / 10**d).astype(np.float32).view(np.uint32), x.view(np.uint32)):
            return f"div-{d}"
        if np.array_equal((k.astype(np.float32) * np.float32(10.0**-d)).view(np.uint32), x.view(np.uint32)):
            return f"mul-{d}"
    return "other"
