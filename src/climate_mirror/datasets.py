"""Registry of mirrored datasets and the interface the generic study scripts use.

`scripts/compression_experiments.py`, `scripts/rounding_analysis.py` and `scripts/estimate.py`
work on any dataset that implements `Dataset`; dataset-specific download/build/verify scripts
live under `scripts/<dataset>/`.
"""

from __future__ import annotations

import datetime as dt
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from climate_mirror.timeaxis import Frequency


@dataclass
class Block:
    data: np.ndarray  # (time, y, x) float32, NaN = missing, already sanitized
    source_bytes: int  # bytes of the source files as distributed (zips, tifs, ...)
    source_payload_bytes: int  # bytes of the compressed raster payload alone (e.g. the .tif in a zip)


class Variable(Protocol):
    name: str
    valid_range: tuple[float, float]


class Dataset(Protocol):
    name: str
    frequencies: dict[str, Frequency]
    variables: dict[str, Variable]
    grid_shape: tuple[int, int]  # (ny, nx)
    results_dir: Path
    record_end: dict[str, dt.date]  # last period available at the source, per frequency
    thresholds: dict[str, list[float]]  # per variable, for the rounding analysis
    layouts: dict[str, dict[str, tuple[tuple[int, ...], tuple[int, ...] | None]]]  # alternative layouts

    def sample_chunks(self, freq: Frequency) -> list[int]: ...

    def read_grid(self, var: str, freq: Frequency, date: dt.date) -> np.ndarray: ...

    def load_block(self, var: str, freq: Frequency, chunk_index: int) -> Block: ...

    def source_exists(self, var: str, freq: Frequency, date: dt.date) -> bool: ...


DATASETS = {"prism": "climate_mirror.prism.adapter", "chirps": "climate_mirror.chirps.adapter"}


def get(name: str) -> Dataset:
    return importlib.import_module(DATASETS[name]).DATASET


def sample_dates(ds: Dataset, freq: Frequency) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(d for c in ds.sample_chunks(freq) for d in freq.chunk_dates(c)))


def default_layout(freq: Frequency) -> str:
    return freq.layout_name()
