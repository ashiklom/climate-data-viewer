"""NLDAS-2 (NLDAS Phase 2, 0.125 degree CONUS, hourly 1979-): local Icechunk mirror of the hourly primary forcing
(NLDAS_FORA0125_H v2.0, all 11 variables) and the Noah soil moisture layers used here (NLDAS_NOAH0125_H v2.0
SoilM_0_10cm, SoilM_10_40cm), plus daily canonical variables derived from them.

Source: NASA GES DISC via Earthdata Cloud (Earthdata login; no anonymous or CORS-enabled copy exists, and there
is no daily NLDAS-2 product). Hourly values are stored losslessly (decimal integers or float32, see DECIMALS; missing -9999 -> NaN/_FillValue),
time-last + pcodec (2.5-5.7x smaller than float32 pcodec for hourly fields).
File hour HH: instantaneous fields are valid at HH; sums (Rainf, PotEvap, CRainf_frac) cover HH-1..HH.
"""

from __future__ import annotations

import datetime as dt

from climate_mirror.derived import Grid

FORA_VARS = ["Tair", "Qair", "PSurf", "Wind_E", "Wind_N", "LWdown", "CRainf_frac", "CAPE", "PotEvap", "Rainf", "SWdown"]
NOAH_VARS = ["SoilM_0_10cm", "SoilM_10_40cm"]
FILL = -9999.0
# Source values sit on decimal grids (from their GRIB-1 encoding): stored as int32 counts of 10**-decimals with
# CF scale_factor (lossless: every decoded float32 is within 1 ulp of the source float32, checked on write).
# Qair is on a binary grid and stays float32. None = float32.
DECIMALS = {"Tair": 2, "Qair": None, "PSurf": 2, "Wind_E": 2, "Wind_N": 2, "LWdown": 2, "CRainf_frac": 4, "CAPE": 3,
            "PotEvap": 4, "Rainf": 4, "SWdown": 3, "SoilM_0_10cm": 2, "SoilM_10_40cm": 2}
INT_FILL = -(2**31)

FORA_URL = "https://data.gesdisc.earthdata.nasa.gov/data/NLDAS/NLDAS_FORA0125_H.2.0/{t:%Y}/{doy:03d}/NLDAS_FORA0125_H.A{t:%Y%m%d.%H}00.020.nc"
NOAH_OPENDAP = ("https://opendap.earthdata.nasa.gov/collections/C2069246977-GES_DISC/granules/"
                "NLDAS_NOAH0125_H.2.0:NLDAS_NOAH0125_H.A{t:%Y%m%d.%H}00.020.nc.dap.nc4")

# Source grid: lat ascending (south to north) 25.0625..52.9375, lon -124.9375..-67.0625, 0.125 degree.
NY, NX, RES, SOUTH, WEST = 224, 464, 0.125, 25.0625, -124.9375
GRID = Grid(north=SOUTH + (NY - 1) * RES, west=WEST, res=RES, ny=NY, nx=NX)  # daily maps: north to south
RECORD = (dt.date(1979, 1, 1), dt.date(2026, 12, 31))
CANONICAL_VARS = ["pr", "tas", "tasmax", "tasmin", "tdps", "ps", "rsds", "sfcWind", "sm1", "sm2"]

CITATION = (
    "NLDAS project (2018), NLDAS Primary Forcing Data L4 Hourly 0.125 x 0.125 degree V2.0, ed. D. Mocko, GES DISC, "
    "doi:10.5067/THUF4J1RLSYG; NLDAS Noah Land Surface Model L4 Hourly 0.125 x 0.125 degree V2.0, "
    "doi:10.5067/T4OW83T8EXDO; Xia et al. (2012), JGR 117, D03109, doi:10.1029/2011JD016048. "
    "Data acquired as part of the mission of NASA's Earth Science Division and archived and distributed by the "
    "Goddard Earth Sciences (GES) Data and Information Services Center (DISC)."
)


def fora_url(t: dt.datetime) -> str:
    return FORA_URL.format(t=t, doy=t.timetuple().tm_yday)


def noah_url(t: dt.datetime) -> str:
    return NOAH_OPENDAP.format(t=t)


def dewpoint_k(q, p):
    """Dew point (K) from specific humidity (kg/kg) and pressure (Pa): vapour pressure e = q p / (0.622 + 0.378 q),
    inverted with the saturation formula over water used by ECMWF (IFS: 611.21 Pa, 17.502, 32.19 K)."""
    import numpy as np

    e = q * p / (0.622 + 0.378 * q)
    x = np.log(e / 611.21)
    return (32.19 * x - 17.502 * 273.16) / (x - 17.502)


def daily(hourly: dict, ndays: int) -> dict:
    """Daily canonical fields (UTC days) from hourly arrays of shape (24 * ndays + 1, lat, lon) starting at D 00 UTC.

    As for ERA5: sums (Rainf) add the hours ending D 01..D+1 00 UTC; instantaneous fields (everything else,
    including SWdown, which NLDAS-2 marks "time: point") aggregate hours 00..23 UTC. Any missing hour -> missing."""
    import numpy as np

    n = 24 * ndays

    def inst(a):
        return a[:n].reshape(ndays, 24, *a.shape[1:])

    def acc(a):
        return a[1 : n + 1].reshape(ndays, 24, *a.shape[1:])

    t = inst(hourly["Tair"]) - 273.15
    return {
        "pr": acc(hourly["Rainf"]).sum(axis=1),  # kg m-2 = mm
        "tas": t.mean(axis=1),
        "tasmax": t.max(axis=1),
        "tasmin": t.min(axis=1),
        "tdps": (dewpoint_k(inst(hourly["Qair"]), inst(hourly["PSurf"])) - 273.15).mean(axis=1),
        "ps": inst(hourly["PSurf"]).mean(axis=1) / 100,
        "rsds": inst(hourly["SWdown"]).mean(axis=1) * 0.0864,  # W m-2 -> MJ m-2 day-1
        "sfcWind": np.hypot(inst(hourly["Wind_E"]), inst(hourly["Wind_N"])).mean(axis=1),
        "sm1": inst(hourly["SoilM_0_10cm"]).mean(axis=1) / 100,  # kg m-2 over 0.1 m -> m3 m-3
        "sm2": inst(hourly["SoilM_10_40cm"]).mean(axis=1) / 300,  # 0.3 m layer
    }
