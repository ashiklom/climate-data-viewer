"""Check the NLDAS-2 mirror against NASA's Giovanni time-series service (an independent copy of the same data).

For each point, fetches a year of hourly Tair, Rainf and SoilM_0_10cm from Giovanni (CSV, 2 decimals), compares
them with our hourly mirror, then recomputes daily tas/tasmax/tasmin, pr and sm1 from the Giovanni values with the
same UTC-day rules and compares with our `daily` group.

    uv run python scripts/nldas/verify.py --year 2021
"""

from __future__ import annotations

import argparse
import io

import numpy as np
import pandas as pd
import xarray as xr

from climate_mirror import storage
from climate_mirror.earthdata import EarthdataSession

GIOVANNI = "https://api.giovanni.earthdata.nasa.gov/proxy-timeseries"
POINTS = {"New Haven CT": (41.3125, -72.9375), "Kansas": (38.5625, -98.0625), "Sierra Nevada": (38.0625, -119.5625)}
VARS = {"Tair": "NLDAS_FORA0125_H_2_0_Tair", "Rainf": "NLDAS_FORA0125_H_2_0_Rainf",
        "SoilM_0_10cm": "NLDAS_NOAH0125_H_2_0_SoilM_0_10cm"}


def giovanni(session: EarthdataSession, var: str, lat: float, lon: float, t0: str, t1: str) -> pd.Series:
    r = session.get(GIOVANNI, params={"data": var, "location": f"[{lat},{lon}]", "time": f"{t0}/{t1}"}, timeout=600)
    r.raise_for_status()
    text = r.text[r.text.index("Timestamp (UTC)"):]
    df = pd.read_csv(io.StringIO(text), parse_dates=[0], index_col=0)
    return df.iloc[:, 0].replace(-9999, np.nan)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2021)
    args = p.parse_args()
    y = args.year
    repo = storage.open_mirror("nldas")
    hourly = xr.open_zarr(repo.readonly_session("main").store, group="hourly", consolidated=False, chunks=None)
    daily = xr.open_zarr(repo.readonly_session("main").store, group="daily", consolidated=False, chunks=None)
    session = EarthdataSession()
    ok = True
    for name, (lat, lon) in POINTS.items():
        g = {v: giovanni(session, gv, lat, lon, f"{y}-01-01T00:00:00", f"{y + 1}-01-01T00:00:00") for v, gv in VARS.items()}
        for v, s in g.items():
            ours = hourly[v].sel(lat=lat, lon=lon, time=s.index.values).values.astype(np.float64)
            diff = np.nanmax(np.abs(ours - s.values))
            same_missing = np.array_equal(np.isnan(ours), np.isnan(s.values))
            good = same_missing and diff <= 0.005 + 1e-6  # Giovanni rounds to 2 decimals
            ok &= good
            print(f"{name:14s} hourly {v:13s} {len(s)} h  max |ours - Giovanni| {diff:.4f}  {'OK' if good else 'FAIL'}")
        days = pd.date_range(f"{y}-01-01", f"{y}-12-31", freq="D")
        n = len(days)
        t = g["Tair"].values
        ref = {
            "tas": t[: 24 * n].reshape(n, 24).mean(1) - 273.15,
            "tasmax": t[: 24 * n].reshape(n, 24).max(1) - 273.15,
            "tasmin": t[: 24 * n].reshape(n, 24).min(1) - 273.15,
            "pr": g["Rainf"].values[1 : 24 * n + 1].reshape(n, 24).sum(1),
            "sm1": g["SoilM_0_10cm"].values[: 24 * n].reshape(n, 24).mean(1) / 100,
        }
        tol = {"tas": 0.005, "tasmax": 0.005, "tasmin": 0.005, "pr": 24 * 0.00005 + 1e-4, "sm1": 0.00005}
        for v, r in ref.items():
            ours = daily[v].sel(lat=lat, lon=lon, time=days).values.astype(np.float64)
            diff = np.nanmax(np.abs(ours - r))
            good = diff <= tol[v] + 1e-5
            ok &= good
            print(f"{name:14s} daily  {v:13s} {n} d  max |ours - from Giovanni| {diff:.5f}  {'OK' if good else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
