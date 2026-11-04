"""Expected values for the site parity test (site/src/lib/parity.test.ts).

Samples random (date, cell) pairs from every map source the site reads that currently has data,
reads them with xarray (CF decoding as in Python), and writes site/test-fixtures/parity.json.

  uv run python scripts/web/make_parity_fixtures.py [--n 50]
"""

from __future__ import annotations

import argparse
import json
import random

import numpy as np
import xarray as xr

from climate_mirror import storage
from climate_mirror.paths import REPO_ROOT
from climate_mirror.web.daily_sources import MERRA2_CROSSWALK, PRISM_CROSSWALK

OUT = REPO_ROOT / "site" / "test-fixtures" / "parity.json"


def mirror(name: str, group: str, chunks: dict | None = {}) -> xr.Dataset:  # noqa: B006
    repo = storage.open_mirror(name)
    return xr.open_zarr(repo.readonly_session("main").store, group=group, consolidated=False, chunks=chunks)


class Derived:
    """A Daymet canonical variable computed from native arrays (float64 arithmetic on float32 inputs, as the site)."""

    def __init__(self, ds: xr.Dataset, name: str):
        from climate_mirror import daymet

        self.ds, self.name, self.inputs = ds, name, daymet.CANONICAL[name]
        self.time = ds.time

    def sel(self, time: str) -> xr.DataArray:
        from climate_mirror import daymet

        day = self.ds.sel(time=time).isel(y=slice(*daymet.WINDOW_Y), x=slice(*daymet.WINDOW_X))
        a = {v: day[v].values.astype(np.float32).astype(np.float64) for v in self.inputs}
        with np.errstate(invalid="ignore", divide="ignore"):
            return xr.DataArray(daymet.canonical(self.name, a), dims=("y", "x"))


def candidates() -> list[tuple[str, str, str, xr.DataArray]]:
    """(dataset, kind, canonical var, DataArray with time/lat/lon dims) for sources the site maps."""
    out = []
    p = mirror("prism", "daily")
    for c, v in PRISM_CROSSWALK.items():
        out.append(("prism", "native", c, p[v].astype(np.float32)))
    for name in ("era5", "era5land", "chirps"):
        ds = mirror(name, "daily")
        for v in ds.data_vars:
            if v != "time_bnds":
                out.append((name, "native", v, ds[v]))
    for name in ("gridmet", "nldas"):
        ds = mirror(name, "daily", chunks=None)
        for v in ds.data_vars:
            if v != "time_bnds":
                out.append((name, "native", v, ds[v]))
    try:
        dm = mirror("daymet", "daily", chunks=None)
        from climate_mirror import daymet

        for c in daymet.CANONICAL_VARS:
            out.append(("daymet", "native", c, Derived(dm, c)))
    except Exception:  # noqa: BLE001, S110 (not built yet)
        pass
    for name in ("prism", "era5", "era5land", "chirps", "merra2", "imerg", "gridmet", "nldas", "daymet"):
        try:
            ds = mirror(name, "common_0p25/daily")
        except Exception:
            continue
        for v in ds.data_vars:
            if v != "time_bnds":
                out.append((name, "common", v, ds[v]))
    power = xr.open_zarr(storage.config()["external"]["merra2_power"]["spatial_url"], consolidated=True, chunks={})
    for c, v in MERRA2_CROSSWALK.items():
        out.append(("merra2", "native", c, power[v]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    cands = candidates()
    cases = []
    tries = 0
    while len(cases) < args.n and tries < args.n * 50:
        tries += 1
        ds, kind, var, da = rng.choice(cands)
        t = da.time.sel(time=slice("2021-01-01", "2021-12-31"))
        date = str(rng.choice(t.values))[:10]
        day = da.sel(time=date)
        # sample a cell with data (most cells are fill for PRISM/CHIRPS/unwritten days)
        vals = day.values
        finite = np.argwhere(np.isfinite(vals))
        if not len(finite):
            continue
        yi, xi = map(int, finite[rng.randrange(len(finite))])
        value = float(np.float32(vals[yi, xi]))
        if isinstance(da, Derived):  # indices within the CONUS window -> full grid
            from climate_mirror import daymet

            yi, xi = yi + daymet.WINDOW_Y[0], xi + daymet.WINDOW_X[0]
        cases.append({
            "dataset": ds, "kind": kind, "variable": var, "date": date, "yi": yi, "xi": xi,
            "value": value,
        })
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(cases, indent=1))
    by = {}
    for c in cases:
        by[(c["dataset"], c["kind"])] = by.get((c["dataset"], c["kind"]), 0) + 1
    print(f"{len(cases)} cases -> {OUT.relative_to(REPO_ROOT)}: {by}")


if __name__ == "__main__":
    main()
