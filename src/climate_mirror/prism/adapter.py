"""PRISM implementation of `climate_mirror.datasets.Dataset`."""

from __future__ import annotations

import datetime as dt
import zipfile

import numpy as np

from climate_mirror.datasets import Block
from climate_mirror.prism import catalog
from climate_mirror.prism.io import read_grid
from climate_mirror.timeaxis import Frequency


class PrismDataset:
    name = "prism"
    frequencies = catalog.FREQUENCIES
    variables = catalog.VARIABLES
    grid_shape = (catalog.NY, catalog.NX)
    results_dir = catalog.RESULTS_DIR
    record_end = catalog.RECORD_END
    thresholds = catalog.THRESHOLDS
    layouts = {
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

    def sample_chunks(self, freq: Frequency) -> list[int]:
        return catalog.sample_chunks(freq)

    def read_grid(self, var: str, freq: Frequency, date: dt.date) -> np.ndarray:
        return read_grid(var, freq, date).data

    def source_exists(self, var: str, freq: Frequency, date: dt.date) -> bool:
        return catalog.local_zip(var, freq, date).exists()

    def load_block(self, var: str, freq: Frequency, chunk_index: int) -> Block:
        dates = freq.chunk_dates(chunk_index)
        data = np.empty((len(dates), catalog.NY, catalog.NX), dtype=np.float32)
        zip_bytes = tif_bytes = 0
        for i, d in enumerate(dates):
            g = read_grid(var, freq, d.date())
            data[i] = g.data
            zip_bytes += g.zip_bytes
            with zipfile.ZipFile(catalog.local_zip(var, freq, d.date())) as z:
                tif_bytes += next(zi.compress_size for zi in z.infolist() if zi.filename.endswith(".tif"))
        return Block(data, zip_bytes, tif_bytes)


DATASET = PrismDataset()
