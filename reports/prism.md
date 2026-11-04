# PRISM 800m in Icechunk: layout, compression, and full-mirror storage estimate

*Generated from `results/prism/*.csv` on 2026-11-02. The sample covers all 9 PRISM variables over the full CONUS grid.*

## Headline

| | Daily | Monthly | Total |
|---|---|---|---|
| Record (as of 2026-11-01) | 16,741 days (1981–) | 1,582 months (1895–) | |
| Raw float32 | 13.15 TB | 1.24 TB | **14.39 TB** |
| PRISM source zips (LZW COG + metadata) | | | ~6.95 TB |
| **Icechunk, `cf-uint+pcodec8` (recommended)** | **1.79 TB** | **0.17 TB** | **1.96 TB** (1.72–2.30) |
| Icechunk, `cf-uint+pcodec12` | 1.73 TB | 0.17 TB | 1.89 TB |
| Icechunk, `pcodec8` on float32 (bit-exact) | 2.66 TB | 0.25 TB | 2.91 TB |
| Icechunk, `zstd3` on float32 (widest reader support) | 3.39 TB | 0.33 TB | 3.72 TB |

- The range comes from the min and max per-variable block in the sample.
- Icechunk metadata (manifests, snapshots) is about 49 bytes per chunk, or roughly 0.07 GB for the full mirror.
- Annual grids, which are not included above, would add about 14 GB.
- The subset store verifies the extrapolation: the experiments predicted 14.1683 GB of chunks for the stored blocks, and the Icechunk store holds 14.168 GB.

## Sample and layout

- **Sample:**
  - Daily: 3 whole time chunks of 32 days each, starting 1985-01-12, 2003-07-09 and 2021-09-28.
  - Monthly: 3 whole years, 1900, 1960 and 2020.
  - All 9 variables (ppt, tmin, tmax, tmean, tdmean, vpdmin, vpdmax, soltotal, solslope), over the full 7025 × 3105 grid. That is 1,188 grid packages and 50 GB of zips.
- **Chunks:** daily `(32, 256, 256)` at first (see the map-friendly daily layout below for the current one), monthly
  `(12, 256, 256)` (one calendar year), 8 MiB / 3 MiB raw.
  - These balance full-map reads (∝ N_space · t) against full-record pixel series (∝ N_time · s²).
  - One daily map touches 364 chunks; a 46-year pixel series touches 524.
  - On the local store, a full daily map reads in 0.6 s and a 96-step pixel series in 0.01 s.
- **Empty chunks:** 44.5% of pixels are nodata, and 37% of spatial chunks (ocean, Canada, Mexico) are entirely NaN. Those are never written (`write_empty_chunks=False`).
- **Layout alternatives** (`cf-uint+pcodec8`, ratio vs raw float32):

  | Daily layout | Ratio | MB/object | | Monthly layout | Ratio | MB/object |
  |---|---|---|---|---|---|---|
  | **shard 32×256×256 / inner 32×64×64** | **7.83** | 1.56 | | **shard 12×256×256 / 12×64×64** | **7.32** | 0.63 |
  | 32×128×128 | 7.73 | 0.42 | | 12×128×128 | 7.23 | 0.17 |
  | 16×256×256 | 7.44 | 0.82 | | 12×256×256 (chosen) | 7.23 | 0.64 |
  | 32×256×256 (chosen) | 7.35 | 1.67 | | 12×512×512 | 6.59 | 2.44 |
  | 8×512×512 / 32×512×512 | 7.03 | 1.5 / 6.1 | | 6×512×512 | 6.59 | 1.22 |

  Smaller spatial tiles skip more coastline-empty area. **For the full mirror, the sharded layout is the better choice:** about 6% smaller, the same object count and map cost, and point-series reads drop to 64×64 inner chunks, 16× less data per point. One caveat: zarr v3 readers without sharding support can't read it. zarrita, zarr-python and icechunk-js all support it.

### Map-friendly daily layout (current, 2026-11-04)

