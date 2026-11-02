"""Copy CHIRPS v3 daily from dynamical.org's time-optimized Icechunk store into our `chirps` mirror,
map-optimized (group `daily`, one day per chunk, 1200x1800 tiles), as precipitation in mm/day.

dynamical's inner chunks span 365 days x 60 x 60, so we read one destination tile row (1200 latitude
rows, all longitudes) for the whole date range at once (~12.6 GB for a year): each source chunk is
fetched once and each destination chunk is written once (no read-modify-write).

  uv run python scripts/chirps/rechunk_dynamical.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import datetime as dt
import time

import numpy as np
import zarr

from climate_mirror import chirps, storage
from climate_mirror.derived import init_daily_group

BAND = chirps.DAILY_CHUNKS[1]  # destination tile height (a multiple of dynamical's 60-row inner chunks)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=dt.date.fromisoformat, required=True)
    p.add_argument("--end", type=dt.date.fromisoformat, required=True)
    args = p.parse_args()
    zarr.config.set({"async.concurrency": 128, "threading.max_workers": 32})

    src_repo = storage.open_external("chirps_dynamical")
    snapshot = next(src_repo.ancestry(branch="main")).id
    src = zarr.open_group(src_repo.readonly_session(snapshot_id=snapshot).store, mode="r")
    times = src["time"][:].astype("datetime64[s]")
    i0 = int(np.searchsorted(times, np.datetime64(args.start)))
    i1 = int(np.searchsorted(times, np.datetime64(args.end), side="right"))
    pr_src = src["precipitation_surface"]

    repo = storage.open_mirror("chirps", create=True)
    init_daily_group(
        repo, "daily", chirps.GRID, *chirps.DAILY_RECORD, ["pr"], chunks=chirps.DAILY_CHUNKS,
        attrs={
            "title": "CHIRPS v3 final daily precipitation (map-optimized copy)",
            "source": f"dynamical.org ucsb-chc-chirps-analysis-final v0.1.0, snapshot {snapshot}",
            "institution": "UCSB Climate Hazards Center; Icechunk by dynamical.org",
            "license": "CC-BY-4.0",
            "comment": "Daily values are CHIRPS pentad totals split into days with ERA5 (CHC final/rnl). "
                       "Values were bit-rounded to 8 mantissa bits by dynamical.org (<=0.2% relative). "
                       "Converted from kg m-2 s-1 to mm/day (x86400).",
        },
    )
    session = repo.writable_session("main")
    dst = zarr.open_group(session.store, path="daily", mode="r+")["pr"]
    d0 = (args.start - chirps.DAILY_RECORD[0]).days
    for y in range(0, chirps.GRID.ny, BAND):
        t0 = time.time()
        band = np.asarray(pr_src[i0:i1, y : y + BAND, :], dtype=np.float32) * np.float32(86400.0)
        dst[d0 : d0 + (i1 - i0), y : y + BAND, :] = band
        print(f"rows {y}-{y + BAND}: {band.nbytes / 1e6:.0f} MB in {time.time() - t0:.0f}s", flush=True)
    session.commit(f"daily: {args.start}..{args.end} from dynamical snapshot {snapshot}")


if __name__ == "__main__":
    main()
