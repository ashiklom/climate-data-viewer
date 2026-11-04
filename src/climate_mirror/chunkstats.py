"""Which stored chunks a selection touches, and how many bytes reading it costs (shard-index aware)."""

from __future__ import annotations

import asyncio
import itertools

import numpy as np
import zarr
from zarr.abc.store import SuffixByteRequest
from zarr.core.buffer import default_buffer_prototype


async def fetched_bytes(arr: zarr.Array, sel: tuple) -> tuple[int, int]:
    """Chunks a selection touches and their stored (compressed) size; absent chunks count as touched, 0 bytes.
    For sharded arrays, inner chunks are counted from each shard's index (plus the index read itself)."""
    a = arr._async_array
    outer = arr.shards or arr.chunks
    per = [o // c for o, c in zip(outer, arr.chunks)]
    n_inner = int(np.prod(per))

    def chunk_range(s, c, n):
        start, stop, _ = s.indices(n) if isinstance(s, slice) else (s, s + 1, 1)
        return range(start // c, (stop - 1) // c + 1)

    inner = list(itertools.product(*(chunk_range(s, c, n) for s, c, n in zip(sel, arr.chunks, arr.shape))))
    by_shard: dict[tuple, list[tuple]] = {}
    for idx in inner:
        by_shard.setdefault(tuple(i // p for i, p in zip(idx, per)), []).append(idx)
    prefix = f"{a.path}/" if a.path else ""
    sem = asyncio.Semaphore(64)

    async def size(shard, members):
        key = prefix + a.metadata.encode_chunk_key(shard)
        async with sem:
            if not arr.shards:
                buf = await a.store_path.store.get(key, default_buffer_prototype())
                return 0 if buf is None else len(buf)
            index_bytes = n_inner * 16 + 4  # (offset, nbytes) uint64 pairs + crc32c, at the shard's end
            buf = await a.store_path.store.get(key, default_buffer_prototype(), SuffixByteRequest(index_bytes))
            if buf is None:
                return 0
            ent = np.frombuffer(buf.to_bytes()[: n_inner * 16], dtype="<u8").reshape(-1, 2)
            flat = [np.ravel_multi_index(tuple(i % p for i, p in zip(m, per)), per) for m in members]
            return index_bytes + int(sum(ent[f, 1] for f in flat if ent[f, 0] != 2**64 - 1))

    sizes = await asyncio.gather(*(size(sh, m) for sh, m in by_shard.items()))
    return len(inner), sum(sizes)
