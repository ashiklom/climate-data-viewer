"""Generate site/src/generated/sources.json: where every dataset's maps, common-grid fields and point
series live, which native variables map to which canonical ones, and how to convert units.

Single source of truth = stores.toml + climate_mirror.{variables,web.daily_sources,...}. Local mirrors become
"/data/<name>.icechunk" (served by the Vite dev server); a mirror moved to S3 uses its public_url.

  uv run python scripts/web/write_sources.py
"""

from __future__ import annotations

import json
from dataclasses import asdict

from climate_mirror import chirps, era5, era5land, storage
from climate_mirror.paths import REPO_ROOT
from climate_mirror.variables import CANONICAL
from climate_mirror.web.daily_sources import DAY_WINDOW, MERRA2_CROSSWALK, PRISM_CROSSWALK

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
            "series": "maps",
            "hourly_series": {"kind": "zarr2", "url": ext("era5land_arco")["geo_url"], "auth": "cds",
                              "variables": {"pr": {"name": "tp", "scale": 1000.0}}, "time": "time",
                              "lat": "latitude", "lon": "longitude", "note": "hourly tp, CDS key (dev only)"},
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
    }
    for name, d in datasets.items():
        d["day_window"] = DAY_WINDOW[name]
        d["common"] = {"kind": "icechunk", "url": mirror_url(name), "group": COMMON}
        d["variables"] = sorted(d["maps"]["variables"])
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
