"""Generate site/src/generated/sources.json: where every dataset's maps, common-grid fields and point
series live, which native variables map to which canonical ones, and how to convert units.

Single source of truth = stores.toml + climate_mirror.{variables,web.daily_sources,...}. Local mirrors become
"/data/<name>.icechunk" (served by the Vite dev server); a mirror moved to S3 uses its public_url.

  uv run python scripts/web/write_sources.py
"""

from __future__ import annotations

import json
from dataclasses import asdict

from climate_mirror import chirps, daymet, era5, era5land, gridmet, nldas, storage
from climate_mirror.paths import REPO_ROOT
from climate_mirror.variables import CANONICAL
from climate_mirror.web.daily_sources import (
    DAY_WINDOW,
    MERRA2_CROSSWALK,
    PRISM_CROSSWALK,
)

DAYMET_OPS = {"tas": "mean", "rsds": "daylight_energy", "tdps": "dewpoint_tetens"}  # site/src/lib/derive.ts
OUT = REPO_ROOT / "site" / "src" / "generated" / "sources.json"
COMMON = "common_0p25/daily"


def mirror_url(name: str) -> str:
    c = storage.config()["mirrors"][name]
    return f"/data/{name}.icechunk" if c["target"] == "local" else c["public_url"]


def ext(name: str) -> dict:
    return storage.config()["external"][name]


def identity(vars_: list[str]) -> dict:
    return {v: {"name": v} for v in vars_}


def main() -> None:
    era5_vars = era5.CANONICAL_VARS
    datasets = {
        "prism": {
            "label": "PRISM 800m (CONUS)",
            "maps": {"kind": "icechunk", "url": mirror_url("prism"), "group": "daily", "cf": True,
                     "variables": {c: {"name": v} for c, v in PRISM_CROSSWALK.items()}},
            "series": "maps",
        },
        "chirps": {
            "label": "CHIRPS v3 0.05° (land 60N–60S)",
            "maps": {"kind": "icechunk", "url": mirror_url("chirps"), "group": "daily", "variables": identity(["pr"])},
            "series": {"kind": "icechunk", "url": ext("chirps_dynamical")["public_url"], "group": "",
                       "variables": {"pr": {"name": "precipitation_surface", "scale": 86400.0}},
                       "time": "daily", "lat": "latitude", "lon": "longitude"},
        },
        "era5": {
            "label": "ERA5 0.25°",
            "maps": {"kind": "icechunk", "url": mirror_url("era5"), "group": "daily", "variables": identity(era5_vars)},
            "series": "maps",
            "hourly_series": {"kind": "icechunk", "url": ext("era5_earthmover")["public_url"], "group": "single/temporal",
                              "note": "hourly; pcodec", "time": "valid_time", "lat": "latitude", "lon": "longitude"},
        },
        "era5land": {
            "label": "ERA5-Land 0.1°",
            "maps": {"kind": "icechunk", "url": mirror_url("era5land"), "group": "daily", "variables": identity(era5land.CANONICAL_VARS)},
            # Point series: ARCO geo-chunked stores (hourly; aggregated to UTC days in the browser like ERA5).
            "series": {"kind": "arco_hourly", "auth": "cds", "time": "time", "lat": "latitude", "lon": "longitude",
                       "stores": {v: era5land.ARCO[store]["geo"] for store, vs in {
                           "pressure-precipitation": ["tp", "sp"], "2m-temperature": ["t2m", "d2m"],
                           "wind": ["u10", "v10"], "soil-water": ["swvl1", "swvl2"], "radiation-heat": ["ssrd"]}.items()
                           for v in vs}},
            "series_variables": [*era5land.CANONICAL_VARS, "sfcWind"],
        },
        "merra2": {
            "label": "MERRA-2 0.5°×0.625° (NASA POWER)",
            "maps": {"kind": "zarr2", "url": ext("merra2_power")["spatial_url"], "consolidated": True,
                     "variables": {c: {"name": v} for c, v in MERRA2_CROSSWALK.items()}, "time": "time"},
            "series": {"kind": "zarr2", "url": ext("merra2_power")["temporal_url"], "consolidated": True,
                       "variables": {c: {"name": v} for c, v in MERRA2_CROSSWALK.items()}, "time": "time"},
        },
        "imerg": {
            "label": "IMERG Final 0.1° (NASA POWER)",
            "maps": {"kind": "zarr2", "url": ext("imerg_power")["spatial_url"], "consolidated": True,
                     "variables": {"pr": {"name": "IMERG_PRECTOT"}}, "time": "time"},
            "series": {"kind": "zarr2", "url": ext("imerg_power")["temporal_url"], "consolidated": True,
                       "variables": {"pr": {"name": "IMERG_PRECTOT"}}, "time": "time"},
        },
        "gridmet": {
            "label": "gridMET 4km (CONUS)",
            "maps": {"kind": "icechunk", "url": mirror_url("gridmet"), "group": "daily", "cf": True,
                     "variables": identity(gridmet.CANONICAL_VARS)},
            "series": "maps",
            "series_note": "gridMET mirror (one-day tiles in 32-day shards)",
        },
        "nldas": {
            "label": "NLDAS-2 0.125° (CONUS)",
            "maps": {"kind": "icechunk", "url": mirror_url("nldas"), "group": "daily",
                     "variables": identity(nldas.CANONICAL_VARS)},
            "series": "maps",
            "series_note": "NLDAS-2 mirror, daily from hourly (one-day tiles in 32-day shards)",
        },
        "daymet": {
            "label": "Daymet 1km (CONUS)",
            "maps": {"kind": "icechunk", "url": mirror_url("daymet"), "group": "daily", "cf": True,
                     # tas, rsds, tdps are computed from native arrays (climate_mirror.daymet.canonical; site derive.ts)
                     "variables": {c: ({"name": ins[0]} if len(ins) == 1 and c not in DAYMET_OPS else
                                       {"inputs": list(ins), "op": DAYMET_OPS[c]})
                                   for c, ins in daymet.CANONICAL.items()}},
            "series": "maps",
            "series_note": "Daymet mirror (one-day 1 km tiles in 32-day shards)",
        },
    }
    datasets["prism"]["series_note"] = "PRISM mirror (one-day chunks in 32-day shards)"
    for name, d in datasets.items():
        d["day_window"] = DAY_WINDOW[name]
        d["common"] = {"kind": "icechunk", "url": mirror_url(name), "group": COMMON}
        d["variables"] = sorted(d["maps"]["variables"])
        d["series_variables"] = sorted(d.get("series_variables", d["variables"]))
    out = {
        "canonical": {k: asdict(v) for k, v in CANONICAL.items()},
        "common_grid": {"res": era5.GRID.res, "north": era5.GRID.north, "west": era5.GRID.west,
                        "ny": era5.GRID.ny, "nx": era5.GRID.nx},
        "grids": {"chirps": asdict(chirps.GRID), "era5land": asdict(era5land.GRID), "era5": asdict(era5.GRID)},
        "prototype_period": ["2021-01-01", "2021-12-31"],
        "datasets": datasets,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
