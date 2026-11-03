"""Static description of the native CHIRPS v3 products (CHC GeoTIFFs) and the chunk layout used to mirror them."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from climate_mirror.chirps import GRID
from climate_mirror.paths import RESULTS_DIR as _RESULTS_ROOT
from climate_mirror.paths import cache_path
from climate_mirror.timeaxis import PERIOD_START_DAYS, Frequency

BASE_URL = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0"
RESULTS_DIR = _RESULTS_ROOT / "chirps"
NODATA = -9999.0  # ocean / outside 60N-60S land; not declared in the GeoTIFF headers
START = dt.date(1981, 1, 1)

# Space: 400 x 400 tiles divide the 2400 x 7200 grid exactly (6 x 18 tiles). Time: a quarter of pentads,
# half a year of dekads, a year of months (18 / 18 / 12 steps).
PENTAD = Frequency("pentad", START, time_chunk=18, space_chunk=400)
DEKAD = Frequency("dekad", START, time_chunk=18, space_chunk=400)
MONTHLY = Frequency("monthly", START, time_chunk=12, space_chunk=400)
FREQUENCIES = {"pentad": PENTAD, "dekad": DEKAD, "monthly": MONTHLY}
GROUPS = {"pentad": "pentads", "dekad": "dekads", "monthly": "monthly"}  # repo groups, named as CHC's directories

# Last periods listed on data.chc.ucsb.edu when the estimate was made (2026-11-02).
RECORD_END = {"pentad": dt.date(2026, 9, 26), "dekad": dt.date(2026, 9, 21), "monthly": dt.date(2026, 9, 1)}


@dataclass(frozen=True)
class Variable:
    name: str
    long_name: str
    units: str
    standard_name: str
    valid_range: tuple[float, float]  # generous plausibility bounds used to catch stray sentinels


VARIABLES = {"precip": Variable("precip", "Precipitation total over the period", "mm", "precipitation_amount",
                                (0.0, 20000.0))}

THRESHOLDS = {"precip": [0.1, 1.0, 10.0, 25.0, 50.0, 100.0]}

# Representative sample: whole time chunks spread across eras (station networks change) and seasons.
SAMPLE_TARGETS = {
    "pentad": [dt.date(1983, 2, 1), dt.date(1993, 5, 1), dt.date(2003, 8, 1), dt.date(2013, 11, 1), dt.date(2025, 5, 1)],
    "dekad": [dt.date(1983, 3, 1), dt.date(1993, 9, 1), dt.date(2003, 3, 1), dt.date(2013, 9, 1), dt.date(2025, 3, 1)],
    "monthly": [dt.date(1983, 6, 1), dt.date(1993, 6, 1), dt.date(2003, 6, 1), dt.date(2013, 6, 1), dt.date(2025, 6, 1)],
}


def sample_chunks(freq: Frequency) -> list[int]:
    return [freq.index_of(d) // freq.time_chunk for d in SAMPLE_TARGETS[freq.name]]


def sample_dates(freq: Frequency) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(d for c in sample_chunks(freq) for d in freq.chunk_dates(c)))


def file_name(freq: Frequency, d: dt.date) -> str:
    """chirps-v3.0.YYYY.MM.P.tif: P = pentad (1-6) or dekad (1-3) of the month; monthly files have no P."""
    if freq.name == "monthly":
        return f"chirps-v3.0.{d:%Y.%m}.tif"
    return f"chirps-v3.0.{d:%Y.%m}.{PERIOD_START_DAYS[freq.name].index(d.day) + 1}.tif"


def url(freq: Frequency, d: dt.date) -> str:
    return f"{BASE_URL}/{GROUPS[freq.name]}/global/tifs/{file_name(freq, d)}"


def local_tif(freq: Frequency, d: dt.date) -> Path:
    return cache_path(url(freq, d))

