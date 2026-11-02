"""Repository-relative locations shared by all datasets."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"  # derived, rebuildable artifacts (stores, logs)
STORES_DIR = DATA_DIR / "stores"  # local Icechunk repos, one per dataset
CACHE_DIR = REPO_ROOT / "cache"  # permanent cache of raw source files, mirroring source URLs
RESULTS_DIR = REPO_ROOT / "results"


def cache_path(url: str) -> Path:
    """Permanent local path for a source URL: cache/<host>/<path>."""
    parts = urlsplit(url)
    return CACHE_DIR / parts.netloc / parts.path.lstrip("/")