The comparison website showed the cost of 32-day chunks: one daily map of CONUS fetched 226 MB (364 chunks of 32
days) and took 2.9 s in the browser even from local disk. The daily group now uses **32 × 512 × 512 shards of one-day
256 × 256 chunks** (`catalog.DAILY`; existing data rewritten in place by `scripts/prism/relayout_daily.py`). The
monthly group is unchanged.

Layout test on two 32-day blocks of 2021 (`scripts/prism/map_layouts.py`, `results/prism/map_layouts.csv`), per day,
`ppt` / `tmean`:

| Layout | Storage vs 32×256×256 | CONUS map | Point series, one year | Point series, full record |
|---|---|---|---|---|
| 32×256×256 (before) | 1 | 193 / 361 MB, 364 objects | 6 / 10 MB, 11 objects | 276 / 473 MB, 523 objects |
| 8×256×256 | 1.00 / 1.00 | 51 / 75 MB | 6 / 10 MB, 46 | 276 / 473 MB, 2,093 |
| 1×256×256 | 0.90 / 0.98 | 7.0 / 9.3 MB | 5 / 10 MB, 365 | 248 / 466 MB, 16,741 |
| 1×512×512 | 0.99 / 1.05 | 7.6 / 10 MB, 98 objects | 8 / 16 MB, 365 | 364 / 733 MB, 16,741 |
| **shards 32×512×512 of 1×256×256 (chosen)** | **0.90 / 0.985** | **7.1 / 9.5 MB** | 5 / 10 MB, 365 ranges | 249 / 467 MB, 16,741 ranges |
| 32×256×256 + 4×/16× overviews (1-day chunks) | 1.11 / 1.13 | 0.8 / 1.3 MB (4× level) | as before | as before |

- One-day chunks compress as well as or better than 32-day ones under pcodec, so the full-mirror daily estimate
  above (1.79 TB) is an upper bound: by this test the new layout needs about 2–10% less.
- A map now reads 1/32 of the data. A point series reads the same bytes in more requests (one byte range per day,
  from 32-day shard objects, so the object count is unchanged).
- Overviews alone don't fix mid-zoom maps: a view of a few states still reads native 32-day tiles. They could be added
  on top of this layout later to cut wide-view requests (28 instead of 364) for remote hosting.
- Measured on the local store (`results/read_benchmark*.csv`): a CONUS map in Python 0.33 s → 0.06 s; in the site
  2.9 s → 1.2 s and 226 MB → 6.9 MB. Point series: full record 0.03 s → 0.11 s in Python; one year in the site
  0.08 s → 0.13 s (386 range requests instead of 21).
- **xarray:** `xr.open_zarr(..., chunks={})` would make one dask chunk per one-day inner chunk (about 6 million per
  variable) and is slow. `climate_mirror.prism.store.open_prism()` uses one dask chunk per shard and a lazy float32
  cast, so maps and point series read only the chunks they need (map 0.07 s, full-record series 0.3 s). Plain
  `xr.open_zarr(..., chunks=None)` is also fast.

## Codecs (all lossless at the integer level; see harmonization below)

Encode and decode throughput is aggregate over 18 threads, measured on the sample:

| Codec | Ratio | Encode MB/s | Decode MB/s |
|---|---|---|---|
| none (empty-chunk skipping only) | 1.46 | 3,876 | 6,999 |
| zstd3 | 3.87 | 3,533 | 5,984 |
| pcodec8 (float32) | 4.95 | 4,569 | 6,221 |
| cf-uint+zstd3 | 4.39 | 2,053 | 5,562 |
| cf-uint+shuffle-zstd9 | 4.96 | 1,460 | 2,879 |
| **cf-uint+pcodec8** | **7.34** | 3,479 | 6,615 |
| cf-uint+pcodec12 | 7.60 | 2,242 | 6,933 |

- **Integer packing:** `cf-uint` stores values as harmonized decimal integers. Each variable has one CF `scale_factor` = 1e-4 and an `add_offset` equal to its lower plausible bound; uint32 uses a `_FillValue` sentinel.
- **Why it wins:** packing is the biggest single gain (pcodec 4.95 → 7.34) because every PRISM value is a short decimal.
- **Codecs that didn't help:**
  - pcodec level 12 adds only about 4% at roughly 60% of the encode speed.
  - A time-last transpose before compression makes things worse.
  - Signed int32 and unsigned-with-offset come out within 0.5% of each other under pcodec. (Unsigned helps byte-oriented codecs slightly.)
