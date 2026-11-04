"""Daymet V4 R1 (1 km daily, North America, Lambert conformal conic): local Icechunk mirror of the CONUS part.

Source: the V4R1 NetCDF files as served anonymously by NCAR GDEX (dataset d682806, identical to ORNL DAAC's
files); only the source HDF5 chunks that overlap CONUS are fetched (byte ranges), see scripts/daymet/mirror.py.
Values carry two decimals (0.01 mm, degC, W m-2, Pa, s) and are stored as int32 counts of 0.01 (CF scale_factor).
The mirror keeps the native full North America grid; only the CONUS window is written.
"""

from __future__ import annotations

import datetime as dt

VARIABLES = {
    # name: (units, long_name)
    "prcp": ("mm/day", "daily total precipitation"),
    "tmax": ("degrees C", "daily maximum temperature"),
    "tmin": ("degrees C", "daily minimum temperature"),
    "srad": ("W/m2", "daylight average incident shortwave radiation"),
    "vp": ("Pa", "daily average vapor pressure"),
    "dayl": ("s", "daylength"),
}
DECIMALS = 2
INT_FILL = -(2**31)
SOURCE_FILL = -9999.0

URL = "https://data.gdex.ucar.edu/d682806/daymet_v4_daily_na_{var}_{year}.nc"
PROJ4 = "+proj=lcc +lat_1=25 +lat_2=60 +lat_0=42.5 +lon_0=-100 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs"

# Native grid (cell centers, metres): x ascending, y descending (north-up), 1 km.
NY, NX, RES = 8075, 7814, 1000.0
X0, Y0 = -4560250.0, 4984000.0
# CONUS window in source-chunk (300 x 300) units: rows 12-23, columns 6-26 (covers 24-50 N, 125.1-66.4 W).
WINDOW_Y = (3600, 7200)
WINDOW_X = (1800, 8100)
RECORD = (dt.date(1980, 1, 1), dt.date(2026, 12, 31))

CITATION = (
    "Thornton, M.M., R. Shrestha, Y. Wei, P.E. Thornton, and S-C. Kao (2022), Daymet: Daily Surface Weather Data on "
    "a 1-km Grid for North America, Version 4 R1, ORNL DAAC, doi:10.3334/ORNLDAAC/2129 (NCAR GDEX copy "
    "doi:10.5065/BTSS-N509); Thornton et al. (2021), Sci. Data 8, 190, doi:10.1038/s41597-021-00973-x."
)


def url(var: str, year: int) -> str:
    return URL.format(var=var, year=year)


def crs_wkt() -> str:
    from pyproj import CRS

    return CRS.from_proj4(PROJ4).to_wkt()


def dewpoint_c(vp_pa):
    """Dew point (degC) from vapour pressure (Pa), inverting the Tetens/Murray saturation formula Daymet uses
    (610.78 Pa, 17.269, 237.3 degC)."""
    import numpy as np

    x = np.log(vp_pa / 610.78)
    return 237.3 * x / (17.269 - x)


# Canonical variables: native ones by name, derived ones from native inputs (the site computes the same).
CANONICAL = {
    "pr": ("prcp",),
    "tasmax": ("tmax",),
    "tasmin": ("tmin",),
    "tas": ("tmax", "tmin"),  # (tmax + tmin) / 2, as PRISM tmean
    "rsds": ("srad", "dayl"),  # daylight-mean W m-2 x daylength s / 1e6 = MJ m-2 day-1
    "tdps": ("vp",),  # dew point of the daily mean vapour pressure
}
CANONICAL_VARS = list(CANONICAL)


def canonical(name: str, a: dict):
    """Canonical field `name` from native arrays `a` (already decoded to float)."""
    if name == "tas":
        return (a["tmax"] + a["tmin"]) / 2
    if name == "rsds":
        return a["srad"] * a["dayl"] / 1e6
    if name == "tdps":
        return dewpoint_c(a["vp"])
    return a[CANONICAL[name][0]]
