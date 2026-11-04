"""Rewrite the PRISM mirror's `daily` variables in the current catalog layout (catalog.DAILY.zarr_layout()), in place.

For each variable whose array layout differs: create `daily/<var>__relayout` with the new chunks/shards and the same
dtype, fill, codec and attributes; copy every written 32-day block (packed integers, unchanged); then delete the
old array and move the new one to its name (rearrange session). Coordinates, provenance arrays, the
`monthly` and `common_0p25` groups and the repo history are untouched. Re-running skips variables already done.

  uv run python scripts/prism/relayout_daily.py
"""

from __future__ import annotations

import argparse
import asyncio

import icechunk
import numpy as np
import zarr

from climate_mirror import storage
from climate_mirror.prism.catalog import DAILY, VARIABLES

GROUP = DAILY.name


async def written_blocks(session: icechunk.Session, path: str, time_chunk: int, old_time_chunk: int) -> list[int]:
    """Time blocks (of `time_chunk` steps) holding any written chunk of the array at `path`."""
    coords = [c async for c in session.chunk_coordinates(f"/{path}")]
    return sorted({c[0] * old_time_chunk // time_chunk for c in coords})


def relayout(repo: icechunk.Repository, var: str) -> None:
    layout = DAILY.zarr_layout()
    session = repo.writable_session("main")
    group = zarr.open_group(session.store, path=GROUP, mode="r+")
    old = group[var]
    if old.chunks == layout["chunks"] and old.shards == layout.get("shards"):
        print(f"{var}: already {DAILY.layout_name()}", flush=True)
        return
    tmp = f"{var}__relayout"
    if tmp in group:
        del group[tmp]
    T = DAILY.time_chunk
    blocks = asyncio.run(written_blocks(session, f"{GROUP}/{var}", T, old.chunks[0]))
    new = group.create_array(
        tmp, shape=old.shape, dtype=old.dtype, fill_value=old.fill_value, dimension_names=old.metadata.dimension_names,
        attributes=dict(old.attrs), config={"write_empty_chunks": False},
        serializer=old.serializer, compressors=old.compressors, filters=old.filters, **layout,
    )
    for b in blocks:  # one 32-day block at a time (~2.8 GB of uint32)
        i0, i1 = b * T, min((b + 1) * T, old.shape[0])
        data = old[i0:i1]
        new[i0:i1] = data
        assert np.array_equal(new[i0:i1], data), (var, b)
    session.commit(f"{GROUP}/{tmp}: copy of {var} ({len(blocks)} blocks) in {DAILY.layout_name()}")

    session = repo.writable_session("main")
    del zarr.open_group(session.store, path=GROUP, mode="r+")[var]
    session.commit(f"{GROUP}/{var}: remove (replaced by {tmp})")
    session = repo.rearrange_session("main")
    session.move(f"/{GROUP}/{tmp}", f"/{GROUP}/{var}")
    session.commit(f"{GROUP}/{var}: now {DAILY.layout_name()} (was {'x'.join(map(str, old.chunks))})")
    print(f"{var}: {len(blocks)} blocks -> {DAILY.layout_name()}", flush=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--vars", nargs="*", default=list(VARIABLES))
    args = p.parse_args()
    zarr.config.set({"threading.max_workers": 18, "async.concurrency": 64})
    repo = storage.open_mirror("prism")
    for var in args.vars:
        relayout(repo, var)


if __name__ == "__main__":
    main()
