# CHIRPS v3: what's on Earthmover, what's missing, and our mirror

## The Earthmover / dynamical.org collection

Earthmover exchange listing `6ad111f3549593cb0581ec6f` is **dynamical.org's "UCSB CHC CHIRPS analysis, final"**:
- a public Icechunk v2 repo at `https://dynamical-ucsb-chc-chirps.s3.us-west-2.amazonaws.com/ucsb-chc-chirps-analysis-final/v0.1.0.icechunk`
  (anonymous access, CORS enabled, CC-BY-4.0);
- one variable, `precipitation_surface`: the **daily** mean rate in kg m⁻² s⁻¹ (× 86400 gives mm/day);
- 0.05°, 60°N–60°S, 1981-01-01 to the latest final month, updated monthly. dynamical also publishes a "preliminary"
  daily product.
- **Source:** CHC `daily/final/rnl`, in which ERA5 rainfall splits the native 5-day CHIRPS totals into days.
- **Encoding:** float32 **bit-rounded to 8 mantissa bits**, so up to about 0.2% relative error per value (verified),
  then blosc-zstd.
- **Layout:** time-optimized. Chunks are 365 × 60 × 60 inside 365 × 1200 × 1800 shards, about 1.15 TB raw.

### Missing compared with CHC's archive

- The native **pentad**, **dekad** and **monthly** products, and CHC's 2–6-month and annual aggregates.
  The Africa and LatAm subsets are also absent, though they are derivable from the global grids.
- Lossless values.
- A map-optimized layout.

### Scientific implications

1. **Native CHIRPS is not exactly reproducible.** The blended product's native step is the pentad. Pentads, dekads
   and months have to be summed from bit-rounded daily values that ERA5 disaggregated. Totals are conserved:
   for all 73 pentads of 2021, the summed daily values match CHC's native pentads with identical land masks.
   Global totals agree within 2e-6, but each cell can differ by up to 0.2% (8-bit rounding; up to 1.5 mm in
   very wet cells). See `results/chirps/daily_vs_pentads.csv`.
2. **Daily statistics inherit ERA5's within-pentad timing.** That covers wet-day frequency, dry-spell length, Rx1day
   and other extremes indices, and onset timing. Daily CHIRPS vs ERA5 or ERA5-Land comparisons are therefore partly
   circular; compare at 5 days or longer. The website shows this caveat.
3. **Threshold-based indices** can flip for values near a threshold because of the bit rounding. That is small next to
   CHIRPS's own uncertainty, but the values are not bit-faithful.
4. **Maps are expensive.** One global daily map touches 4,800 chunks. For this reason the site keeps a map-optimized
   copy (`chirps.icechunk/daily`, 1200 × 1800 tiles per day, built by `scripts/chirps/rechunk_dynamical.py`). It
   is bit-identical to dynamical's values × 86400.

## Our native CHIRPS subset mirror

Groups `pentads`, `dekads` and `monthly` sit in the same `chirps` repo as `daily` and `common_0p25/daily`. Each
holds `precip` (mm per period) on full-record time axes (1981 to 2026-09). Written so far are five whole chunks per
product, spread across eras and seasons (1983, 1993, 2003, 2013, 2025), plus all of 2021: about 5.6 GB.

- **Source:** `https://data.chc.ucsb.edu/products/CHIRPS/v3.0/{pentads,dekads,monthly}/global/tifs/`.
  - Files: 3,294 / 1,647 / 549 LZW GeoTIFFs, about 103 GB in total. Cached under `cache/data.chc.ucsb.edu/...`.
  - The server returns HTTP 429 at four parallel requests now and then; reruns fetch only missing files.
- **Sanitization:**
  - The undeclared −9999 ocean fill becomes missing. Any other negative or non-finite value is an error; none
    occurred.
  - Pixel centers are exact 0.05° values. The header's pixel size, `0.050000000745`, is float32-rounded, which
    shifts the eastern and southern edges by 5e-6°.
  - CF-1.10 and GeoZarr metadata, EPSG:4326.
