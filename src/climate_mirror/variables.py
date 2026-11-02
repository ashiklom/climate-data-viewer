"""Canonical variables shared by all datasets (CMIP-style short names, comparison-friendly units).

Each dataset maps its native variables onto these (see the per-dataset `DAILY` recipes); the website
uses the same names (exported by scripts/web/write_sources.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Canonical:
    name: str
    long_name: str
    units: str
    standard_name: str | None
    cell_methods: str  # over the day
    colormap: str  # sequential colormap for maps
    diff_colormap: str  # diverging colormap for A-B maps
    comparable_note: str = ""


CANONICAL: dict[str, Canonical] = {
    c.name: c
    for c in [
        Canonical("pr", "Precipitation", "mm day-1", "lwe_precipitation_rate", "time: sum", "precip", "BrBG"),
        Canonical("tas", "Mean 2 m air temperature", "degC", "air_temperature", "time: mean", "thermal", "RdBu_r",
                  "PRISM tmean is (tmin+tmax)/2, not a 24-hour mean."),
        Canonical("tasmax", "Maximum 2 m air temperature", "degC", "air_temperature", "time: maximum", "thermal", "RdBu_r",
                  "Reanalysis maxima use hourly values; station-based products use instantaneous extremes."),
        Canonical("tasmin", "Minimum 2 m air temperature", "degC", "air_temperature", "time: minimum", "thermal", "RdBu_r",
                  "Reanalysis minima use hourly values; station-based products use instantaneous extremes."),
        Canonical("tdps", "Mean 2 m dew point temperature", "degC", "dew_point_temperature", "time: mean", "haline", "RdBu_r"),
        Canonical("ps", "Mean surface pressure", "hPa", "surface_air_pressure", "time: mean", "dense", "RdBu_r"),
        Canonical("rsds", "Surface downwelling shortwave radiation", "MJ m-2 day-1",
                  "surface_downwelling_shortwave_flux_in_air", "time: sum", "solar", "RdBu_r"),
        Canonical("sfcWind", "Mean 10 m wind speed", "m s-1", "wind_speed", "time: mean", "speed", "RdBu_r",
                  "MERRA-2 (POWER) reports 2 m and 10 m wind; ERA5 uses hourly 10 m speed."),
        Canonical("sm1", "Surface-layer soil moisture", "m3 m-3", "volume_fraction_of_condensed_water_in_soil",
                  "time: mean", "rain", "BrBG",
                  "ERA5/ERA5-Land layer 1 is 0-7 cm; MERRA-2 GWETTOP is a 0-1 wetness fraction, not volumetric."),
        Canonical("sm2", "Second-layer soil moisture", "m3 m-3", "volume_fraction_of_condensed_water_in_soil",
                  "time: mean", "rain", "BrBG", "ERA5/ERA5-Land layer 2 is 7-28 cm."),
    ]
}
