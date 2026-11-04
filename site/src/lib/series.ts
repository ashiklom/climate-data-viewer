// Daily point time series per dataset, read from the most time-friendly copy of each dataset:
//   PRISM: our mirror (32-day chunks); CHIRPS: dynamical.org (365-day chunks); ERA5: Earthmover single/temporal
//   (hourly, one ~year per chunk; aggregated to UTC days here with the same rules as climate_mirror.era5);
//   MERRA-2 / IMERG: NASA POWER temporal stores; ERA5-Land: ECMWF ARCO geo-chunked stores (hourly, CDS key).
import * as zarr from "zarrita";

import { cfDecode, indexOf, openIcechunkGroup, openZarr2Group, sources, timeAxis, type DatasetName } from "./data";

type Grp = zarr.Group<zarr.Readable>;
export type Series = { dataset: DatasetName; dates: string[]; values: number[]; source: string };

const coordCache = new Map<string, Promise<Float64Array>>();
function coord(group: Grp, name: string, key: string): Promise<Float64Array> {
  const k = `${key}|${name}`;
  if (!coordCache.has(k)) {
    coordCache.set(k, (async () => {
      const a = await zarr.open(group.resolve(name), { kind: "array" });
      return Float64Array.from((await zarr.get(a)).data as ArrayLike<number>);
    })());
  }
  return coordCache.get(k)!;
}

function nearest(values: Float64Array, x: number): number {
  let best = 0;
  for (let i = 1; i < values.length; i++) if (Math.abs(values[i]! - x) < Math.abs(values[best]! - x)) best = i;
  return best;
}

function days(start: string, end: string): string[] {
  const out: string[] = [];
  for (let t = Date.parse(`${start}T00:00Z`); t <= Date.parse(`${end}T00:00Z`); t += 86400000) out.push(new Date(t).toISOString().slice(0, 10));
  return out;
}

/** Point series from a daily (time, lat, lon) array with 1-D lat/lon coordinates. */
async function dailyPoint(group: Grp, key: string, varName: string, lon: number, lat: number, start: string, end: string,
  opts: { time?: string; latName?: string; lonName?: string; scale?: number } = {}): Promise<number[]> {
  const [lats, lons] = await Promise.all([coord(group, opts.latName ?? "lat", key), coord(group, opts.lonName ?? "lon", key)]);
  const ax = await timeAxis(group, opts.time ?? "time");
  const i0 = indexOf(ax, start), i1 = indexOf(ax, end) + 1;
  const arr = await zarr.open(group.resolve(varName), { kind: "array" });
  const chunk = await zarr.get(arr, [zarr.slice(i0, i1), nearest(lats, lat), nearest(lons, lon)]);
  const vals = cfDecode(chunk.data as ArrayLike<number>, arr.attrs as Record<string, unknown>);
  return Array.from(vals, (v) => v * (opts.scale ?? 1));
}

// Hourly -> UTC-day aggregation, matching climate_mirror.era5.daily (and the ERA5-Land checks against CDS):
// accumulations (tp, ssrd; hourly increments labelled at the end of each hour) sum hours ending (D 00, D+1 00];
// instantaneous fields aggregate hours 00..23. ERA5 (Earthmover) and ERA5-Land (ARCO) share variable names.
const HOURLY_RULES: Record<string, { vars: string[]; agg: "sum_acc" | "mean" | "max" | "min"; f: (...x: number[]) => number }> = {
  pr: { vars: ["tp"], agg: "sum_acc", f: (x) => x * 1000 },
  rsds: { vars: ["ssrd"], agg: "sum_acc", f: (x) => x / 1e6 },
  tas: { vars: ["t2m"], agg: "mean", f: (x) => x - 273.15 },
  tasmax: { vars: ["t2m"], agg: "max", f: (x) => x - 273.15 },
  tasmin: { vars: ["t2m"], agg: "min", f: (x) => x - 273.15 },
  tdps: { vars: ["d2m"], agg: "mean", f: (x) => x - 273.15 },
  ps: { vars: ["sp"], agg: "mean", f: (x) => x / 100 },
  sfcWind: { vars: ["u10", "v10"], agg: "mean", f: (u, v) => Math.hypot(u, v) },
  sm1: { vars: ["swvl1"], agg: "mean", f: (x) => x },
  sm2: { vars: ["swvl2"], agg: "mean", f: (x) => x },
};

