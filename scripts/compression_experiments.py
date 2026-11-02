"""Compare lossless codecs and chunk layouts on whole sample time-chunks of PRISM 800m.

Each config encodes the block through the real zarr v3 codec pipeline into an in-memory store.
Icechunk stores those encoded chunk bytes verbatim, so the stored size equals what the
Icechunk repo would hold (build_store.py cross-checks this for the chosen codec).
Packed variants ("cf-uint+...", "cf-int32+...") first convert values to harmonized decimal
integers with CF scale_factor/add_offset (see prism_mirror/packing.py); the stored integers are
round-tripped exactly, and decoded floats are within 1 ulp of the source (checked in pack()).
Results are appended to results/compression.csv; rows already present are skipped.
"""

from __future__ import annotations

import argparse
import time
import zipfile

import numpy as np
import pandas as pd
import zarr
from zarr.storage import MemoryStore

from prism_mirror.catalog import FREQUENCIES, NX, NY, RESULTS_DIR, VARIABLES, local_zip, sample_chunks
from prism_mirror.codecs import CODEC_NAMES, codec_kwargs, split_name
from prism_mirror.io import read_grid
from prism_mirror.packing import pack

OUT = RESULTS_DIR / "compression.csv"
KEY = ["freq", "var", "chunk_index", "codec", "layout"]
COLUMNS = KEY + [
    "start", "n_time", "raw_bytes", "nan_fraction", "zip_bytes", "source_tif_bytes", "stored_bytes", "n_objects",
    "n_possible_objects", "encode_s", "decode_s", "exact", "stored_dtype", "scale_factor", "add_offset",
]

# Alternative layouts (chunk shape, shard shape or None), tried with a single codec.
LAYOUTS = {
    "daily": {
        "32x256x256": ((32, 256, 256), None),
        "32x128x128": ((32, 128, 128), None),
        "16x256x256": ((16, 256, 256), None),
        "8x512x512": ((8, 512, 512), None),
        "32x512x512": ((32, 512, 512), None),
        "shard32x256x256/32x64x64": ((32, 64, 64), (32, 256, 256)),
    },
    "monthly": {
        "12x256x256": ((12, 256, 256), None),
        "12x128x128": ((12, 128, 128), None),
        "12x512x512": ((12, 512, 512), None),
        "6x512x512": ((6, 512, 512), None),
        "shard12x256x256/12x64x64": ((12, 64, 64), (12, 256, 256)),
    },
}


def load_block(var: str, freq, chunk_index: int):
    dates = freq.chunk_dates(chunk_index)
    block = np.empty((len(dates), NY, NX), dtype=np.float32)
    zip_bytes = tif_bytes = 0
    for i, d in enumerate(dates):
        g = read_grid(var, freq, d.date())
        block[i] = g.data
        zip_bytes += g.zip_bytes
        with zipfile.ZipFile(local_zip(var, freq, d.date())) as z:
            tif_bytes += next(zi.compress_size for zi in z.infolist() if zi.filename.endswith(".tif"))
    return block, zip_bytes, tif_bytes


def same_bits(a: np.ndarray, b: np.ndarray) -> bool:
    if a.dtype.kind != "f":
        return bool(np.array_equal(a, b))
    nan = np.isnan(a)
    return bool(np.array_equal(nan, np.isnan(b)) and np.array_equal(a.view(np.uint32)[~nan], b.view(np.uint32)[~nan]))


