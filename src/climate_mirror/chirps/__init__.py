"""CHIRPS v3 (UCSB Climate Hazards Center): 0.05 deg, 60N-60S, 1981-.

- Daily: read from dynamical.org's Icechunk copy (stores.toml [external.chirps_dynamical]; ERA5-split
  pentads, 8-bit mantissa rounding, time-optimized chunks); we keep a map-optimized copy in our `chirps`
  mirror (group `daily`) for the website.
- Native pentads/dekads/monthly from CHC GeoTIFFs: groups `pentads`, `dekads`, `monthly` (catalog.py, io.py,
  scripts/chirps/build_store.py); see docs/chirps.md.
"""

from __future__ import annotations

import datetime as dt

from climate_mirror.derived import Grid

GRID = Grid(north=59.975, west=-179.975, res=0.05, ny=2400, nx=7200)
DAILY_RECORD = (dt.date(1981, 1, 1), dt.date(2026, 9, 30))
DAILY_CHUNKS = (1, 1200, 1800)  # matches dynamical's shard tiles; 8 tiles per day
