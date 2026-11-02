# climate-data-mirror

Cloud-native ([Icechunk](https://icechunk.io)) mirrors of climate datasets, with sizing and compression studies, and a
local comparison website (in progress).

| Dataset | Status | Report |
|---|---|---|
| PRISM 800m (CONUS, daily + monthly, 9 variables) | subset mirror + full-size estimate (~1.96 TB) | [reports/prism.md](reports/prism.md) |
| CHIRPS v3 (global, pentads / dekads / monthly) | planned | |

Layout:

- `src/climate_mirror/` — shared codecs, packing, time axes, paths, and the dataset registry (`datasets.py`);
  one subpackage per dataset (`prism/`, ...).
- `scripts/` — dataset-generic study scripts (`compression_experiments.py`, `rounding_analysis.py`, `estimate.py`,
  all taking `--dataset`); dataset-specific download/build/verify scripts in `scripts/<dataset>/`.
- `cache/<host>/<path>` — permanent cache of raw source files, mirroring source URLs (gitignored).
- `data/` — rebuildable artifacts: local Icechunk stores, logs (gitignored).
- `results/<dataset>/` — experiment outputs (CSV).