/** Where an hourly source variable lives: its group, coordinate/time names, and longitude convention. */
type HourlyLocator = (v: string) => Promise<{ group: Grp; key: string; time: string; lat: string; lon: string; lon360: boolean }>;

const era5Locator: HourlyLocator = async () => {
  const spec = sources.datasets.era5.hourly_series;
  return { group: await openIcechunkGroup(spec.url, spec.group), key: spec.url, time: "valid_time", lat: "latitude", lon: "longitude", lon360: true };
};

const era5landLocator: HourlyLocator = async (v) => {
  const spec = sources.datasets.era5land.series as { stores: Record<string, string>; time: string; lat: string; lon: string };
  const url = spec.stores[v]!;
  // ARCO requires the CDS key as a Bearer token (dev server only; see vite.config.ts `virtual:cds-key`).
  const { default: key } = await import("virtual:cds-key");
  return { group: await openZarr2Group(url, { Authorization: `Bearer ${key}` }), key: url, time: spec.time, lat: spec.lat, lon: spec.lon, lon360: false };
};

async function hourlyPoint(locate: HourlyLocator, variable: string, lon: number, lat: number, start: string, end: string): Promise<number[]> {
  const rule = HOURLY_RULES[variable];
  if (!rule) throw new Error(`no hourly rule for ${variable}`);
  const hourly = await Promise.all(rule.vars.map(async (v) => {
    const loc = await locate(v);
    const [lats, lons] = await Promise.all([coord(loc.group, loc.lat, loc.key), coord(loc.group, loc.lon, loc.key)]);
    const ax = await timeAxis(loc.group, loc.time);
    const h0 = indexOf(ax, start), h1 = indexOf(ax, end) + 25; // through end+1 00:00 for accumulations
    const yi = nearest(lats, lat), xi = nearest(lons, loc.lon360 ? ((lon % 360) + 360) % 360 : lon);
    const arr = await zarr.open(loc.group.resolve(v), { kind: "array" });
    return (await zarr.get(arr, [zarr.slice(h0, h1), yi, xi])).data as Float32Array;
  }));
  const n = days(start, end).length;
  const out: number[] = [];
  for (let d = 0; d < n; d++) {
    // instantaneous: hours 00..23 of day d; accumulations: hours ending 01..24
    const s = rule.agg === "sum_acc" ? d * 24 + 1 : d * 24;
    const vals: number[] = [];
    for (let h = s; h < s + 24; h++) vals.push(rule.f(...hourly.map((a) => a[h]!)));
    if (rule.agg === "sum_acc") out.push(vals.reduce((a, b) => a + b, 0));
    else if (rule.agg === "max") out.push(Math.max(...vals));
    else if (rule.agg === "min") out.push(Math.min(...vals));
    else out.push(vals.reduce((a, b) => a + b, 0) / vals.length);
  }
  return out;
}

export async function pointSeries(dataset: DatasetName, variable: string, lon: number, lat: number, start: string, end: string): Promise<Series> {
  const ds = sources.datasets[dataset];
  const dates = days(start, end);
  let values: number[];
  let source: string;
  if (dataset === "era5") {
    values = await hourlyPoint(era5Locator, variable, lon, lat, start, end);
    source = "Earthmover ERA5 single/temporal (hourly → UTC days)";
  } else if (dataset === "era5land") {
    values = await hourlyPoint(era5landLocator, variable, lon, lat, start, end);
    source = "ECMWF ARCO ERA5-Land geo-chunked (hourly → UTC days)";
  } else if (dataset === "chirps") {
    const s = ds.series as { url: string; variables: Record<string, { name: string; scale: number }> };
    const g = await openIcechunkGroup(s.url, "");
    values = await dailyPoint(g, s.url, s.variables.pr!.name, lon, lat, start, end,
      { latName: "latitude", lonName: "longitude", scale: s.variables.pr!.scale });
    source = "dynamical.org CHIRPS v3 (time-optimized)";
  } else if (dataset === "merra2" || dataset === "imerg") {
    const s = ds.series as { url: string; variables: Record<string, { name: string }> };
    const g = await openZarr2Group(s.url);
    values = await dailyPoint(g, s.url, s.variables[variable]!.name, lon, lat, start, end);
    source = "NASA POWER temporal store";
  } else {
    const m = ds.maps as { url: string; group: string; variables: Record<string, { name: string }> };
    const g = await openIcechunkGroup(m.url, m.group);
    values = await dailyPoint(g, `${m.url}|${m.group}`, m.variables[variable]!.name, lon, lat, start, end);
    source = "PRISM mirror (32-day chunks)";
  }
  return { dataset, dates, values, source };
}

