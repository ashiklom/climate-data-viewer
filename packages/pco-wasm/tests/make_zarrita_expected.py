"""Expected raw (undecoded-CF) values for tests/zarrita.test.mjs, read with icechunk + zarr-python.

Run from the repo root:  uv run python packages/pco-wasm/tests/make_zarrita_expected.py
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import zarr

from climate_mirror import storage
from climate_mirror.prism.catalog import DAILY

OUT = Path(__file__).parent / "fixtures" / "zarrita_expected.json"
ERA5_URL = storage.config()["external"]["era5_earthmover"]["public_url"]


def case(label: str, repo, url: str, path: str, selection: list) -> dict:
    arr = zarr.open_array(repo.readonly_session("main").store, path=path, mode="r")
    sel = tuple(slice(*s) if isinstance(s, list) else s for s in selection)
    values = np.asarray(arr[sel])
    return {
        "label": label,
        "url": url,
        "path": "/" + path,
        "selection": selection,
        "shape": list(values.shape),
        "values": [None if (isinstance(v, float) and np.isnan(v)) else v for v in values.ravel().tolist()],
    }


def main() -> None:
    era5 = storage.open_external("era5_earthmover")
    cases = [
        case("ERA5 t2m map window (Earthmover, spatial, pcodec)", era5, ERA5_URL,
             "single/spatial/t2m", [714420, [400, 410], [1100, 1110]]),
        case("ERA5 tp point series (Earthmover, temporal, pcodec)", era5, ERA5_URL,
             "single/temporal/tp", [[714400, 714424], 195, 1148]),
    ]
    prism_path = storage.local_path("prism")
    if prism_path and prism_path.exists():
        i = DAILY.index_of(dt.date(2021, 10, 10))
        cases.append(case("PRISM daily ppt window (local mirror, cf-uint+pcodec, raw uint32)", storage.open_mirror("prism"),
                          "local:prism.icechunk", "daily/ppt", [i, [1500, 1510], [5800, 5810]]))
    OUT.write_text(json.dumps(cases, indent=1))
    print(f"{len(cases)} cases -> {OUT}")


if __name__ == "__main__":
    main()
