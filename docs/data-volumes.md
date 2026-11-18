# Data volumes

*Compiled 2026-11-17.* For each dataset, three volumes are compared over its full record:

1. **Source, all variables.** The original archive as its provider publishes it.
2. **Source, site variables.** The same archive cut down to the variables the website shows.
3. **Our stores.** What this repo writes: compressed Icechunk mirrors and derived daily groups. Only 2021 (plus the
   PRISM and CHIRPS samples) is written so far, so full-record figures are extrapolated from measured stores.

Units are decimal: 1 TB = 10¹² bytes, 1 GB = 10⁹ bytes. Ranges in parentheses are uncertainties; the
[Methods](#methods-and-uncertainty) section explains where each comes from.

## Summary

| Dataset | Record | Source, all variables | Source, site variables | Our stores, full record | Our stores, 2021 (measured) |
|---|---|---|---|---|---|
| PRISM 800 m | daily 1981–, monthly 1895– | **7.0 TB** (6.9–7.3) | **4.2 TB** daily (4.0–4.4) | **1.0 TB** site daily (0.85–1.3); 1.9 TB full mirror | ~23 GB/yr (est.) |
| CHIRPS v3 0.05° | 1981– | **0.63 TB** (0.55–0.70) | **0.27 TB** (0.25–0.28) | **0.18 TB** (0.16–0.20) | 2.9 GB |
| ERA5 0.25° | 1940– | **720 TB** (NCAR netCDF) | **8.6 TB** (7.3–9.9) | **1.1 TB** (0.95–1.3) | 12.7 GB |
| ERA5-Land 0.1° | 1950– | **~175 TB** (105–245) | **~25 TB** (15–34) | **1.4 TB** (1.2–1.6) | 17.9 GB |
| MERRA-2 0.5° × 0.625° | 1980– | **440 TB** (400–480) | **~1.0 TB** (0.6–1.4) | **0.25 TB** (0.21–0.29) | 5.6 GB |
| IMERG Final 0.1° | 1998– | **3.9 TB** (3.5–4.3) | **~0.09 TB** (0.06–0.14) | **0.02 TB** (0.017–0.023) | 0.75 GB |
| gridMET 4 km | 1979– | **87 GB** (83–92) | **29 GB** (28–30) | **29 GB** (26–33) | 0.62 GB |
| NLDAS-2 0.125° | 1979– | **8.8 TB** (8.4–9.2) | **~0.56 TB** (0.42–0.70) | **0.39 TB** (0.34–0.45) | 8.3 GB |
| Daymet V4R1 1 km | 1980– | **3.4 TB** (3.3–3.6) | **3.1 TB** (3.0–3.2) | **0.87 TB** (0.78–0.96) | 18.8 GB |
| **Total** | | **~1.36 PB** | **~43 TB** (31–54) | **~5.2 TB** (4.5–6.2) | ~91 GB |

- **"Our stores, full record"** counts everything the site reads from our repos: the daily map group (or hourly mirror)
  plus `common_0p25/daily`. For PRISM it counts only the six site variables, and the PRISM total uses that 1.0 TB.
  The PRISM mirror as designed (all 9 variables, daily + monthly) would be 1.9 TB, which makes the total about
  6.1 TB.
- **Totals:** ERA5 and MERRA-2 make up 85% of the source archives, but almost none of it is used. ERA5-Land, ERA5, PRISM and Daymet make up 95% of the
  site-variable sources and over 80% of our stores.
- **Local disk today:** about 117 GB of stores (`data/stores`) and 162 GB of cached source files (`cache/`, mostly the
  PRISM sample zips).

Where the stores are larger than they need to be:
- **ERA5:** `common_0p25/daily` duplicates `daily`. ERA5's grid is the common grid, so the two hold the same values
  (0.55 TB over the full record, a tenth of the total).
- **ERA5, ERA5-Land, MERRA-2, IMERG:** the derived daily and common-grid groups are float32 with lossless pcodec.
  Decimal integer packing, as used for PRISM and NLDAS-2, would likely shrink them by 1.5–2×.

## Per dataset

### PRISM (800 m CONUS)
- **Source:** 9 variables (ppt, tmin, tmax, tmean, tdmean, vpdmin, vpdmax, soltotal, solslope), daily and monthly
  zips of LZW COGs.
  - All variables: 6.67 TB daily + 0.66 TB monthly, about 7.0 TB. ([reports/prism.md](../reports/prism.md) quotes
    6.95 TB; the per-variable sums in `results/prism/storage_estimate.csv` give 7.3 TB.)
  - Site variables: ppt, tmean, tmax, tmin, tdmean and soltotal, daily only: 4.2 TB. As raw float32 that would be
    8.8 TB.
- **Ours:**
  - Six site variables, daily: 1.07 TB (0.92–1.34) with `cf-uint+pcodec8` in the original layout. The map-friendly
    daily layout the site now uses is 2–10% smaller, so about 1.0 TB.
  - Full mirror (all 9 variables, daily and monthly): 1.96 TB (1.72–2.30); a little less in the current layout.
  - `common_0p25/daily`: 0.11 GB/yr, so 5 GB.
- **2021 measured:** the local daily group (36.4 GB) mixes the three sample blocks with 2021, so the per-year figure
  is the estimate, 23 GB/yr for the six site variables.

### CHIRPS v3 (0.05°, land 60°S–60°N)
- **Source (CHC global GeoTIFFs):**

  | Product | Size |
  |---|---|
  | Daily `rnl` (ERA5-disaggregated) | 5.8 GB/yr; 5.74–5.88 GB for 1985, 2003 and 2021 (CHC directory listings) |
  | Daily `sat` variant | assumed the same size, not measured |
  | Pentads, dekads and monthly | 103 GB |
  | **Total** | **≈0.63 TB** |

  Site variable: daily precipitation (`rnl`), 0.27 TB.
- **Ours:**
  - Map-optimized daily copy of dynamical.org's data: 2.70 GB/yr, so 124 GB.
  - Native pentad, dekad and monthly mirror: 45 GB (41.7–50.0; see [docs/chirps.md](chirps.md)).
  - `common_0p25/daily`: 0.19 GB/yr, so 9 GB.
- **Point series:** read live from dynamical.org's store, which isn't counted here.

### ERA5 (0.25°)
- **Source, all variables:** NCAR's ERA5 0.25° collection (d633000) holds 721 TB of netCDF4. That is 552 TB of
  pressure-level analysis, 53 TB of surface analysis, 70 TB of surface forecasts and 46 TB of vertical integrals,
  plus 189 TB of Zarr copies, which aren't counted.
  - This excludes model levels, the ensemble and ocean waves, so ECMWF's full archive is larger.
  - Earthmover's public store, which we read, holds 39 single-level and 8 pressure-level variables (13 levels)
    hourly, 1940-01 to 2026-06, with pcodec level 8.
  - Sampled chunk sizes put its map layout (`spatial`) at about 161 TB: 38 TB single-level, 123 TB pressure-level.
    The time-series layout (`temporal`) is a second full copy, so the store is roughly 320 TB (±30%).
- **Source, site variables:** tp, t2m, d2m, sp, ssrd, u10, v10, swvl1 and swvl2.
  - 8.6 TB (±15%) in Earthmover's map layout, about 100 GB/yr.
  - 28 TB as raw float32.
  - Compression ratios range from 2.0× (u10, v10) to 5.8× (ssrd).
- **Ours:**
  - `daily` (10 canonical variables): 6.37 GB/yr × 86.5 yr, so 0.55 TB.
  - `common_0p25/daily`: the same again, 0.55 TB (a duplicate; see above).

### ERA5-Land (0.1°)
- **Source, all variables:** about 50 hourly variables, 1950–. Neither CDS nor ECMWF publishes a total, so this is
  estimated from the GRIB encoding.
  - Each field is 2.21 million land points × 16 bits, plus a 0.8 MB land/sea bitmap: about 5.2 MB.
  - That gives 46 GB per variable-year and about 2.3 TB/yr in all, so **≈175 TB (±40%)**.
- **Source, site variables:**
  - Seven hourly variables are needed for the daily maps: tp, t2m, d2m, sp, ssrd, swvl1 and swvl2. That is about
    320 GB/yr, **≈25 TB (±40%)**.
  - The point series also use u10 and v10, read live from ECMWF's ARCO Zarr stores.
- **What we actually transferred:** CDS daily statistics, 12 GB for 7 variables in 2021, plus 3.2 GB of 00 UTC slices
  for tp and ssrd. That is far less than the hourly source.
- **Ours:**
  - `daily` (9 variables, full 0.1° grid): 14.6 GB/yr × 76.8 yr, so 1.12 TB.
  - `common_0p25/daily`: 3.3 GB/yr, so 0.25 TB.

### MERRA-2 (0.5° × 0.625°)
- **Source, all variables:** NASA CMR lists 95 MERRA-2 V5.12.4 collections. Their 2021 granules sum to 9.63 TB; the
  biggest is 3-hourly model-level aerosols at 1.4 TB/yr. Over 46 years that is **≈440 TB**.
- **Source, site variables:** the nine variables come from four collections. Each collection's share is its yearly
  size × (variables used / variables in the file), about 21 GB/yr in all, so **≈1.0 TB** over the record (±40%,
  because variables differ in size):

  | Collection | Variables used | Collection size |
  |---|---|---|
  | `M2T1NXSLV` | T2M, T2MDEW, PS, U10M, V10M (5 of ~47) | 144 GB/yr |
  | `M2T1NXFLX` | PRECTOTCORR | 139 GB/yr |
  | `M2T1NXLND` | GWETTOP, GWETROOT | 73 GB/yr |
  | `M2SDNXSLV` | T2MMAX, T2MMIN | 0.6 GB/yr |
- **Our source in practice:** the site reads NASA POWER's daily Zarr stores, which are derived from these
  collections; their size wasn't measured.
- **Ours:** `common_0p25/daily` only: 5.6 GB/yr × 45 yr (POWER starts in 1981), so 0.25 TB.

### IMERG Final (0.1°)
- **Source, all variables (Final run):** half-hourly 130 GB/yr, daily 10.8 GB/yr and monthly 0.2 GB/yr (CMR, 2021).
  Over 1998-01 to 2025-09 that is **3.9 TB**. The Early and Late runs, about 2× more, are excluded.
- **Source, site variables:** daily precipitation is one of about 9 fields in the daily files (with counts, errors and
  liquid fraction). Taking 20–45% of the daily file gives 2–5 GB/yr, **≈0.09 TB**.
- **Ours:** `common_0p25/daily` only, 0.75 GB/yr, about 20 GB from POWER's record. The site reads native maps
  live from NASA POWER.

### gridMET (4 km CONUS)
- **Source, all variables:** 16 variables (pr, rmax, rmin, sph, srad, th, tmmn, tmmx, vs, erc, etr, pet, vpd, bi,
  fm100, fm1000).
  - NKN files are 1.76, 1.77, 1.93 and 1.95 GB/yr for 1979, 2000, 2021 and 2024 (HTTP `Content-Length`).
  - Over 47 years that is **87 GB**.
- **Source, site variables:** pr, tmmx, tmmn, srad and vs: 0.60–0.63 GB/yr, so 29 GB.
- **Ours:**
  - `daily` (6 variables, the source counts copied losslessly): 0.51 GB/yr, so 24 GB.
  - `common_0p25/daily`: 0.11 GB/yr, so 5 GB.
- **Why no smaller than the source:** for gridMET our store is the same size as the source subset. The source's
  uint16 counts are already compact, and `tas` is stored as an extra array rather than computed on read.

### NLDAS-2 (0.125° CONUS)
- **Source, all variables:** hourly V2.0 FORA, FORB, Noah, VIC and Mosaic files are 15.0 + 13.7 + 60.2 + 49.8 + 47.7
  = 186 GB/yr (CMR, 2021). Over 47 years that is **8.8 TB**; the monthly products are negligible.
- **Source, site variables:** 7 of the 11 FORA variables (about 9.6 GB/yr) plus 2 of the ~52 Noah variables (about
  2.3 GB/yr). That is about 12 GB/yr, **≈0.56 TB (±25%)**.
- **What we transfer:** whole FORA files (15 GB/yr) and OPeNDAP soil-moisture subsets (3.3 GB/yr).
- **Ours:**
  - `hourly`: all 11 forcing variables plus 2 soil layers, 7.35 GB/yr, so 0.35 TB. This is a full hourly mirror and
    is more than the site needs.
  - `daily`: 0.68 GB/yr, so 32 GB.
  - `common_0p25/daily`: 0.26 GB/yr, so 12 GB.

### Daymet V4R1 (1 km)
- **Source, all variables:** 7 variables (dayl, prcp, srad, swe, tmax, tmin, vp) for North America, Hawaii and
  Puerto Rico.
  - 74.4 GB/yr (CMR, 2021; 76.9 GB for 1980 and 2000).
  - Over 46 years that is **3.4 TB**. CMR also lists a few small 1950 granules, but the North America files start in
    1980.
- **Source, site variables:** all variables except swe, North America only: 66.4 GB/yr, so 3.1 TB.
- **What we transfer:** only the HDF5 chunks inside the CONUS window, about 36 GB/yr (1.65 TB over the record).
- **Ours:**
  - `daily` (6 native variables, CONUS window, int32 0.01 counts, bit-exact): 18.6 GB/yr, so 0.86 TB.
  - `common_0p25/daily`: 0.17 GB/yr, so 8 GB.

## Methods and uncertainty

How each figure was obtained, from most to least certain:

| Basis | Used for | Uncertainty |
|---|---|---|
| Measured file sizes for whole years | NASA CMR granule sizes (NLDAS-2, Daymet, MERRA-2, IMERG), CHC directory listings (CHIRPS daily), NKN `Content-Length` (gridMET), NCAR GDEX totals (ERA5) | Within ±2% for the year measured |
| Extrapolation from one year to the full record (record years × 2021 size) | Most source and store figures | ±5–10% |
| Sample-based estimate | PRISM and CHIRPS native, using the compression study's sample blocks | Min–max over sample blocks, about ±15% |
| Chunk sampling | ERA5 from Earthmover's store, 4–6 random hourly chunks per variable | Spread within ±10% per variable; ±15% overall |
| Our stores | Measured 2021 sizes (`nbytes_stored` per array) × record years | ±10–15% for differences in compressibility between years (PRISM blocks ranged about ±15%) |
| Variable-share estimate | MERRA-2, NLDAS-2 and IMERG site subsets: a file's size split by its variable count | ±25–50%, because variables differ in size |
| Encoding-based estimate | ERA5-Land, from land points × 16-bit GRIB packing | ±40%. ECMWF uses more bits for some variables, and CDS netCDF output is a different size |

Record lengths assume the archives continue through 2025 or their latest release: PRISM daily 45.8 yr, CHIRPS
45.7, ERA5 86.5, ERA5-Land 76.8, MERRA-2 46 (POWER 45), IMERG 27.75, gridMET 47, NLDAS-2 47, Daymet 46. These are
deliberately rounded.

**Reproduce the 2021 store sizes:** run `zarr.Array.nbytes_stored()` over every array in each repo's `main` tip
(read through `climate_mirror.storage.open_mirror`).