type Box = [number, number, number, number];

/** One day of a lon/lat box on the common grid, keyed by global common-grid cell (row * nx + col). */
async function boxCells(dataset: DatasetName, variable: string, date: string, box: Box): Promise<Map<number, { v: number; w: number }>> {
  const spec = sources.datasets[dataset].common;
  const grid = sources.common_grid;
  const g = await openIcechunkGroup(spec.url, spec.group);
  const ax = await timeAxis(g);
  const [lats, lons] = await Promise.all([coord(g, "lat", `${spec.url}c`), coord(g, "lon", `${spec.url}c`)]);
  const [w, s, e, n] = box;
  const ys = [...lats.keys()].filter((i) => lats[i]! >= s && lats[i]! <= n);
  const xs = [...lons.keys()].filter((i) => lons[i]! >= w && lons[i]! <= e);
  const cells = new Map<number, { v: number; w: number }>();
  if (!ys.length || !xs.length) return cells;
  const arr = await zarr.open(g.resolve(variable), { kind: "array" });
  const chunk = await zarr.get(arr, [indexOf(ax, date), zarr.slice(ys[0]!, ys.at(-1)! + 1), zarr.slice(xs[0]!, xs.at(-1)! + 1)]);
  const data = chunk.data as Float32Array;
  ys.forEach((yi, r) => {
    const row = Math.round((grid.north - lats[yi]!) / grid.res);
    const wt = Math.cos((lats[yi]! * Math.PI) / 180);
    xs.forEach((xi, c) => {
      const v = data[r * xs.length + c]!;
      if (Number.isFinite(v)) cells.set(row * grid.nx + Math.round((lons[xi]! - grid.west) / grid.res), { v, w: wt });
    });
  });
  return cells;
}

export interface BoxMean {
  dataset: DatasetName;
  shared: number; // mean over the cells every dataset with data in the box covers
  own: number; // mean over all of this dataset's own cells in the box
  ownCells: number;
}

/** cos(lat)-weighted means over a lon/lat box on the common grid for one day. `shared` uses only the cells that
 * every dataset with data in the box covers, so land-only and global datasets are compared like for like. */
export async function boxMeans(datasets: DatasetName[], variable: string, date: string, box: Box):
    Promise<{ means: BoxMean[]; sharedCells: number }> {
  const results = await Promise.allSettled(datasets.map((d) => boxCells(d, variable, date, box)));
  const fields = results.map((r) => (r.status === "fulfilled" ? r.value : new Map<number, { v: number; w: number }>()));
  const present = fields.filter((f) => f.size);
  const shared = present.length ? [...present[0]!.keys()].filter((k) => present.every((f) => f.has(k))) : [];
  const mean = (f: Map<number, { v: number; w: number }>, keys: Iterable<number>) => {
    let sum = 0, wsum = 0;
    for (const k of keys) { const c = f.get(k)!; sum += c.v * c.w; wsum += c.w; }
    return wsum ? sum / wsum : NaN;
  };
  const means = datasets.map((dataset, i) => {
    const f = fields[i]!;
    return { dataset, shared: f.size ? mean(f, shared) : NaN, own: mean(f, f.keys()), ownCells: f.size };
  });
  return { means, sharedCells: shared.length };
}
