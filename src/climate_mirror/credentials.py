"""Local credentials from _credentials.toml (gitignored). Values are never printed or logged."""

from __future__ import annotations

import tomllib
from functools import cache

from climate_mirror.paths import REPO_ROOT

PATH = REPO_ROOT / "_credentials.toml"


@cache
def _load() -> dict:
    if not PATH.exists():
        raise FileNotFoundError(f"{PATH.name} not found; see README for the expected keys")
    with open(PATH, "rb") as f:
        return tomllib.load(f)


def get(key: str) -> str:
    try:
        return _load()[key]
    except KeyError:
        raise KeyError(f"{key!r} missing from {PATH.name}") from None


def cds_headers() -> dict[str, str]:
    """HTTP headers for the ECMWF data stores (ARCO Zarr), authenticated with the CDS API key."""
    return {"Authorization": f"Bearer {get('cds_api_key')}"}
