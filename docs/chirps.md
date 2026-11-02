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
   and months have to be summed from bit-rounded daily values that ERA5 disaggregated. Totals should be conserved,
   but this is unverified until CHC's server is reachable, and each value carries up to 0.2% error.
2. **Daily statistics inherit ERA5's within-pentad timing.** That covers wet-day frequency, dry-spell length, Rx1day
   and other extremes indices, and onset timing. Daily CHIRPS vs ERA5 or ERA5-Land comparisons are therefore partly
   circular; compare at 5 days or longer. The website shows this caveat.
3. **Threshold-based indices** can flip for values near a threshold because of the bit rounding. That is small next to
   CHIRPS's own uncertainty, but the values are not bit-faithful.
4. **Maps are expensive.** One global daily map touches 4,800 chunks. For this reason the site keeps a map-optimized
   copy (`chirps.icechunk/daily`, 1200 × 1800 tiles per day, built by `scripts/chirps/rechunk_dynamical.py`). It
   is bit-identical to dynamical's values × 86400.

## Our native CHIRPS subset mirror (planned; blocked)

`data.chc.ucsb.edu` has refused connections on ports 80 and 443 since about 14:00 EST on 2026-11-02 (`chc.ucsb.edu`
itself responds). The plan, ready to run once the server is back:

- **Source:** `https://data.chc.ucsb.edu/products/CHIRPS/v3.0/{pentads,dekads,monthly}/global/tifs/`, covering
  3,294 / 1,647 / 549 files from 1981 to 2026-09 at about 18–23 MB each. Raw files go to the permanent cache at
  `cache/data.chc.ucsb.edu/products/CHIRPS/v3.0/...`.
- **Sanitization:**
  - Pixel centers are exact 0.05° values; the GeoTIFF pixel size is the float32-rounded `0.050000000745`.
  - No nodata value is declared, so the ocean fill has to be detected and mapped to missing.
  - CF and GeoZarr metadata, EPSG:4326.
  - Run a decimal-precision and float32-style analysis with `scripts/rounding_analysis.py` to decide on
    CF-integer packing, as for PRISM.
- **Layout:** chunks `(18, 400, 400)` for pentads (a quarter year) and dekads (half a year), `(12, 400, 400)` for
  monthly (one year). The grid divides into 6 × 18 tiles. Use full-record time axes so the repo grows in place.
- **Sample:** 5 whole chunks per product, spread across eras and seasons, plus 2021 for the website.
- **Steps:**
  - Add a `climate_mirror/chirps` catalog and adapter; the generic scripts take `--dataset chirps`.
  - Download, run `compression_experiments.py`, build, and verify.
  - Run `estimate.py` for the full-volume estimate (pentads + dekads + monthly).
  - Check that the summed CHC daily data reproduces the native pentads.
