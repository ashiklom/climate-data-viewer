# Common operations. `just` lists them; extra arguments after a recipe name pass through to the script.
# Dates are YYYY-MM-DD; the website prototype covers 2021.

py := "uv run python"
start := "2021-01-01"
end := "2021-12-31"

# List recipes
default:
    @just --list --unsorted

# ---- Setup -----------------------------------------------------------------------------------------------------

# Python env, the pcodec WASM decoder and the site's packages (WASM needs rustup, wasm32 target, wasm-pack)
setup:
    uv sync
    cd packages/pco-wasm && npm install && npm run build
    cd site && npm install
    just sources

# Regenerate site/src/generated/sources.json from stores.toml
sources:
    {{py}} scripts/web/write_sources.py

# ---- Website ---------------------------------------------------------------------------------------------------

# Serve the comparison site locally (stores under data/stores are served at /data)
serve port="5173": sources
    cd site && npm run dev -- --port {{port}}

# Site unit tests and type check
site-test:
    cd site && npm test
    cd site && npm run check

# Site values vs. the stores read in Python (regenerates the fixtures first)
parity:
    {{py}} scripts/web/make_parity_fixtures.py
    cd site && PARITY=1 npx vitest run src/lib/parity.test.ts

# Headless-Chrome end-to-end run against a running `just serve` (screenshots in data/logs/snapshots)
e2e:
    cd site && node scripts/e2e.mjs

# Regenerate the coastline / border overlays in site/public/overlays (Natural Earth 1:10m)
overlays *args:
    {{py}} scripts/web/make_overlays.py {{args}}

# Build every data product the site reads, for a date range
prototype-data start=start end=end:
    scripts/web/build_prototype_data.sh {{start}} {{end}}

# Regrid one dataset's daily data to the common 0.25 degree grid
regrid dataset start=start end=end:
    {{py}} scripts/web/regrid_common.py --dataset {{dataset}} --start {{start}} --end {{end}}

# ---- PRISM -----------------------------------------------------------------------------------------------------

# Download PRISM grids to the cache (default: the representative sample; e.g. --freq daily --start ... --end ...)
prism-download *args:
    {{py}} scripts/prism/download.py {{args}}

# Write PRISM chunks into the mirror (e.g. --sample, or --freq daily --start ... --end ... --vars ppt)
prism-build *args:
    {{py}} scripts/prism/build_store.py {{args}}

# Check the PRISM mirror against the source grids (default: the sample; or --start ... --end ...)
prism-verify *args:
    {{py}} scripts/prism/verify_store.py {{args}}

# ---- CHIRPS ----------------------------------------------------------------------------------------------------

# Download CHIRPS v3 pentads/dekads/monthly to the cache (default: the sample)
chirps-download *args:
    {{py}} scripts/chirps/download.py {{args}}

# Write CHIRPS native chunks into the mirror (e.g. --sample, or --start ... --end ...)
chirps-build *args:
    {{py}} scripts/chirps/build_store.py {{args}}

# Check the CHIRPS native groups against the source GeoTIFFs
chirps-verify *args:
    {{py}} scripts/chirps/verify_store.py {{args}}

# Copy dynamical.org's CHIRPS daily into the map-optimized `daily` group
chirps-daily start=start end=end:
    {{py}} scripts/chirps/rechunk_dynamical.py --start {{start}} --end {{end}}

# ---- ERA5 and ERA5-Land ----------------------------------------------------------------------------------------

# ERA5 daily canonical variables from Earthmover's hourly ERA5
era5-daily start=start end=end:
    {{py}} scripts/era5/derive_daily.py --start {{start}} --end {{end}}

# ERA5-Land daily variables: pr from ARCO, the rest from CDS (slow: CDS queues for hours)
era5land-daily start=start end=end:
    {{py}} scripts/era5land/derive_pr_arco.py --start {{start}} --end {{end}}
    {{py}} scripts/era5land/fetch_cds.py --start {{replace_regex(start, '-[0-9]+$', '')}} --end {{replace_regex(end, '-[0-9]+$', '')}}
    {{py}} scripts/era5land/derive_daily.py --start {{replace_regex(start, '-[0-9]+$', '')}} --end {{replace_regex(end, '-[0-9]+$', '')}}

# ---- Studies ---------------------------------------------------------------------------------------------------

# Codec (or with --layouts, chunk layout) experiments for one dataset
compression dataset *args:
    {{py}} scripts/compression_experiments.py --dataset {{dataset}} {{args}}

# Effect of CF integer rounding for one dataset
rounding dataset *args:
    {{py}} scripts/rounding_analysis.py --dataset {{dataset}} {{args}}

# Full-mirror storage estimate for one dataset
estimate dataset *args:
    {{py}} scripts/estimate.py --dataset {{dataset}} {{args}}

# Cold-read benchmark of every source in Python (e.g. --only PRISM ARCO)
benchmark *args:
    {{py}} scripts/benchmark_reads.py {{args}}

# Map and point-series load times in the site, per dataset (needs a running `just serve`)
benchmark-browser:
    cd site && node scripts/bench.mjs

# ---- Housekeeping ----------------------------------------------------------------------------------------------

# Lint Python
lint:
    uv run ruff check src scripts
