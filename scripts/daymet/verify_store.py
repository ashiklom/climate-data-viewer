"""Check the Daymet mirror against ORNL's Daymet single-pixel API (an independent service over the same data).

For each point, fetches a year of prcp, tmax, tmin, srad, vp and dayl and compares them with the mirror's nearest
1 km cell (the API returns the cell containing the point; values have 2 decimals).

    uv run python scripts/daymet/verify_store.py --year 2021
"""

from __future__ import annotations

import argparse

import numpy as np
import requests
import xarray as xr
from pyproj import Transformer

from climate_mirror import daymet, storage

API = "https://daymet.ornl.gov/single-pixel/api/data"
POINTS = {"New Haven CT": (41.31, -72.93), "Kansas": (38.5, -98.0), "Sierra Nevada": (38.06, -119.56),
          "Arkansas": (35.85, -92.06), "Florida": (27.5, -81.5), "Washington": (47.6, -121.5)}
API_NAMES = {"prcp": "prcp (mm/day)", "tmax": "tmax (deg c)", "tmin": "tmin (deg c)", "srad": "srad (W/m^2)",
             "vp": "vp (Pa)", "dayl": "dayl (s)"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, default=2021)
    p.add_argument("--vars", nargs="*", default=list(daymet.VARIABLES))
    args = p.parse_args()
    ds = xr.open_zarr(storage.open_mirror("daymet").readonly_session("main").store, group="daily",
                      consolidated=False, chunks=None).sel(time=str(args.year))
    to_lcc = Transformer.from_crs("EPSG:4326", daymet.PROJ4, always_xy=True)
    ok = True
    for name, (lat, lon) in POINTS.items():
        r = requests.get(API, params={"lat": lat, "lon": lon, "vars": ",".join(args.vars), "start": f"{args.year}-01-01",
                                      "end": f"{args.year}-12-31", "format": "json"}, timeout=120)
        r.raise_for_status()
        data = r.json()["data"]
        x, y = to_lcc.transform(lon, lat)
        for v in args.vars:
            api = np.asarray(data[API_NAMES[v]], dtype=np.float64)
            ours = ds[v].sel(x=x, y=y, method="nearest").values.astype(np.float64)[: len(api)]
            diff = np.nanmax(np.abs(ours - api))
            good = diff <= 0.0051 and not np.isnan(ours).any()
            ok &= good
            print(f"{name:14s} {v:5s} {len(api)} d  max |ours - API| {diff:.4f}  {'OK' if good else 'FAIL'}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
