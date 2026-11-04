# gridMET, NLDAS-2 and Daymet: sources and mirrors

*Added 2026-11-04.* All three are CONUS-focused daily (or hourly) gridded products. The goal was to read a
cloud-native copy directly ("live") where one exists, and otherwise to download, clean, compress and convert to
Icechunk as for PRISM and CHIRPS. Sources were tested on 2026-11-04: anonymous HTTPS, HTTP Range, CORS (an
`Origin: http://localhost:5173` request), 2021 coverage, and chunking (bytes per map and per point series).

**Outcome: none of the three can be read live from the browser, so all three are local Icechunk mirrors.**

## Source decisions

### gridMET (4 km, 1979–)

| Candidate | Why not / why |
|---|---|
| Planetary Computer Zarr (`ai4edataeuwest/gridmet`) | Ends 2020-12-31 (no 2021); needs a SAS token |
| USGS GDP Zarr on OSN (`usgs.osn.mghpcc.org/mdmf/gdp/gridMET.zarr`) | No CORS; chunks of 2190 days × 150 × 150 (0.5–2 GB per map); **its 2021 values disagree with NKN** (pr correlation 0.91, mean annual total 1,224 vs 1,369 mm; apparently stale provisional data) |
| NKN THREDDS (OPeNDAP / NCSS) | CORS ok, but not Zarr; NCSS CSV returns unscaled values |
| **NKN NetCDF files** (`northwestknowledge.net/metdata/data/<var>_<year>.nc`, CC0) | **Chosen.** The canonical files; CORS and Range work, but HDF5 chunks of 61 days make a daily map 11–37 MB, so they're downloaded (625 MB for the five 2021 variables used) |

**Mirror (`gridmet.icechunk`, group `daily`).**
- **Values:** the source's uint16 counts are copied unchanged (lossless). Only CF `scale_factor`/`add_offset` change, so that values decode to canonical units (K → °C, daily-mean W m⁻² → MJ m⁻² day⁻¹).
- **tas** = (tmmx + tmmn)/2, stored exactly as the count sum (scale 0.05).
- **Layout:** 32-day shards of one-day 117 × 154 chunks.
- **Size:** 487 MB for 2021.
- **Check:** `scripts/gridmet/verify_store.py` compares every 2021 day and cell with the source: max |diff| 3e-14.
- **Variables:** pr, tas, tasmax, tasmin, rsds, sfcWind.
  - No dew point: gridMET has specific humidity but no pressure, and its elevation file is unreachable.
  - No surface pressure or soil moisture.

### NLDAS-2 (0.125°, hourly, 1979–)

| Candidate | Why not / why |
|---|---|
| GES DISC hydro1 HTTPS / OPeNDAP | Earthdata login, no CORS; on-prem service being retired (notice: by 2026-09-30) |
| Data Rods time-series service | Discontinued (redirects to a notice) |
| Giovanni time-series API | One request per variable-year, but no usable CORS (preflight blocks `Authorization`); used only to **verify** our mirror |
| Planetary Computer, Source Cooperative, Earthmover, dynamical.org | No NLDAS-2 (NLDAS-3 beta exists on AWS, but it is a different product) |
| **Earthdata Cloud** (`data.gesdisc.earthdata.nasa.gov`, Earthdata login) | **Chosen.** Hourly NetCDF FORA files (all 11 forcing variables) plus Cloud OPeNDAP subsets of the Noah soil-moisture layers (0.38 MB/hour instead of 6.9 MB files). There is no daily NLDAS-2 product |

**Mirror (`nldas.icechunk`).**
- **`hourly` group:** the hourly mirror, all FORA variables plus Noah SoilM 0–10 and 10–40 cm.
  - **Values:** decimal int32 counts; Qair stays float32.
  - **Codec:** time-last + pcodec, 2.5–5.7× smaller than float32 pcodec.
  - **Size:** 6.9 GB for 2021, against 14.7 GB of FORA files plus 59 GB of NOAH files.
  - **Rounding:** values sit on the decimal grids of their GRIB-1 encoding, except for binary-scaling noise. Rounding moves at most 0.8% of Tair values and 2.5% of PotEvap values by more than 1 ulp. The largest changes are 6e-5 K and 1.2e-7 mm; the mean change is about 0. See `results/nldas/hourly_packing.csv`.
