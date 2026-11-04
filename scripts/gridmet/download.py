"""Download gridMET yearly NetCDF files (one per variable) into the permanent cache.

    uv run python scripts/gridmet/download.py --years 2021
"""

from __future__ import annotations

import argparse

import h5py
import httpx

from climate_mirror import gridmet


def fetch(client: httpx.Client, src: str, dest) -> int:
    if dest.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".nc.part")
    with client.stream("GET", src) as r:
        r.raise_for_status()
        expected = int(r.headers.get("content-length", -1))
        with open(tmp, "wb") as f:
            f.writelines(r.iter_bytes(1 << 20))
    if expected >= 0 and tmp.stat().st_size != expected:
        raise OSError(f"truncated: {src}")
    with h5py.File(tmp, "r"):  # fail loudly on corrupt files
        pass
    tmp.rename(dest)
    return dest.stat().st_size


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--years", type=int, nargs="+", required=True)
    p.add_argument("--vars", nargs="*", default=[f.source for f in gridmet.FIELDS])
    args = p.parse_args()
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, read=300)) as client:
        for year in args.years:
            for v in args.vars:
                n = fetch(client, gridmet.url(v, year), gridmet.local(v, year))
                print(f"{v} {year}: {'cached' if n == 0 else f'{n / 1e6:.0f} MB'}", flush=True)


if __name__ == "__main__":
    main()
