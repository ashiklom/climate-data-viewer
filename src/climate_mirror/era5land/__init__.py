"""ERA5-Land daily canonical variables (0.1 deg, global land, 1950-).

Sources: ARCO Zarr stores by default (arco.datastores.ecmwf.int, CDS key as Bearer token; `time` = time-chunked
hourly map tiles for maps, `geo` = geo-chunked long series for point series), with one documented exception:

- ARCO: pr daily maps (sum of hourly de-accumulated tp over (D 00, D+1 00], matching CDS daily totals exactly),
  and all point series in the website (hourly -> UTC days in the browser).
- CDS API, `derived-era5-land-daily-statistics` (tas, tasmax, tasmin, tdps, ps, sm1, sm2) and
  `reanalysis-era5-land` at 00 UTC (rsds): **reason** - ARCO holds hourly data only, so daily maps need all 24
  hourly fields (~41 MB/hour for these variables, ~360 GB for 2021 at ~2-4 MB/s here), whereas CDS aggregates
  server-side and ships one field per day (~24x less transfer). Raw NetCDFs cached under cache/cds.climate.copernicus.eu/.

sfcWind daily maps are not provided (daily mean speed needs hourly u10/v10: ~260 MB/day from ARCO); wind speed is
available in point series (ARCO sfc-wind, hourly).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from climate_mirror.derived import Grid
from climate_mirror.paths import CACHE_DIR

CDS_URL = "https://cds.climate.copernicus.eu/api"
_ARCO = "https://arco.datastores.ecmwf.int/cadl-arco-{kind}-{n}/arco/reanalysis_era5_land/sfc-{name}/{kind}Chunked.zarr"
ARCO_STORES = {"2m-temperature": "007", "wind": "008", "soil-water": "005", "radiation-heat": "010",
               "pressure-precipitation": "009"}
ARCO = {name: {k: _ARCO.format(kind=k, n=n, name=name) for k in ("time", "geo")} for name, n in ARCO_STORES.items()}
CACHE = CACHE_DIR / "cds.climate.copernicus.eu"
# Native grid is lat 90..-90 (1801), lon 0..359.9 (3600); we roll longitudes to -180..179.9.
GRID = Grid(north=90.0, west=-180.0, res=0.1, ny=1801, nx=3600)
CHUNKS = (1, 901, 1800)
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
    Field("rsds", "reanalysis-era5-land", "surface_solar_radiation_downwards", None, scale=1e-6),  # J m-2 -> MJ m-2
]
CDS_VARS = [f.canonical for f in FIELDS]
CANONICAL_VARS = ["pr", *CDS_VARS]  # pr from ARCO (scripts/era5land/derive_pr_arco.py)
GROUP_ATTRS = {
    "title": "ERA5-Land daily canonical variables (UTC days)",
    "source": "pr: ARCO Zarr sfc-pressure-precipitation (hourly tp summed over (D 00, D+1 00]); "
              "tas, tasmax, tasmin, tdps, ps, sm1, sm2: CDS derived-era5-land-daily-statistics; "
              "rsds: CDS reanalysis-era5-land at 00 UTC (24 h accumulation ending D+1 00 UTC)",
    "institution": "ECMWF / Copernicus Climate Change Service",
    "license": "CC-BY-4.0",
    "comment": "UTC days. Longitudes -180..180. sfcWind daily maps not provided (see climate_mirror.era5land).",
}


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
