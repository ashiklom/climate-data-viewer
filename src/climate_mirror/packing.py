"""Harmonized CF integer packing (scale_factor / add_offset) of float32 grids of decimal values.

Written for PRISM (described below) and reused for other datasets with decimal-valued data.

Almost all PRISM values are exact decimal quantities (3 decimals, a few tmin grids 4), but
individual grids were written to float32 in different ways:
  * "div-3":  x == float32(k / 1000)
  * "mul-3":  x == float32(k) * float32(0.001)   (float32(0.001) is ~4.7e-8 too large)
  * "mul-4":  x == float32(k) * float32(0.0001)
The "mul" forms differ from the float32 nearest the decimal value by at most 1 ulp.
Some older daily ppt grids also contain unrounded values ("other"); those are rounded to the
nearest 1e-4 mm (error <= 5e-5 mm, unbiased), far below the 0.254 mm gauge resolution.
We store the integer k (in 1e-4 units) and let CF decoding return one consistent float32 per
decimal value. pack() refuses any grid where a value would move by more than half a quantum
plus 1 ulp (see scripts/rounding_analysis.py for the measured effect).
"""

from __future__ import annotations

import numpy as np
import xarray as xr
from xarray.conventions import decode_cf_variable

DECIMALS = 4
SCALE = 10.0**-DECIMALS


ValidRange = tuple[float, float]


def cf_attrs(valid_range: ValidRange, kind: str = "cf-uint") -> tuple[np.dtype, dict]:
    """Integer dtype and CF packing attributes for a variable with the given plausible range."""
    if kind == "cf-int32":
        dtype = np.dtype(np.int32)
        return dtype, {"scale_factor": SCALE, "_FillValue": dtype.type(np.iinfo(dtype).min)}
    if kind != "cf-uint":
        raise ValueError(kind)
    lo, hi = valid_range
    span = round((hi - lo) / SCALE)
    dtype = np.dtype(np.uint16 if span < np.iinfo(np.uint16).max else np.uint32)
    attrs = {"scale_factor": SCALE, "_FillValue": dtype.type(np.iinfo(dtype).max)}
    if lo:
        attrs["add_offset"] = float(lo)
    return dtype, attrs


def encode(data: np.ndarray, valid_range: ValidRange, kind: str = "cf-uint") -> np.ndarray:
    dtype, attrs = cf_attrs(valid_range, kind)
    nan = np.isnan(data)
    k = np.rint((data.astype(np.float64) - attrs.get("add_offset", 0.0)) / SCALE)
    k[nan] = attrs["_FillValue"]
    return k.astype(dtype)


def decode(ints: np.ndarray, attrs: dict) -> np.ndarray:
    """Decode exactly as a CF reader (xarray) does, returned as float32."""
    out = decode_cf_variable("x", xr.Variable(tuple(f"d{i}" for i in range(ints.ndim)), ints, dict(attrs))).values
    return out.astype(np.float32)


def canonical(data: np.ndarray, valid_range: ValidRange, kind: str = "cf-uint") -> np.ndarray:
    """The harmonized float32 values a reader of the mirror sees for `data`."""
    return decode(encode(data, valid_range, kind), cf_attrs(valid_range, kind)[1])


def pack(data: np.ndarray, valid_range: ValidRange, kind: str = "cf-uint", label: str = "") -> tuple[np.ndarray, dict]:
    """Encode float32 `data` (NaN = missing) to integers.

    Guarantees |decoded - data| <= SCALE / 2 + 1 ulp: decimal values move by at most float32 noise,
    unrounded values are rounded to the nearest SCALE.
    """
    _, attrs = cf_attrs(valid_range, kind)
    ints = encode(data, valid_range, kind)
    back = decode(ints, attrs)
    nan = np.isnan(data)
    if not np.array_equal(nan, np.isnan(back)):
        raise ValueError(f"{label}: missing-value mask changed by packing")
    src, out = data[~nan], back[~nan]
    ulp = np.abs(np.spacing(src)).astype(np.float64)
    excess = np.abs(out.astype(np.float64) - src) - (SCALE / 2 + ulp)
    if excess.size and excess.max() > 0:
        i = int(np.argmax(excess))
        raise ValueError(f"{label}: packing would move {src[i]!r} to {out[i]!r} (> {SCALE / 2:g} + 1 ulp)")
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