def measure(block: np.ndarray, chunks, shards, codec: dict, fill_value=np.nan) -> dict:
    store = MemoryStore()
    arr = zarr.create_array(
        store,
        shape=block.shape,
        dtype=block.dtype,
        chunks=chunks,
        shards=shards,
        fill_value=fill_value,
        config={"write_empty_chunks": False},
        **codec,
    )
    t0 = time.perf_counter()
    arr[:] = block
    enc = time.perf_counter() - t0
    t0 = time.perf_counter()
    back = arr[:]
    dec = time.perf_counter() - t0
    chunk_items = {k: v for k, v in store._store_dict.items() if not k.endswith("zarr.json")}
    outer = shards or chunks
    possible = int(np.prod([-(-n // c) for n, c in zip(block.shape, outer)]))
    return {
        "stored_bytes": sum(len(v) for v in chunk_items.values()),
        "n_objects": len(chunk_items),
        "n_possible_objects": possible,
        "encode_s": enc,
        "decode_s": dec,
        "exact": same_bits(block, back),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--vars", nargs="*", default=list(VARIABLES))
    p.add_argument("--codecs", nargs="*", default=CODEC_NAMES)
    p.add_argument("--blocks", choices=["first", "middle", "last", "all"], default="last")
    p.add_argument("--layouts", action="store_true", help="vary chunk layout instead of codec")
    p.add_argument("--workers", type=int, default=18)
    args = p.parse_args()
    zarr.config.set({"threading.max_workers": args.workers, "async.concurrency": 4 * args.workers})

    RESULTS_DIR.mkdir(exist_ok=True)
    done = set()
    if OUT.exists():
        done = set(map(tuple, pd.read_csv(OUT)[KEY].astype(str).values.tolist()))

    for fname in args.freq:
        freq = FREQUENCIES[fname]
        chunks_all = sample_chunks(freq)
        blocks = {"first": chunks_all[:1], "middle": chunks_all[1:2], "last": chunks_all[-1:], "all": chunks_all}[args.blocks]
        default_layout = f"{freq.time_chunk}x{freq.space_chunk}x{freq.space_chunk}"
        if args.layouts:
            runs = [(c, name, ch, sh) for c in args.codecs for name, (ch, sh) in LAYOUTS[fname].items()]
        else:
            chunks = (freq.time_chunk, freq.space_chunk, freq.space_chunk)
            runs = [(c, default_layout, chunks, None) for c in args.codecs]
        for var in args.vars:
            for ci in blocks:
                todo = [r for r in runs if (fname, var, str(ci), r[0], r[1]) not in done]
                if not todo:
                    continue
                t0 = time.perf_counter()
                block, zip_bytes, tif_bytes = load_block(var, freq, ci)
                print(f"[{fname} {var} chunk {ci}] loaded in {time.perf_counter() - t0:.0f}s", flush=True)
                packed = {}
                for codec_name, layout, ch, sh in todo:
                    packing, _ = split_name(codec_name)
                    data, fill, extra = block, np.nan, {"stored_dtype": "float32"}
                    if packing:
                        if packing not in packed:
                            packed[packing] = pack(block, var, packing)  # raises if any value moves > 1 ulp
                        data, attrs = packed[packing]
                        fill = attrs["_FillValue"]
                        extra = {"stored_dtype": str(data.dtype), "scale_factor": repr(attrs["scale_factor"]),
                                 "add_offset": repr(attrs.get("add_offset", 0.0))}
                    m = measure(data, ch, sh, codec_kwargs(codec_name, data.dtype.itemsize), fill)
                    if not m["exact"]:
                        raise AssertionError(f"{codec_name}/{layout} is not lossless for {fname} {var} {ci}")
                    row = {
                        "freq": fname, "var": var, "chunk_index": ci, "codec": codec_name, "layout": layout,
                        "start": str(freq.chunk_dates(ci)[0].date()), "n_time": block.shape[0],
                        "raw_bytes": block.nbytes, "nan_fraction": float(np.isnan(block).mean()),
                        "zip_bytes": zip_bytes, "source_tif_bytes": tif_bytes, **m, **extra,
                    }
                    pd.DataFrame([row]).reindex(columns=COLUMNS).to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
                    print(
                        f"  {codec_name:26s} {layout:26s} ratio {block.nbytes / m['stored_bytes']:6.2f}"
                        f"  enc {block.nbytes / m['encode_s'] / 1e6:7.0f} MB/s  dec {block.nbytes / m['decode_s'] / 1e6:7.0f} MB/s",
                        flush=True,
                    )
                del block, packed


if __name__ == "__main__":
    main()
