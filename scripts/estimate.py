"""Extrapolate sample measurements to a full mirror of a dataset (--dataset) in Icechunk.

Inputs: results/<dataset>/compression.csv (from compression_experiments.py) and, if given, a
built store (for Icechunk metadata overhead per chunk object).
Outputs: results/<dataset>/storage_estimate.csv (per codec x frequency x variable) and
results/<dataset>/storage_summary.csv (per codec totals).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from climate_mirror import datasets

TB = 1e12


def dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def store_overhead(store: Path) -> dict:
    """Icechunk metadata bytes (manifests, snapshots, transactions, refs) per stored chunk object."""
    chunk_files = [f for f in (store / "chunks").rglob("*") if f.is_file()]
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
    p.add_argument("--dataset", choices=list(datasets.DATASETS), default="prism")
    p.add_argument("--codec", default="cf-uint+pcodec8", help="headline codec")
    p.add_argument("--store", help="built Icechunk store, for metadata overhead")
    args = p.parse_args()
    ds = datasets.get(args.dataset)
    ny, nx = ds.grid_shape
    freqs = list(ds.frequencies)
    steps = {f: ds.frequencies[f].n_steps(ds.record_end[f]) for f in freqs}

    df = pd.read_csv(ds.results_dir / "compression.csv")
    df = df[df.layout == df.freq.map({f: datasets.default_layout(F) for f, F in ds.frequencies.items()})]
    overhead = store_overhead(Path(args.store)) if args.store and Path(args.store).exists() else None
    meta_per_chunk = overhead["metadata_bytes_per_chunk"] if overhead else 0.0

    rows = []
    for (codec, fname, var), g in df.groupby(["codec", "freq", "var"]):
        n = steps[fname]
        per_step = g.stored_bytes / g.n_time  # one value per sampled block
        rows.append({
            "codec": codec, "freq": fname, "var": var, "n_blocks": len(g), "n_steps": n,
            "est_bytes": per_step.mean() * n,
            "est_bytes_min": per_step.min() * n,
            "est_bytes_max": per_step.max() * n,
            "est_chunk_objects": (g.n_objects / g.n_time).mean() * n,
            "raw_float32_bytes": nx * ny * 4 * n,
            "source_bytes": (g.zip_bytes / g.n_time).mean() * n,
            "ratio_vs_raw": g.raw_bytes.sum() / g.stored_bytes.sum(),
            "encode_MBps": g.raw_bytes.sum() / g.encode_s.sum() / 1e6,
            "decode_MBps": g.raw_bytes.sum() / g.decode_s.sum() / 1e6,
        })
    est = pd.DataFrame(rows)
    est["est_metadata_bytes"] = est.est_chunk_objects * meta_per_chunk
    est.to_csv(ds.results_dir / "storage_estimate.csv", index=False)

    # Codec totals, only where every variable of every frequency has been measured.
    full = est.groupby("codec").filter(lambda g: len(g) == len(freqs) * len(ds.variables))
    cols = ["est_bytes", "est_bytes_min", "est_bytes_max", "raw_float32_bytes", "source_bytes", "est_metadata_bytes"]
    by_freq = full.groupby(["codec", "freq"])[cols].sum().unstack("freq")
    summary = pd.DataFrame({f"{f}_TB": by_freq[("est_bytes", f)] / TB for f in freqs})
    summary["total_TB"] = by_freq["est_bytes"].sum(axis=1) / TB
    summary["total_min_TB"] = by_freq["est_bytes_min"].sum(axis=1) / TB
    summary["total_max_TB"] = by_freq["est_bytes_max"].sum(axis=1) / TB
    summary["metadata_GB"] = by_freq["est_metadata_bytes"].sum(axis=1) / 1e9
    summary = summary.sort_values("total_TB")
    raw_tb = by_freq["raw_float32_bytes"].sum(axis=1).iloc[0] / TB
    src_tb = by_freq["source_bytes"].sum(axis=1).iloc[0] / TB
    summary["ratio_vs_raw"] = raw_tb / summary.total_TB
    summary.to_csv(ds.results_dir / "storage_summary.csv", float_format="%.4f")

    pd.set_option("display.width", 200)
    print(f"[{ds.name}] record: " + ", ".join(f"{steps[f]} {f} steps" for f in freqs)
          + f"; raw float32 {raw_tb:.3f} TB; source files ~{src_tb:.3f} TB")
    print(summary.round(4).to_string())
    if overhead:
        print("\nIcechunk store:", json.dumps(overhead))
    if args.codec in summary.index:
        h = summary.loc[args.codec]
        print(f"\nHeadline ({args.codec}): {h.total_TB:.3f} TB (range {h.total_min_TB:.3f}-{h.total_max_TB:.3f}) "
              f"+ ~{h.metadata_GB:.2f} GB Icechunk metadata")


if __name__ == "__main__":
    main()
