"""Fetch the CDS-sourced ERA5-Land daily fields (see climate_mirror.era5land for why these use CDS) from the CDS API into the permanent cache (one file per field and month).

Cached files are never re-requested. Accumulated fields (00 UTC) also fetch the month after --end, whose
first day holds the total for the last day of --end's month.

  uv run python scripts/era5land/fetch_cds.py --start 2021-01 --end 2021-12
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import time

import cdsapi
import pandas as pd

from climate_mirror import credentials, era5land


def fetch(f: era5land.Field, month: pd.Period) -> str:
    out = era5land.cache_file(f, str(month))
    if out.exists():
        return f"cached {out.name}"
    out.parent.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client(url=era5land.CDS_URL, key=credentials.get("cds_api_key"), quiet=True, progress=False)
    t0 = time.time()
    tmp = out.with_suffix(".nc.part")
    client.retrieve(f.dataset, era5land.request(f, month.year, month.month), str(tmp))
    tmp.rename(out)
    return f"{out.name}: {out.stat().st_size / 1e6:.0f} MB in {time.time() - t0:.0f}s"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="YYYY-MM")
    p.add_argument("--end", required=True, help="YYYY-MM")
    p.add_argument("--fields", nargs="*", default=era5land.CDS_VARS)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()
    months = pd.period_range(args.start, args.end, freq="M")
    jobs = []
    for f in era5land.FIELDS:
        if f.canonical not in args.fields:
            continue
        ms = list(months) + ([months[-1] + 1] if f.statistic is None else [])
        jobs += [(f, m) for m in ms]
    print(f"{len(jobs)} field-months", flush=True)
    failures = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fetch, f, m): (f.canonical, str(m)) for f, m in jobs}
        for fut in cf.as_completed(futs):
            try:
                print(fut.result(), flush=True)
            except Exception as e:  # report and continue; rerun fetches only what is missing
                failures.append((futs[fut], repr(e)[:300]))
    for job, e in failures:
        print("FAILED", job, e, flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
