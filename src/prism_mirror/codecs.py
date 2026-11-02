"""Lossless codec configurations compared in the compression experiments.

Plain names (e.g. "pcodec8") store float32 directly. Names prefixed "cf-uint+" (unsigned with
add_offset) or "cf-int32+" (signed, no offset) first pack values into harmonized decimal
integers with CF scale_factor/add_offset (see packing.py), then apply the named codec.
"""

from __future__ import annotations

from typing import Callable

from zarr.codecs import BloscCodec, BytesCodec, GzipCodec, TransposeCodec, ZstdCodec
from zarr.codecs.numcodecs import PCodec, Shuffle

TIME_LAST = TransposeCodec(order=(1, 2, 0))


def _cfg(serializer=None, compressors=(), filters=()):
    return {
        "serializer": serializer or BytesCodec(),
        "compressors": list(compressors),
        "filters": list(filters),
    }


def _blosc(cname: str, shuffle: str, itemsize: int, clevel: int = 5) -> BloscCodec:
    return BloscCodec(cname=cname, clevel=clevel, shuffle=shuffle, typesize=itemsize)


# name -> builder(itemsize) -> codec kwargs for zarr.create_array
BUILDERS: dict[str, Callable[[int], dict]] = {
    "none": lambda n: _cfg(),
    "zstd1": lambda n: _cfg(compressors=[ZstdCodec(level=1)]),
    "zstd3": lambda n: _cfg(compressors=[ZstdCodec(level=3)]),
    "zstd9": lambda n: _cfg(compressors=[ZstdCodec(level=9)]),
    "zstd19": lambda n: _cfg(compressors=[ZstdCodec(level=19)]),
    "gzip6": lambda n: _cfg(compressors=[GzipCodec(level=6)]),
    "blosc-lz4-shuffle": lambda n: _cfg(compressors=[_blosc("lz4", "shuffle", n)]),
    "blosc-zstd5-shuffle": lambda n: _cfg(compressors=[_blosc("zstd", "shuffle", n)]),
    "blosc-zstd5-bitshuffle": lambda n: _cfg(compressors=[_blosc("zstd", "bitshuffle", n)]),
    "shuffle-zstd3": lambda n: _cfg(compressors=[Shuffle(elementsize=n), ZstdCodec(level=3)]),
    "shuffle-zstd9": lambda n: _cfg(compressors=[Shuffle(elementsize=n), ZstdCodec(level=9)]),
    "pcodec4": lambda n: _cfg(serializer=PCodec(level=4)),
    "pcodec8": lambda n: _cfg(serializer=PCodec(level=8)),
    "pcodec12": lambda n: _cfg(serializer=PCodec(level=12)),
    # Time-last ordering puts each pixel's series contiguous before compression.
    "T-blosc-zstd5-bitshuffle": lambda n: _cfg(filters=[TIME_LAST], compressors=[_blosc("zstd", "bitshuffle", n)]),
    "T-shuffle-zstd9": lambda n: _cfg(filters=[TIME_LAST], compressors=[Shuffle(elementsize=n), ZstdCodec(level=9)]),
    "T-pcodec8": lambda n: _cfg(filters=[TIME_LAST], serializer=PCodec(level=8)),
}

PACKED_BASES = ["zstd3", "shuffle-zstd9", "blosc-zstd5-bitshuffle", "pcodec4", "pcodec8", "pcodec12", "T-pcodec8"]
CODEC_NAMES = list(BUILDERS) + [f"cf-uint+{b}" for b in PACKED_BASES] + ["cf-int32+pcodec8"]


def split_name(name: str) -> tuple[str | None, str]:
    """'cf-uint+pcodec8' -> ('cf-uint', 'pcodec8'); 'pcodec8' -> (None, 'pcodec8')."""
    if "+" in name:
        packing, base = name.split("+", 1)
        return packing, base
    return None, name


def codec_kwargs(name: str, itemsize: int = 4) -> dict:
    return BUILDERS[split_name(name)[1]](itemsize)
