# climate-data-mirror

Cloud-native ([Icechunk](https://icechunk.io)) mirrors of climate datasets, with sizing and compression studies, and a
local website comparing daily PRISM, CHIRPS, ERA5, ERA5-Land, MERRA-2 and IMERG data.

| Dataset | What we hold | Docs |
|---|---|---|
| PRISM 800m (CONUS, daily + monthly, 9 variables) | Full-record mirror with the representative sample and 2021 written; full size estimated at about 1.96 TB | [reports/prism.md](reports/prism.md) |
| CHIRPS v3 (global 0.05°) | Map-optimized copy of dynamical.org's daily data (2021); native pentad/dekad/monthly subset mirror planned (CHC server down) | [docs/chirps.md](docs/chirps.md) |
| ERA5 (0.25°) | Daily canonical variables derived from Earthmover's public hourly ERA5 | `climate_mirror/era5` |
| ERA5-Land (0.1°) | Daily maps: precipitation from the ECMWF ARCO Zarr stores (hourly sums); other variables from CDS daily statistics (24× less transfer than hourly ARCO tiles). Point series read ARCO geo-chunked stores directly | `climate_mirror/era5land` |
| MERRA-2, IMERG | Read directly from NASA POWER; we keep only common-grid copies | `climate_mirror/web` |

All datasets also have `common_0p25/daily`: a conservative regrid onto the ERA5 0.25° grid, used for A − B maps and
area means.

## Layout

- **`src/climate_mirror/`:**
  - shared code: codecs, CF integer packing, time axes, paths, `storage.py`, canonical `variables.py`, `derived.py`
    (derived daily map groups), and the dataset registry (`datasets.py`);
  - one subpackage per dataset;
  - `web/` for website products.
- **`stores.toml`:** where every repo lives. Mirrors are local now (`data/stores/<name>.icechunk`), and any
  S3-compatible target (AWS, Wasabi, OSN, Source Cooperative) needs only a config change. External stores we read
  are listed alongside.
- **`scripts/`:**
  - generic study scripts that take `--dataset`: `compression_experiments.py`, `rounding_analysis.py`, `estimate.py`;
  - per-dataset download, build and derivation scripts;
  - `web/` for the common-grid regrid, `sources.json` generation and parity fixtures.
- **`packages/pco-wasm/`:** a decode-only pcodec build for zarrita in the browser, compiled from the `pco` crate.
- **`site/`:** the comparison website (Vite + Svelte + deck.gl-zarr). See [docs/website-stack.md](docs/website-stack.md).
- **`cache/<host>/<path>`:** the permanent cache of raw source files (gitignored).
- **`data/`:** rebuildable stores and logs (gitignored).
- **`_credentials.toml`:** local keys (CDS API key, NASA Earthdata), gitignored and never logged.

## Website (local prototype)

```bash
uv sync
(cd packages/pco-wasm && npm install && npm run build)   # needs rustup, the wasm32 target, and wasm-pack
uv run python scripts/web/write_sources.py                # site/src/generated/sources.json from stores.toml
cd site && npm install && npm run dev                     # http://localhost:5173
```

The dev server serves `data/stores/` at `/data/` with HTTP Range support. The CDS key is available only to the dev
server, so production builds fail by design.

Checks:
- `npm test`: unit tests.
- `PARITY=1 npx vitest run src/lib/parity.test.ts`: after `uv run python scripts/web/make_parity_fixtures.py`.
- `node scripts/e2e.mjs`: headless Chrome, with screenshots in `data/logs/snapshots/`.
