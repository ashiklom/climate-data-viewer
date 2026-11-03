"""Download CHIRPS v3 GeoTIFFs (pentads, dekads, monthly) into the permanent cache
(cache/data.chc.ucsb.edu/products/CHIRPS/v3.0/...).

By default fetches the representative sample (whole time chunks). With --start/--end, fetches every period in
the whole time chunks overlapping that range instead. Files already on disk are never re-requested.

  uv run python scripts/chirps/download.py
  uv run python scripts/chirps/download.py --start 2021-01-01 --end 2021-12-31
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt

import httpx
from tqdm import tqdm

from climate_mirror.chirps.catalog import FREQUENCIES, local_tif, sample_dates, url


def fetch(client: httpx.Client, src: str, dest) -> int:
    if dest.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tif.part")
    with client.stream("GET", src) as r:
        r.raise_for_status()
        expected = int(r.headers.get("content-length", -1))
        with open(tmp, "wb") as f:
            for block in r.iter_bytes(1 << 20):
                f.write(block)
    if expected >= 0 and tmp.stat().st_size != expected:  # fail loudly on truncated downloads
        raise IOError(f"truncated: {src} ({tmp.stat().st_size} of {expected} bytes)")
    tmp.rename(dest)
    return dest.stat().st_size


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--start", type=dt.date.fromisoformat, help="fetch whole chunks overlapping [start, end]")
    p.add_argument("--end", type=dt.date.fromisoformat)
    args = p.parse_args()

    def dates_for(f):
        if args.start is None:
            return sample_dates(f)
        return [d for c in f.chunk_indices(args.start, args.end or args.start) for d in f.chunk_dates(c)]

    jobs = [(url(f, d.date()), local_tif(f, d.date())) for fname in args.freq for f in [FREQUENCIES[fname]] for d in dates_for(f)]
    todo = [j for j in jobs if not j[1].exists()]
    print(f"{len(jobs)} files selected, {len(todo)} to download", flush=True)
    failures = []
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as client:
        with cf.ThreadPoolExecutor(args.workers) as ex, tqdm(total=len(todo), unit="file", mininterval=30) as bar:
            futs = {ex.submit(fetch, client, s, d): s for s, d in todo}
            for fut in cf.as_completed(futs):
                try:
                    fut.result()
                except Exception as e:  # keep going; report at the end (rerun fetches only what is missing)
                    failures.append((futs[fut], repr(e)))
                bar.update()
    for s, e in failures:
        print("FAILED", s, e)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