- **Ratio per variable (cf-uint+pcodec8):**
  - Daily ppt 14.6× (mostly zeros).
  - Temperatures 7.7–8.7× daily and 9.4–9.9× monthly.
  - VPD and solar 5.7–7.4×.
- **Caveat: browser support.** pcodec has no browser decoder today, so `pcodec` stores need a WASM codec to be read on the web. That is a planned spike; zstd is the fallback.

## Harmonization of float32 representations (not bit-exact, by design)

PRISM grids encode the same decimal values in float32 in different ways, varying by grid and era, even within one variable:

| Style | Construction | Seen in (sample) |
|---|---|---|
| div-3 | `float32(k / 1000)` | ppt ≤1960 and 2021, tdmean/vpd/sol, 2021 temperatures |
| mul-3 | `float32(k) * float32(0.001)` | temperatures 1985–2020, ppt 2020 monthly |
| mul-4 | `float32(k) * float32(1e-4)` | most tmin monthly 2020 |
| other | unrounded floats | 10–20% of values in older daily ppt (1985, 2003) |

A single CF `scale_factor` can't reproduce all of these bit for bit. The mirror therefore stores the decimal integer `k` in 1e-4 units, and every reader decodes one consistent float32 per decimal value. `pack()` refuses any value that would move by more than half a quantum (5e-5) plus 1 ulp.

**Measured effect** (`results/prism/rounding_analysis.csv`, all sampled grids):

- **mul-style grids:**
  - 31–58% of values move by exactly 1 ulp (≤1.19e-7 relative); max |Δ| is 3.8e-6 °C for temperature and 6.1e-5 mm for monthly ppt.
  - **The shift is systematic.** The source is +4.7e-8 relative too high for mul-3 (float32(0.001) is too large) and −2.6e-8 for mul-4, so harmonizing *removes* a source bias.
  - Worst case, with every value 1 ulp the same way: 1.2e-7 relative. That is ≤0.03 mm over the entire 46-year daily record at the wettest pixel, against a gauge resolution of 0.254 mm.
  - Zero threshold flips (wet day, frost, heat).
- **"other" ppt grids:**
  - 17% of values are quantized to 1e-4 mm, max |Δ| 6.1e-5 mm, mean bias +5e-10 mm (round-to-nearest is unbiased).
  - 1,816 threshold comparisons flipped across 64 grids, about 3e-7 of comparisons; all of those values sit within 5e-5 mm of a threshold.
- **div-3 grids:** unchanged (bit-exact).

## Sanitization

- `-9999` becomes NaN: `_FillValue` sentinel in packed arrays, NaN fill in float arrays. The reader asserts that no other sentinel-like or implausible values remain.
- Pixel-center coordinates are computed exactly from 1/120° steps, rather than from the header's truncated `0.008333333333` pixel size. Over the full 7,025 columns the two differ by 2.3e-9°, which is negligible, but the exact centers are the canonical ones and match other 30″ grids.
- CF-1.10 metadata: `crs` grid mapping (NAD83, EPSG:4269), lat/lon/time bounds, `cell_methods`, units and standard names, and PRISM provenance (dataset version, type, creation date) as per-time auxiliary coordinates.
- `climate_mirror.prism.store.open_prism()` returns lazy float32 variables.

## Reproduce

```bash
uv run python scripts/prism/download_sample.py        # cached under cache/data.prism.oregonstate.edu/; never re-downloads
uv run python scripts/compression_experiments.py --dataset prism --freq monthly --blocks first   # full codec matrix
uv run python scripts/compression_experiments.py --dataset prism --blocks all --codecs <top codecs>
uv run python scripts/compression_experiments.py --dataset prism --layouts --codecs cf-uint+pcodec8
uv run python scripts/prism/build_store.py --overwrite
uv run python scripts/rounding_analysis.py --dataset prism
(cd scripts/prism && uv run python verify_store.py)
uv run python scripts/estimate.py --dataset prism --store <store path>
```
