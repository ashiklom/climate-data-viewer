"""Open Icechunk repos by dataset name, wherever stores.toml says they live (local or S3-compatible)."""

from __future__ import annotations

import tomllib
from functools import cache

import icechunk

from climate_mirror.paths import REPO_ROOT

CONFIG = REPO_ROOT / "stores.toml"


@cache
def config() -> dict:
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def _s3_storage(c: dict) -> icechunk.Storage:
    return icechunk.s3_storage(
        bucket=c["bucket"],
        prefix=c["prefix"],
        region=c.get("region"),
        endpoint_url=c.get("endpoint_url"),
        force_path_style=c.get("force_path_style", False),
        anonymous=c.get("anonymous", False),
        from_env=not c.get("anonymous", False),
    )


def mirror_storage(name: str) -> icechunk.Storage:
    """Storage for one of our mirrors (writable when credentials allow)."""
    c = config()["mirrors"][name]
    if c["target"] == "local":
        root = REPO_ROOT / config()["defaults"]["local_root"]
        return icechunk.local_filesystem_storage(str(root / f"{name}.icechunk"))
    if c["target"] == "s3":
        return _s3_storage(c)
    raise ValueError(f"unknown target {c['target']!r} for mirror {name}")


def open_mirror(name: str, create: bool = False) -> icechunk.Repository:
    storage = mirror_storage(name)
    return icechunk.Repository.open_or_create(storage) if create else icechunk.Repository.open(storage)


def open_external(name: str) -> icechunk.Repository:
    """Read-only Icechunk repo maintained by someone else (see [external.*] in stores.toml)."""
    c = config()["external"][name]
    if c.get("kind") != "icechunk":
        raise ValueError(f"{name} is not an Icechunk store")
    return icechunk.Repository.open(_s3_storage(c))


def local_path(name: str):
    """Filesystem path of a local mirror (None if it lives in object storage)."""
    c = config()["mirrors"][name]
    if c["target"] != "local":
        return None
    return REPO_ROOT / config()["defaults"]["local_root"] / f"{name}.icechunk"
