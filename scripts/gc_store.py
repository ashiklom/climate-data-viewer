"""Drop a mirror's old history and delete the chunks only that history used.

Rewrites (re-mirrored days, re-derived groups, relayouts) leave the replaced chunks on disk, reachable only from
older snapshots. This expires every snapshot older than the `main` tip, then garbage-collects unreachable objects.
The tip, and therefore everything the site and scripts read, is unchanged. History before the tip is lost.

  uv run python scripts/gc_store.py nldas daymet --dry-run
  uv run python scripts/gc_store.py nldas daymet
"""

from __future__ import annotations

import argparse
import datetime as dt

from climate_mirror import storage


def gb(n: int) -> str:
    return f"{n / 1e9:.2f} GB"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mirrors", nargs="+", help="names from stores.toml [mirrors]")
    p.add_argument("--dry-run", action="store_true", help="report what would be deleted, change nothing")
    args = p.parse_args()

    for name in args.mirrors:
        repo = storage.open_mirror(name)
        if repo.list_branches() != {"main"} or repo.list_tags():
            raise SystemExit(f"{name}: has branches {repo.list_branches()} / tags {repo.list_tags()}; handle by hand")
        hist = list(repo.ancestry(branch="main"))
        tip = hist[0]
        print(f"{name}: {len(hist)} snapshots, tip {tip.id} ({tip.written_at:%Y-%m-%d %H:%M} UTC) {tip.message[:60]!r}")
        if args.dry_run:
            # Garbage only becomes visible to GC after expiry (itself a write), so report history size instead.
            print(f"  chunks referenced by any snapshot: {gb(repo.chunk_storage_stats().native_bytes)}")
            continue
        expired = repo.expire_snapshots(older_than=tip.written_at)
        r = repo.garbage_collect(dt.datetime.now(dt.UTC))
        after = list(repo.ancestry(branch="main"))
        assert after[0].id == tip.id, "tip changed"
        print(f"  expired {len(expired)} snapshots; deleted {r.chunks_deleted} chunks ({gb(r.bytes_deleted)}), "
              f"{r.manifests_deleted} manifests, {r.snapshots_deleted} snapshots, "
              f"{r.transaction_logs_deleted} transaction logs; history now {len(after)} snapshots")


if __name__ == "__main__":
    main()
