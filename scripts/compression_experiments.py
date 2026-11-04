"""Compare lossless codecs and chunk layouts on whole sample time-chunks of a dataset (--dataset).

Each config encodes the block through the real zarr v3 codec pipeline into an in-memory store.
Icechunk stores those encoded chunk bytes verbatim, so the stored size equals what the
Icechunk repo would hold (build_store.py cross-checks this for the chosen codec).
Packed variants ("cf-uint+...", "cf-int32+...") first convert values to harmonized decimal
integers with CF scale_factor/add_offset (see climate_mirror/packing.py); the stored integers are
round-tripped exactly, and decoded floats are within 1 ulp of the source (checked in pack()).
Results are appended to results/<dataset>/compression.csv; rows already present are skipped.
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd
import zarr
from zarr.storage import MemoryStore

from climate_mirror import datasets
from climate_mirror.codecs import CODEC_NAMES, codec_kwargs, split_name
from climate_mirror.packing import pack

KEY = ["freq", "var", "chunk_index", "codec", "layout"]
COLUMNS = KEY + [
    "start", "n_time", "raw_bytes", "nan_fraction", "zip_bytes", "source_tif_bytes", "stored_bytes", "n_objects",
    "n_possible_objects", "encode_s", "decode_s", "exact", "stored_dtype", "scale_factor", "add_offset",
]

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
    p.add_argument("--dataset", choices=list(datasets.DATASETS), default="prism")
    p.add_argument("--freq", nargs="*")
    p.add_argument("--vars", nargs="*")
    p.add_argument("--codecs", nargs="*", default=CODEC_NAMES)
    p.add_argument("--blocks", choices=["first", "middle", "last", "all"], default="last")
    p.add_argument("--layouts", action="store_true", help="vary chunk layout instead of codec")
    p.add_argument("--workers", type=int, default=18)
    args = p.parse_args()
    ds = datasets.get(args.dataset)
    out = ds.results_dir / "compression.csv"
    zarr.config.set({"threading.max_workers": args.workers, "async.concurrency": 4 * args.workers})

    ds.results_dir.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = set(map(tuple, pd.read_csv(out)[KEY].astype(str).values.tolist()))

    for fname in args.freq or list(ds.frequencies):
        freq = ds.frequencies[fname]
        chunks_all = ds.sample_chunks(freq)
        blocks = {"first": chunks_all[:1], "middle": chunks_all[1:2], "last": chunks_all[-1:], "all": chunks_all}[args.blocks]
        default_layout = datasets.default_layout(freq)
        if args.layouts:
            runs = [(c, name, ch, sh) for c in args.codecs for name, (ch, sh) in ds.layouts[fname].items()]
        else:
            layout = freq.zarr_layout()
            runs = [(c, default_layout, layout["chunks"], layout.get("shards")) for c in args.codecs]
        for var in args.vars or list(ds.variables):
            for ci in blocks:
                todo = [r for r in runs if (fname, var, str(ci), r[0], r[1]) not in done]
                if not todo:
                    continue
                t0 = time.perf_counter()
                loaded = ds.load_block(var, freq, ci)
                block = loaded.data
                print(f"[{fname} {var} chunk {ci}] loaded in {time.perf_counter() - t0:.0f}s", flush=True)
                packed = {}
                for codec_name, layout, ch, sh in todo:
                    packing, _ = split_name(codec_name)
                    data, fill, extra = block, np.nan, {"stored_dtype": "float32"}
                    if packing:
                        if packing not in packed:
                            # raises if any value would move by more than half a quantum + 1 ulp
                            packed[packing] = pack(block, ds.variables[var].valid_range, packing, label=var)
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
                        "zip_bytes": loaded.source_bytes, "source_tif_bytes": loaded.source_payload_bytes, **m, **extra,
                    }
                    pd.DataFrame([row]).reindex(columns=COLUMNS).to_csv(out, mode="a", header=not out.exists(), index=False)
                    print(
                        f"  {codec_name:26s} {layout:26s} ratio {block.nbytes / m['stored_bytes']:6.2f}"
                        f"  enc {block.nbytes / m['encode_s'] / 1e6:7.0f} MB/s  dec {block.nbytes / m['decode_s'] / 1e6:7.0f} MB/s",
                        flush=True,
                    )
                del block, loaded, packed


if __name__ == "__main__":
    main()
