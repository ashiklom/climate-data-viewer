// Display settings per canonical variable (names/units/notes come from sources.json).
import type { COLORMAP_INDEX } from "@developmentseed/deck.gl-raster/gpu-modules";

type Cmap = keyof typeof COLORMAP_INDEX;
export type Display = { clim: [number, number]; cmap: Cmap; reversed?: boolean; diff: number; diffCmap: Cmap; diffReversed?: boolean };

export const DISPLAY: Record<string, Display> = {
  pr: { clim: [0, 30], cmap: "ylgnbu", diff: 20, diffCmap: "brbg" },
  tas: { clim: [-30, 40], cmap: "thermal", diff: 5, diffCmap: "rdbu", diffReversed: true },
  tasmax: { clim: [-30, 45], cmap: "thermal", diff: 5, diffCmap: "rdbu", diffReversed: true },
  tasmin: { clim: [-40, 30], cmap: "thermal", diff: 5, diffCmap: "rdbu", diffReversed: true },
  tdps: { clim: [-30, 30], cmap: "haline", diff: 5, diffCmap: "rdbu", diffReversed: true },
  ps: { clim: [500, 1050], cmap: "dense", diff: 10, diffCmap: "rdbu", diffReversed: true },
  rsds: { clim: [0, 35], cmap: "solar", diff: 10, diffCmap: "rdbu", diffReversed: true },
  sfcWind: { clim: [0, 12], cmap: "speed", diff: 4, diffCmap: "rdbu", diffReversed: true },
  sm1: { clim: [0, 0.5], cmap: "rain", diff: 0.2, diffCmap: "brbg" },
  sm2: { clim: [0, 0.5], cmap: "rain", diff: 0.2, diffCmap: "brbg" },
};

/** Ratio maps show log2(A/B): symmetric, 0 = agreement, +-1 = a factor of 2. */
export const RATIO_RANGE: [number, number] = [-2, 2];
