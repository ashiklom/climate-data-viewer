"""ERA5-Land daily canonical variables (0.1 deg, global land, 1950-).

Sources (CDS API, authenticated with the local CDS key; raw NetCDFs cached under cache/cds.climate.copernicus.eu/):
- `derived-era5-land-daily-statistics` (ECMWF's own UTC-day mean/max/min of hourly fields):
  tas/tasmax/tasmin (2 m temperature), tdps, ps, sm1, sm2.
- `reanalysis-era5-land` at 00 UTC for accumulated fields: ERA5-Land accumulates from 00 UTC, so the
  value valid at D+1 00:00 is the total over day D. pr (total_precipitation), rsds (surface solar radiation).
The ARCO ERA5-Land Zarr stores (stores.toml [external.era5land_arco]) only carry hourly tp and sp; they serve
point time series in the website and cross-check pr here.

sfcWind is not provided: a daily mean wind speed cannot be derived from daily mean u/v components, and
hourly 0.1 deg winds for a year are ~450 GB.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from climate_mirror.derived import Grid
from climate_mirror.paths import CACHE_DIR

CDS_URL = "https://cds.climate.copernicus.eu/api"
CACHE = CACHE_DIR / "cds.climate.copernicus.eu"
# Native grid is lat 90..-90 (1801), lon 0..359.9 (3600); we roll longitudes to -180..179.9.
GRID = Grid(north=90.0, west=-180.0, res=0.1, ny=1801, nx=3600)
RECORD = (dt.date(1950, 1, 1), dt.date(2026, 10, 26))


@dataclass(frozen=True)
class Field:
    canonical: str
    dataset: str
    variable: str  # CDS variable name
    statistic: str | None  # daily statistic (daily-statistics dataset) or None for 00 UTC accumulations
    scale: float = 1.0
    offset: float = 0.0


FIELDS = [
    Field("tas", "derived-era5-land-daily-statistics", "2m_temperature", "daily_mean", offset=-273.15),
    Field("tasmax", "derived-era5-land-daily-statistics", "2m_temperature", "daily_maximum", offset=-273.15),
    Field("tasmin", "derived-era5-land-daily-statistics", "2m_temperature", "daily_minimum", offset=-273.15),
    Field("tdps", "derived-era5-land-daily-statistics", "2m_dewpoint_temperature", "daily_mean", offset=-273.15),
    Field("ps", "derived-era5-land-daily-statistics", "surface_pressure", "daily_mean", scale=0.01),
    Field("sm1", "derived-era5-land-daily-statistics", "volumetric_soil_water_layer_1", "daily_mean"),
    Field("sm2", "derived-era5-land-daily-statistics", "volumetric_soil_water_layer_2", "daily_mean"),
    Field("pr", "reanalysis-era5-land", "total_precipitation", None, scale=1000.0),  # m -> mm
    Field("rsds", "reanalysis-era5-land", "surface_solar_radiation_downwards", None, scale=1e-6),  # J m-2 -> MJ m-2
]
CANONICAL_VARS = [f.canonical for f in FIELDS]


def cache_file(f: Field, month: str) -> "Path":  # noqa: F821
    stat = f.statistic or "00utc"
    return CACHE / f.dataset / f"{f.variable}_{stat}_{month}.nc"


def request(f: Field, year: int, month: int) -> dict:
    """CDS request for one field and calendar month (all days)."""
    days = [f"{d:02d}" for d in range(1, 32)]
    if f.statistic:
        return {"variable": [f.variable], "year": str(year), "month": [f"{month:02d}"], "day": days,
                "daily_statistic": f.statistic, "time_zone": "utc+00:00", "frequency": "1_hourly"}
    return {"variable": [f.variable], "year": str(year), "month": [f"{month:02d}"], "day": days,
            "time": ["00:00"], "data_format": "netcdf", "download_format": "unarchived"}
