#!/usr/bin/env bash
# Build the website prototype's data products for a date range (default: 2021), in dependency order.
# Every step is idempotent: downloads skip cached files and derived groups are overwritten in place.
#   scripts/web/build_prototype_data.sh [START] [END]
set -euo pipefail
START=${1:-2021-01-01}
END=${2:-2021-12-31}
PY="uv run python"
cd "$(dirname "$0")/../.."

# PRISM: raw grids for the site's variables, written into the full-record mirror, then the common grid.
VARS="ppt tmean tmax tmin tdmean soltotal"
for v in $VARS; do $PY scripts/prism/download.py --freq daily --start "$START" --end "$END" --vars "$v"; done
$PY scripts/prism/build_store.py --freq daily --start "$START" --end "$END" --vars $VARS

# CHIRPS: map-optimized copy of dynamical.org's daily data.
$PY scripts/chirps/rechunk_dynamical.py --start "$START" --end "$END"

# ERA5: daily canonical variables from Earthmover's hourly ERA5.
$PY scripts/era5/derive_daily.py --start "$START" --end "$END"

# ERA5-Land: CDS daily statistics + 00 UTC accumulations, then daily canonical variables.
$PY scripts/era5land/fetch_cds.py --start "${START:0:7}" --end "${END:0:7}"
$PY scripts/era5land/derive_daily.py --start "${START:0:7}" --end "${END:0:7}"

# Common 0.25 degree grid for every dataset (MERRA-2 and IMERG are read from NASA POWER).
for ds in prism chirps era5 era5land merra2 imerg; do
  $PY scripts/web/regrid_common.py --dataset "$ds" --start "$START" --end "$END"
done

$PY scripts/web/write_sources.py
