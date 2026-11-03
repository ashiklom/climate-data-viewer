"""CHIRPS v3 (native pentads, dekads, months) implementation of `climate_mirror.datasets.Dataset`."""

from __future__ import annotations

import datetime as dt

import numpy as np

from climate_mirror.chirps import GRID, catalog
from climate_mirror.chirps.io import read_grid
from climate_mirror.datasets import Block
from climate_mirror.timeaxis import Frequency


class ChirpsDataset:
    name = "chirps"
    frequencies = catalog.FREQUENCIES
    variables = catalog.VARIABLES
    grid_shape = (GRID.ny, GRID.nx)
    results_dir = catalog.RESULTS_DIR
    record_end = catalog.RECORD_END
    thresholds = catalog.THRESHOLDS
    layouts = {
        f: {
            f"{t}x400x400": ((t, 400, 400), None),
            f"{t}x240x240": ((t, 240, 240), None),
            f"{t}x600x600": ((t, 600, 600), None),
            f"{t}x800x900": ((t, 800, 900), None),
            f"{t // 2}x600x600": ((t // 2, 600, 600), None),
            f"shard{t}x1200x1200/{t}x200x200": ((t, 200, 200), (t, 1200, 1200)),
        }
        for f, t in (("pentad", 18), ("dekad", 18), ("monthly", 12))
    }

    def sample_chunks(self, freq: Frequency) -> list[int]:
        return catalog.sample_chunks(freq)

    def read_grid(self, var: str, freq: Frequency, date: dt.date) -> np.ndarray:
        return read_grid(freq, date)

    def source_exists(self, var: str, freq: Frequency, date: dt.date) -> bool:
        return catalog.local_tif(freq, date).exists()

    def load_block(self, var: str, freq: Frequency, chunk_index: int) -> Block:
        dates = freq.chunk_dates(chunk_index)
        data = np.empty((len(dates), GRID.ny, GRID.nx), dtype=np.float32)
        nbytes = 0
        for i, d in enumerate(dates):
            data[i] = read_grid(freq, d.date())
            nbytes += catalog.local_tif(freq, d.date()).stat().st_size
        return Block(data, nbytes, nbytes)  # plain LZW GeoTIFFs: the file is the payload


DATASET = ChirpsDataset()
