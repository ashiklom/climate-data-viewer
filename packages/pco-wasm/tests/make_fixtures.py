"""Write golden fixtures for the pco-wasm decoder: (encoded chunk, expected decoded bytes, dtype).

Encodes with the same numcodecs.pcodec codec zarr uses, plus real chunks:
- a harmonized PRISM daily ppt block (cf-uint packing -> uint32), and
- a raw chunk fetched from Earthmover's public ERA5 Icechunk store (bytes exactly as served).

Run from the repo root:  uv run python packages/pco-wasm/tests/make_fixtures.py
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path

import numpy as np
from numcodecs.pcodec import PCodec
from zarr.core.buffer import default_buffer_prototype

OUT = Path(__file__).parent / "fixtures"


def write(name: str, encoded: bytes, expected: np.ndarray, meta: list) -> None:
    (OUT / f"{name}.pco").write_bytes(encoded)
    (OUT / f"{name}.raw").write_bytes(np.ascontiguousarray(expected).tobytes())
    meta.append({"name": name, "dtype": str(expected.dtype), "n": int(expected.size)})


def synthetic(meta: list) -> None:
    rng = np.random.default_rng(42)
    smooth = np.cumsum(rng.normal(size=(64, 64)), axis=1).astype(np.float32)
    with_nan = smooth.copy()
    with_nan[rng.random(smooth.shape) < 0.3] = np.nan
    cases = {
        "f32_smooth": smooth,
        "f32_nan_inf": np.concatenate([with_nan.ravel(), np.array([np.inf, -np.inf, -0.0], np.float32)]),
        "f32_all_nan": np.full(1000, np.nan, np.float32),
        "f32_constant": np.full(4096, 3.25, np.float32),
        "f32_decimal_mult": (rng.integers(0, 50000, 10000) * np.float32(0.001)).astype(np.float32),
        "f64_random": rng.normal(size=5000),
        "u16_counts": rng.integers(0, 65535, 8192, dtype=np.uint16),
        "u32_packed": rng.integers(0, 50_000_000, 8192).astype(np.uint32),
        "i32_signed": rng.integers(-1_000_000, 1_000_000, 8192).astype(np.int32),
        "i16_small": rng.integers(-300, 300, 5000).astype(np.int16),
        "u32_single": np.array([7], np.uint32),
        "f32_empty": np.zeros(0, np.float32),
    }
    for level in (4, 8, 12):
        codec = PCodec(level=level)
        for name, arr in cases.items():
            if arr.size == 0 and level != 8:
                continue
            write(f"{name}_L{level}", bytes(codec.encode(arr)), arr, meta)


def prism_block(meta: list) -> None:
    from climate_mirror.packing import pack
    from climate_mirror.prism.catalog import DAILY, VARIABLES
    from climate_mirror.prism.io import read_grid

    x = read_grid("ppt", DAILY, dt.date(2021, 10, 10)).data[:256, :256]  # one spatial tile
    ints, _ = pack(x[None], VARIABLES["ppt"].valid_range, "cf-uint", label="ppt")
    write("prism_ppt_cfuint_L8", bytes(PCodec(level=8).encode(ints)), ints, meta)


def era5_chunk(meta: list) -> None:
    from climate_mirror import storage

    repo = storage.open_external("era5_earthmover")
    store = repo.readonly_session("main").store
    key = "single/spatial/t2m/c/714420/0/0"  # 2021-07-01T12:00 UTC, full 721x1440 map
    buf = asyncio.run(store.get(key, prototype=default_buffer_prototype()))
    encoded = buf.to_bytes()
    decoded = np.asarray(PCodec(level=8).decode(encoded)).astype(np.float32)
    write("era5_t2m_spatial_chunk", encoded, decoded, meta)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    meta: list = []
    synthetic(meta)
    prism_block(meta)
    era5_chunk(meta)
    (OUT / "index.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(meta)} fixtures in {OUT}")


if __name__ == "__main__":
    main()
