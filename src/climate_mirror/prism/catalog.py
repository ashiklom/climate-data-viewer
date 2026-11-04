"""Static description of the PRISM 800m time series and the chunk layout used to mirror it."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from climate_mirror.paths import RESULTS_DIR as _RESULTS_ROOT
from climate_mirror.paths import STORES_DIR, cache_path
from climate_mirror.timeaxis import Frequency

BASE_URL = "https://data.prism.oregonstate.edu/time_series/us/an/800m"
RESULTS_DIR = _RESULTS_ROOT / "prism"
STORE = STORES_DIR / "prism.icechunk"

# Grid (CONUS, 30 arc-second). The GeoTIFF header stores a truncated pixel size
# (0.008333333333), so coordinates are derived from exact 1/120 degree steps instead.
NX, NY = 7025, 3105
RES = 1.0 / 120.0
WEST = -125.0 - 2.5 / 120.0  # -125.0208333...
NORTH = 49.9375
NODATA = -9999.0

DAILY_START = dt.date(1981, 1, 1)
MONTHLY_START = dt.date(1895, 1, 1)


@dataclass(frozen=True)
class Variable:
    name: str
    long_name: str
    units: str
    standard_name: str | None
    daily_cell_method: str
    monthly_cell_method: str
    valid_range: tuple[float, float]  # generous plausibility bounds used to catch stray sentinels


VARIABLES: dict[str, Variable] = {
    v.name: v
    for v in [
        Variable("ppt", "Total precipitation (rain + melted snow)", "mm", "precipitation_amount",
                 "time: sum", "time: sum", (0.0, 5000.0)),
        Variable("tmin", "Minimum air temperature", "degC", "air_temperature",
                 "time: minimum", "time: mean within days time: minimum over days", (-70.0, 60.0)),
        Variable("tmax", "Maximum air temperature", "degC", "air_temperature",
                 "time: maximum", "time: mean within days time: maximum over days", (-70.0, 70.0)),
        Variable("tmean", "Mean air temperature, (tmin + tmax) / 2", "degC", "air_temperature",
                 "time: mean", "time: mean", (-70.0, 70.0)),
        Variable("tdmean", "Mean dew point temperature", "degC", "dew_point_temperature",
                 "time: mean", "time: mean", (-80.0, 50.0)),
        Variable("vpdmin", "Minimum vapor pressure deficit", "hPa", None,
                 "time: minimum", "time: mean within days time: minimum over days", (0.0, 200.0)),
        Variable("vpdmax", "Maximum vapor pressure deficit", "hPa", None,
                 "time: maximum", "time: mean within days time: maximum over days", (0.0, 200.0)),
        Variable("soltotal", "Total global shortwave solar radiation on a horizontal surface",
                 "MJ m-2 day-1", "surface_downwelling_shortwave_flux_in_air",
                 "time: mean", "time: mean", (0.0, 60.0)),
        Variable("solslope", "Total global shortwave solar radiation on the sloped terrain surface",
                 "MJ m-2 day-1", None, "time: mean", "time: mean", (0.0, 60.0)),
    ]
}


# Daily: 32-day x 512 x 512 shards of one-day 256 x 256 chunks. A one-day map reads 1/32 of what 32x256x256 chunks
# cost, with the same object count and no more storage (one-day chunks compress as well or better); a point series
# reads the same bytes in more (range) requests. See results/prism/map_layouts.csv.
DAILY = Frequency("daily", DAILY_START, time_chunk=32, space_chunk=512, inner_chunk=(1, 256, 256))
MONTHLY = Frequency("monthly", MONTHLY_START, time_chunk=12, space_chunk=256)
FREQUENCIES = {"daily": DAILY, "monthly": MONTHLY}

# Last grids listed on data.prism.oregonstate.edu when the estimate was made (2026-11-02).
RECORD_END = {"daily": dt.date(2026, 11, 1), "monthly": dt.date(2026, 10, 1)}

# Thresholds (native units) checked for classification flips in the rounding analysis.
THRESHOLDS = {
    "ppt": [0.01, 0.1, 0.254, 1.0, 10.0, 25.4, 50.8],
    "tmin": [0.0, -17.778],
    "tmax": [0.0, 32.222, 35.0],
    "tmean": [0.0, 5.0, 10.0],
    "tdmean": [0.0],
    "vpdmin": [1.0],
    "vpdmax": [10.0, 30.0],
    "soltotal": [5.0],
    "solslope": [5.0],
}

# Representative sample: whole time chunks spread across eras and seasons.
SAMPLE_TARGETS = {
    "daily": [dt.date(1985, 1, 15), dt.date(2003, 7, 15), dt.date(2021, 10, 15)],
    "monthly": [dt.date(1900, 6, 1), dt.date(1960, 6, 1), dt.date(2020, 6, 1)],
}


def sample_chunks(freq: Frequency) -> list[int]:
    return [freq.index_of(d) // freq.time_chunk for d in SAMPLE_TARGETS[freq.name]]


def sample_dates(freq: Frequency) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(sorted(d for c in sample_chunks(freq) for d in freq.chunk_dates(c)))


def file_stem(var: str, freq: Frequency, d: dt.date) -> str:
    return f"prism_{var}_us_30s_{d:%Y%m%d}" if freq.name == "daily" else f"prism_{var}_us_30s_{d:%Y%m}"


def url(var: str, freq: Frequency, d: dt.date) -> str:
    return f"{BASE_URL}/{var}/{freq.name}/{d.year}/{file_stem(var, freq, d)}.zip"


def local_zip(var: str, freq: Frequency, d: dt.date) -> Path:
    return cache_path(url(var, freq, d))
