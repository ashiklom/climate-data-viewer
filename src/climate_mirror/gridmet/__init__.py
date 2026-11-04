"""gridMET (Abatzoglou 2013; 1/24 degree CONUS daily, 1979-): local Icechunk mirror of the NKN NetCDF files.

Source: https://www.northwestknowledge.net/metdata/data/<var>_<year>.nc (CC0). Values there are uint16 counts with
CF scale_factor/add_offset; the mirror keeps those exact counts (lossless) and only rewrites the CF attributes so
that decoded values are in canonical units (degC, MJ m-2 day-1). See docs/new-datasets.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from climate_mirror.paths import cache_path

BASE = "https://www.northwestknowledge.net/metdata/data/"
FILL = 32767  # uint16 _FillValue in the source files (and the mirror)


@dataclass(frozen=True)
class Field:
    source: str  # file prefix, e.g. "tmmx"
    nc_var: str  # variable inside the file
    canonical: str
    scale: float  # canonical units per count
    offset: float  # canonical value at count 0


# Source packing (scale_factor, add_offset) and units: pr 0.1 mm; tmmx/tmmn 0.1 K + 220/210 K; srad 0.1 W m-2
# (daily mean); vs 0.1 m/s (10 m). Canonical: K -> degC subtracts 273.15; W m-2 daily mean -> MJ m-2 day-1 x 0.0864.
FIELDS = [
    Field("pr", "precipitation_amount", "pr", 0.1, 0.0),
    Field("tmmx", "air_temperature", "tasmax", 0.1, 220.0 - 273.15),
    Field("tmmn", "air_temperature", "tasmin", 0.1, 210.0 - 273.15),
    Field("srad", "surface_downwelling_shortwave_flux_in_air", "rsds", 0.1 * 0.0864, 0.0),
    Field("vs", "wind_speed", "sfcWind", 0.1, 0.0),
]
# tas = (tasmax + tasmin) / 2 as for PRISM tmean, stored exactly as the count sum tmmx + tmmn.
TAS = Field("tmmx+tmmn", "", "tas", 0.05, (220.0 + 210.0) / 2 - 273.15)
CANONICAL_VARS = [f.canonical for f in FIELDS] + ["tas"]


def url(source: str, year: int) -> str:
    return f"{BASE}{source}_{year}.nc"


def local(source: str, year: int):
    return cache_path(url(source, year))
