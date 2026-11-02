// Daily point time series per dataset, read from the most time-friendly copy of each dataset:
//   PRISM: our mirror (32-day chunks); CHIRPS: dynamical.org (365-day chunks); ERA5: Earthmover single/temporal
//   (hourly, one ~year per chunk; aggregated to UTC days here with the same rules as climate_mirror.era5);
//   MERRA-2 / IMERG: NASA POWER temporal stores; ERA5-Land: our daily mirror (map chunks; slower).
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

// ERA5 hourly -> daily, matching climate_mirror.era5.daily.
const ERA5_RULES: Record<string, { vars: string[]; agg: "sum_acc" | "mean" | "max" | "min"; f: (...x: number[]) => number }> = {
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

async function era5Point(variable: string, lon: number, lat: number, start: string, end: string): Promise<number[]> {
  const spec = sources.datasets.era5.hourly_series;
  const group = await openIcechunkGroup(spec.url, spec.group);
  const [lats, lons] = await Promise.all([coord(group, "latitude", spec.url), coord(group, "longitude", spec.url)]);
  const ax = await timeAxis(group, "valid_time");
  const rule = ERA5_RULES[variable]!;
  const h0 = indexOf(ax, start), h1 = indexOf(ax, end) + 25; // through end+1 00:00 for accumulations
  const yi = nearest(lats, lat), xi = nearest(lons, ((lon % 360) + 360) % 360);
  const hourly = await Promise.all(rule.vars.map(async (v) => {
    const arr = await zarr.open(group.resolve(v), { kind: "array" });
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
    values = await era5Point(variable, lon, lat, start, end);
    source = "Earthmover ERA5 single/temporal (hourly → UTC days)";
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
    source = dataset === "prism" ? "PRISM mirror (32-day chunks)" : "local daily mirror (map chunks)";
  }
  return { dataset, dates, values, source };
}

/** Area-weighted mean over a lon/lat box on the common grid for one day. */
export async function boxMean(dataset: DatasetName, variable: string, date: string, box: [number, number, number, number]): Promise<number> {
  const spec = sources.datasets[dataset].common;
  const g = await openIcechunkGroup(spec.url, spec.group);
  const ax = await timeAxis(g);
  const [lats, lons] = await Promise.all([coord(g, "lat", `${spec.url}c`), coord(g, "lon", `${spec.url}c`)]);
  const [w, s, e, n] = box;
  const ys = [...lats.keys()].filter((i) => lats[i]! >= s && lats[i]! <= n);
  const xs = [...lons.keys()].filter((i) => lons[i]! >= w && lons[i]! <= e);
  if (!ys.length || !xs.length) return NaN;
  const arr = await zarr.open(g.resolve(variable), { kind: "array" });
  const chunk = await zarr.get(arr, [indexOf(ax, date), zarr.slice(ys[0]!, ys.at(-1)! + 1), zarr.slice(xs[0]!, xs.at(-1)! + 1)]);
  const data = chunk.data as Float32Array;
  let sum = 0, wsum = 0;
  ys.forEach((yi, r) => {
    const wt = Math.cos((lats[yi]! * Math.PI) / 180);
    for (let c = 0; c < xs.length; c++) {
      const v = data[r * xs.length + c]!;
      if (Number.isFinite(v)) { sum += v * wt; wsum += wt; }
    }
  });
  return wsum ? sum / wsum : NaN;
}