- **`daily` group:** UTC days, with the same rules as ERA5.
  - Sums (Rainf) add the hours ending 01–24 UTC; instantaneous fields aggregate hours 00–23.
  - **tdps:** hourly dew point from Qair and PSurf (IFS saturation formula), then averaged.
  - **rsds:** mean of hourly SWdown × 0.0864.
  - **sm1/sm2:** Noah total soil water divided by layer depth (0–10 cm and 10–40 cm, against ERA5's 0–7 and 7–28 cm).
  - **Variables:** all ten canonical variables.
- **Download handling:** each day's files are downloaded, written, checked against the files, then deleted.
- **OPeNDAP glitch:** OPeNDAP returned a different hour's granule for the first requests of a new login session. Every granule's `time` is now checked, and the session logs in before parallel requests.
- **Check:** `scripts/nldas/verify.py` matches NASA Giovanni at three points for all of 2021. That covers hourly Tair, Rainf and SoilM, and daily tas/tasmax/tasmin/pr/sm1 recomputed from Giovanni.

### Daymet V4 R1 (1 km, North America, 1980–)

| Candidate | Why not / why |
|---|---|
| Planetary Computer Zarr (`daymeteuwest/daymet-zarr/daily/na.zarr`) | Version 4.0, not R1; ends 2020; 365-day chunks (GBs per map); SAS token |
| Daymet single-pixel API | No CORS; used only to **verify** our mirror |
| ORNL THREDDS | Retired |
| Earthdata Hyrax OPeNDAP (server-side subsets) | No CORS; one request per day; multi-day subsets come back uncompressed |
| NCAR GDEX copy (`data.gdex.ucar.edu/d682806`, anonymous, CORS) | Same files; tested first, but its server resets parallel connections (rate limiting) |
| **ORNL DAAC via Earthdata Cloud** (`data.ornldaac.earthdata.nasa.gov`, Earthdata login) | **Chosen.** Signed CloudFront URLs take parallel Range requests at about 10 MB/s; each file's DMR++ sidecar lists its chunk offsets |

**Mirror (`daymet.icechunk`, group `daily`).**
- **Coverage:** prcp, tmax, tmin, srad, vp, dayl on the **native full North America LCC grid**, with only the CONUS window written: source chunk rows 12–23 and columns 6–26, which cover 24–50°N and 125–66°W.
- **Transfer:** only the (10, 300, 300) HDF5 chunks inside that window are fetched by byte range and decoded in-process (shuffle + deflate). That is about 36 GB instead of the 66 GB of whole North America files. No source file is kept.
- **Values:** int32 counts of 0.01 (the data carry two decimals; `results/daymet/packing.csv`).
- **Layout:** one-day 256 × 256 chunks in 32 × 1024 × 1024 shards.
- **GeoZarr:** the CRS is given as `proj:wkt2`; deck.gl-zarr reprojects the grid on the GPU.
- **Canonical variables:** pr, tasmax and tasmin are native. tas = (tmax + tmin)/2, rsds = srad × dayl / 1e6, and tdps comes from vp (inverting Daymet's Tetens formula). Python (`climate_mirror.daymet.canonical`) and the site (`site/src/lib/derive.ts`) compute these on read, so nothing extra is stored.
- **Common grid:** `regrid_common.py` reprojects with GDAL area-average resampling, and cells less than half covered are missing.
- **Check:** `scripts/daymet/verify_store.py` matches the single-pixel API at six points for all of 2021, for all six variables.
- **Data notes:**
  - Daymet's precipitation occurrence model produces sharp-edged dry patches inside rain areas, and occasional very large daily totals (204 mm in Arkansas on 2021-02-13). Both are in the source; the API returns the same values.
  - In leap years Daymet has no December 31; that day reads as missing.

## Day windows (shown in the site's caveats)
- **gridMET:** calendar day ending at midnight MST (07 UTC the next day).
- **NLDAS-2:** UTC day. Its precipitation is the CPC daily gauge analysis (12–12 UTC), disaggregated to hours.
- **Daymet:** 24-hour day based on local time.

## Reproduce
```bash
just gridmet 2021        # download + build + verify
just nldas 2021-01-01 2021-12-31
just daymet 2021
just regrid gridmet; just regrid nldas; just regrid daymet
```
