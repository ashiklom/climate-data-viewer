"""Download the representative PRISM sample (whole time chunks, every variable) into data/raw.

Files already on disk are never re-requested: PRISM blocks a file after two downloads in 24 h.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import zipfile

import httpx
from tqdm import tqdm

from climate_mirror.prism.catalog import FREQUENCIES, VARIABLES, local_zip, sample_dates, url


def fetch(client: httpx.Client, src: str, dest) -> int:
    if dest.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".zip.part")
    with client.stream("GET", src) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for block in r.iter_bytes(1 << 20):
                f.write(block)
    with zipfile.ZipFile(tmp) as z:  # fail loudly on truncated downloads
        if z.testzip() is not None:
            raise IOError(f"corrupt zip: {src}")
    tmp.rename(dest)
    return dest.stat().st_size


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--freq", choices=list(FREQUENCIES), nargs="*", default=list(FREQUENCIES))
    p.add_argument("--vars", nargs="*", default=list(VARIABLES))
    args = p.parse_args()

    jobs = [
        (url(v, f, d), local_zip(v, f, d))
        for fname in args.freq
        for f in [FREQUENCIES[fname]]
        for d in sample_dates(f)
        for v in args.vars
    ]
    todo = [j for j in jobs if not j[1].exists()]
    print(f"{len(jobs)} files in sample, {len(todo)} to download")
    failures = []
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as client:
        with cf.ThreadPoolExecutor(args.workers) as ex, tqdm(total=len(todo), unit="file") as bar:
            futs = {ex.submit(fetch, client, s, d): s for s, d in todo}
            for fut in cf.as_completed(futs):
                try:
                    fut.result()
                except Exception as e:  # keep going; report at the end
                    failures.append((futs[fut], repr(e)))
                bar.update()
    for s, e in failures:
        print("FAILED", s, e)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