- **Values:** unlike PRISM, CHIRPS values are full-precision floats, not decimals.
  - The mirror rounds them to the nearest 1e-4 mm and stores `uint32` integers (CF `scale_factor`).
  - Across all 240 sampled grids (`results/chirps/rounding_analysis.csv`):
    - per-value change at most 6.1e-5 mm;
    - no systematic direction (mean signed change about 1e-9 mm; grid totals change by at most 1.5e-10 relative);
    - about 2 in a million comparisons at 0.1–100 mm thresholds flip;
    - about 20 cells per grid below 5e-5 mm become exactly 0.
  - Worst case if every cell rounded the same way: 5e-5 mm per period, or 0.004 mm per year of pentads.
- **Codec:** `cf-uint+pcodec8`, as for PRISM; the site already has a WASM pcodec decoder. Compared with CHC's
  GeoTIFFs:

  | Codec | Size vs CHC's GeoTIFFs | Decode speed |
  |---|---|---|
  | `cf-uint+pcodec8` | 2.1–2.3× smaller | ~8.5 GB/s |
  | Lossless float32 `pcodec8` | 1.6× smaller | — |
  | Lossless float32 zstd | ~1.45× smaller | — |
  | `cf-uint+shuffle-zstd9` | 0.7 GB smaller over the full record than `cf-uint+pcodec8` | ~2.5 GB/s |

  See `results/chirps/compression.csv`.
- **Layout:** chunks `(18, 400, 400)` for pentads (a quarter year) and dekads (half a year), and `(12, 400, 400)` for
  monthly (a year): 6 × 18 tiles.
  - Alternatives (240² to 800 × 900 tiles, half-length chunks, sharding) change the size by at most about 3%.
  - A full map reads 108 objects. On the local store a map takes about 0.2–0.3 s and a full-record pixel series
    0.05–0.26 s.
- **Verified** (`scripts/chirps/verify_store.py`): every checked sample and 2021 period equals the packed source
  exactly, and unwritten periods read as missing.

### Full-mirror estimate (`results/chirps/storage_summary.csv`)

| Product | `cf-uint+pcodec8` | Range over samples | CHC GeoTIFFs | Raw float32 |
|---|---|---|---|---|
| pentads (3,294) | 24.9 GB | 22.0–28.8 | 58.0 GB | 227.7 GB |
| dekads (1,647) | 14.5 GB | 13.9–15.2 | 32.4 GB | 113.8 GB |
| monthly (549) | 5.9 GB | 5.8–5.9 | 12.6 GB | 37.9 GB |
| **total** | **45.3 GB** | 41.7–50.0 | 103 GB | 379 GB |

Icechunk metadata adds about 4 MB. Lossless float32 `pcodec8` would be about 64 GB.

**The pentads alone determine the rest.** In 2021:
- each dekad is bit-for-bit the float32 sum of its two pentads (all 9 checked);
- each month is the sum of its six pentads to float32 rounding (at most 5e-4 mm, 1e-7 relative).

So a pentads-only mirror (about 25 GB) could derive dekads exactly and months to float32 precision. We store all
three because CHC publishes them and they cost only 20 GB more.

### Commands

```bash
uv run python scripts/chirps/download.py                                      # sample chunks
uv run python scripts/chirps/download.py --start 2021-01-01 --end 2021-12-31  # whole chunks over a range
uv run python scripts/rounding_analysis.py --dataset chirps
uv run python scripts/compression_experiments.py --dataset chirps --blocks middle   # [--layouts]
uv run python scripts/chirps/build_store.py --sample --start 2021-01-01 --end 2021-12-31
uv run python scripts/chirps/verify_store.py [--start ... --end ...]
uv run python scripts/estimate.py --dataset chirps --store data/stores/chirps.icechunk
uv run python scripts/chirps/compare_daily_pentads.py                         # dynamical daily vs CHC pentads (2021)
```

A full mirror is `download.py` and `build_store.py` with `--start 1981-01-01 --end 2026-09-30`: about 103 GB to
download, about 45 GB stored.
