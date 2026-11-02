"""Extrapolate the sample measurements to a full PRISM 800m daily + monthly Icechunk mirror.

Inputs: results/compression.csv (from compression_experiments.py) and the built subset store
(for Icechunk metadata overhead and a cross-check of chunk bytes).
Outputs: results/storage_estimate.csv (every codec) and results/storage_summary.csv (headline).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from prism_mirror.catalog import FREQUENCIES, NX, NY, RESULTS_DIR, VARIABLES

# Last grids listed on data.prism.oregonstate.edu at the time of the estimate (2026-11-02).
RECORD_END = {"daily": dt.date(2026, 11, 1), "monthly": dt.date(2026, 10, 1)}
ANNUAL_YEARS = 2025 - 1895 + 1
TB = 1e12


def n_steps(fname: str) -> int:
    return len(FREQUENCIES[fname].dates(RECORD_END[fname]))


def dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def store_overhead(store: Path) -> dict:
    """Icechunk metadata bytes (manifests, snapshots, transactions, refs) per stored chunk object."""
    chunk_dir = store / "chunks"
    chunk_files = [f for f in chunk_dir.rglob("*") if f.is_file()]
    chunk_bytes = sum(f.stat().st_size for f in chunk_files)
    meta_bytes = dir_bytes(store) - chunk_bytes
    return {
        "chunk_objects": len(chunk_files),
        "chunk_bytes": chunk_bytes,
        "metadata_bytes": meta_bytes,
        "metadata_bytes_per_chunk": meta_bytes / max(len(chunk_files), 1),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--codec", default="cf-uint+pcodec8", help="headline codec")
    p.add_argument("--store", default=str(Path(__file__).resolve().parents[1] / "data" / "prism_subset.icechunk"))
    args = p.parse_args()

    df = pd.read_csv(RESULTS_DIR / "compression.csv")
    df = df[df.layout == df.freq.map({f: f"{F.time_chunk}x{F.space_chunk}x{F.space_chunk}" for f, F in FREQUENCIES.items()})]

    overhead = store_overhead(Path(args.store)) if Path(args.store).exists() else None
    meta_per_chunk = overhead["metadata_bytes_per_chunk"] if overhead else 0.0

    rows = []
    for (codec, fname, var), g in df.groupby(["codec", "freq", "var"]):
        F = FREQUENCIES[fname]
        steps = n_steps(fname)
        per_step = g.stored_bytes / g.n_time  # one value per sampled block
        objects_per_step = g.n_objects / g.n_time
        rows.append({
            "codec": codec, "freq": fname, "var": var, "n_blocks": len(g), "n_steps": steps,
            "est_bytes": per_step.mean() * steps,
            "est_bytes_min": per_step.min() * steps,
            "est_bytes_max": per_step.max() * steps,
            "est_chunk_objects": objects_per_step.mean() * steps,
            "raw_float32_bytes": NX * NY * 4 * steps,
            "source_zip_bytes": (g.zip_bytes / g.n_time).mean() * steps,
            "ratio_vs_raw": (g.raw_bytes.sum() / g.stored_bytes.sum()),
            "encode_MBps": g.raw_bytes.sum() / g.encode_s.sum() / 1e6,
            "decode_MBps": g.raw_bytes.sum() / g.decode_s.sum() / 1e6,
        })
    est = pd.DataFrame(rows)
    est["est_metadata_bytes"] = est.est_chunk_objects * meta_per_chunk
    est.to_csv(RESULTS_DIR / "storage_estimate.csv", index=False)

    # Codec totals, only where every variable of both frequencies has been measured.
    full = est.groupby("codec").filter(lambda g: len(g) == 2 * len(VARIABLES))
    totals = (
        full.groupby(["codec", "freq"])[["est_bytes", "est_bytes_min", "est_bytes_max", "raw_float32_bytes", "source_zip_bytes", "est_metadata_bytes"]]
        .sum()
        .unstack("freq")
    )
    summary = pd.DataFrame({
        "daily_TB": totals[("est_bytes", "daily")] / TB,
        "monthly_TB": totals[("est_bytes", "monthly")] / TB,
        "total_TB": (totals[("est_bytes", "daily")] + totals[("est_bytes", "monthly")]) / TB,
        "total_min_TB": (totals[("est_bytes_min", "daily")] + totals[("est_bytes_min", "monthly")]) / TB,
        "total_max_TB": (totals[("est_bytes_max", "daily")] + totals[("est_bytes_max", "monthly")]) / TB,
        "metadata_GB": (totals[("est_metadata_bytes", "daily")] + totals[("est_metadata_bytes", "monthly")]) / 1e9,
    }).sort_values("total_TB")
    raw_tb = (totals[("raw_float32_bytes", "daily")] + totals[("raw_float32_bytes", "monthly")]).iloc[0] / TB
    zip_tb = (totals[("source_zip_bytes", "daily")] + totals[("source_zip_bytes", "monthly")]).iloc[0] / TB if len(totals) else np.nan
    summary["ratio_vs_raw"] = raw_tb / summary.total_TB
    summary.to_csv(RESULTS_DIR / "storage_summary.csv", float_format="%.4f")

    pd.set_option("display.width", 200)
    print(f"Record: {n_steps('daily')} days, {n_steps('monthly')} months; raw float32 {raw_tb:.2f} TB; source zips ~{zip_tb:.2f} TB")
    print(summary.round(3).to_string())
    if overhead:
        print("\nIcechunk subset store:", json.dumps(overhead))
    if args.codec in summary.index:
        h = summary.loc[args.codec]
        monthly_share = full[(full.codec == args.codec) & (full.freq == "monthly")].est_bytes.sum() / n_steps("monthly")
        annual_tb = monthly_share * ANNUAL_YEARS / TB  # annual grids compress roughly like monthly ones
        print(f"\nHeadline ({args.codec}): {h.total_TB:.2f} TB (range {h.total_min_TB:.2f}-{h.total_max_TB:.2f}) "
              f"+ ~{h.metadata_GB:.1f} GB Icechunk metadata; annual grids would add ~{annual_tb * 1000:.0f} GB")


if __name__ == "__main__":
    main()
