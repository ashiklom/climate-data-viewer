// deck.gl-zarr layers: native daily maps and A-B / A/B maps on the common grid.
import type { MinimalTileData, RenderTileResult } from "@developmentseed/deck.gl-raster";
import {
  Colormap,
  COLORMAP_INDEX,
  CreateTexture,
  FilterNoDataVal,
  LinearRescale,
} from "@developmentseed/deck.gl-raster/gpu-modules";
import { ZarrLayer, type GetTileDataOptions } from "@developmentseed/deck.gl-zarr";
import type { Texture } from "@luma.gl/core";
import * as zarr from "zarrita";

import { cfDecode, indexOf, openIcechunkGroup, openZarr2Group, sources, timeAxis, type DatasetName } from "./data";

type Arr = zarr.Array<zarr.DataType, zarr.Readable>;
type TileData = MinimalTileData & { texture: Texture };
type Grp = zarr.Group<zarr.Readable>;

export type Style = { clim: [number, number]; cmap: keyof typeof COLORMAP_INDEX; reversed?: boolean };
export type MapSource = { group: Grp; arr: Arr; metadata: Record<string, unknown>; timeIndex: number };

const groupCache = new Map<string, Promise<Grp>>();
function cachedGroup(key: string, open: () => Promise<Grp>) {
  if (!groupCache.has(key)) groupCache.set(key, open());
  return groupCache.get(key)!;
}

/** GeoZarr attributes for a store without them (NASA POWER), from its 1-D regular lat/lon coordinates. */
async function geozarrFromCoords(group: Grp): Promise<Record<string, unknown>> {
  const lat = (await zarr.get(await zarr.open(group.resolve("lat"), { kind: "array" }))).data as Float64Array;
  const lon = (await zarr.get(await zarr.open(group.resolve("lon"), { kind: "array" }))).data as Float64Array;
  const dy = lat[1]! - lat[0]!; // positive for south-to-north rows
  const dx = lon[1]! - lon[0]!;
  return {
    "spatial:dimensions": ["lat", "lon"],
    "spatial:transform": [dx, 0, lon[0]! - dx / 2, 0, dy, lat[0]! - dy / 2],
    "spatial:shape": [lat.length, lon.length],
    "spatial:registration": "pixel",
    "proj:code": "EPSG:4326",
  };
}

/** The native daily map of `variable` (canonical name) for `dataset` on `date`. */
export async function nativeSource(dataset: DatasetName, variable: string, date: string): Promise<MapSource> {
  const spec = sources.datasets[dataset].maps as {
    kind: string; url: string; group?: string; variables: Record<string, { name: string }>; time?: string;
  };
  const name = spec.variables[variable]?.name;
  if (!name) throw new Error(`${dataset} has no ${variable}`);
  let group: Grp;
  let metadata: Record<string, unknown>;
  if (spec.kind === "icechunk") {
    group = await cachedGroup(`${spec.url}|${spec.group}`, () => openIcechunkGroup(spec.url, spec.group ?? ""));
    metadata = group.attrs as Record<string, unknown>;
  } else {
    group = await cachedGroup(spec.url, () => openZarr2Group(spec.url));
    metadata = await geozarrFromCoords(group);
  }
  const arr = (await zarr.open(group.resolve(name), { kind: "array" })) as Arr;
  const ax = await timeAxis(group, spec.time ?? "time");
  return { group, arr, metadata, timeIndex: indexOf(ax, date) };
}

/** The common-grid (0.25 deg) daily field of `variable` for `dataset`. */
export async function commonSource(dataset: DatasetName, variable: string, date: string): Promise<MapSource> {
  const spec = sources.datasets[dataset].common;
  const group = await cachedGroup(`${spec.url}|${spec.group}`, () => openIcechunkGroup(spec.url, spec.group));
  const arr = (await zarr.open(group.resolve(variable), { kind: "array" })) as Arr;
  const ax = await timeAxis(group);
  return { group, arr, metadata: group.attrs as Record<string, unknown>, timeIndex: indexOf(ax, date) };
}

async function readTile(a: Arr, o: GetTileDataOptions): Promise<{ data: Float32Array; h: number; w: number }> {
  const chunk = await zarr.get(a, o.sliceSpec, { signal: o.signal });
  const [h, w] = chunk.shape.slice(-2) as [number, number];
  return { data: cfDecode(chunk.data as ArrayLike<number>, a.attrs as Record<string, unknown>), h, w };
}

function upload(o: GetTileDataOptions, data: Float32Array, w: number, h: number): TileData {
  const texture = o.device.createTexture({
    format: "r32float", width: w, height: h, data, mipLevels: 1,
    sampler: { minFilter: "nearest", magFilter: "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
  });
  return { texture, width: w, height: h, byteLength: data.byteLength };
}

function renderTile(colormapTexture: Texture, style: Style) {
  return (d: TileData): RenderTileResult => ({
    renderPipeline: [
      { module: CreateTexture, props: { textureName: d.texture } },
      { module: FilterNoDataVal, props: { value: NaN } },
      { module: LinearRescale, props: { rescaleMin: style.clim[0], rescaleMax: style.clim[1] } },
      { module: Colormap, props: { colormapTexture, colormapIndex: COLORMAP_INDEX[style.cmap], reversed: !!style.reversed } },
    ],
  });
}

export function makeLayer(
  id: string, a: MapSource, style: Style, colormapTexture: Texture, opts: { b?: MapSource; op?: "diff" | "ratio"; onLoad?: () => void } = {},
) {
  const { b, op } = opts;
  return new ZarrLayer({
    id,
    node: a.arr,
    metadata: a.metadata,
    selection: { time: a.timeIndex },
    getTileData: async (arr: Arr, o: GetTileDataOptions) => {
      const ta = await readTile(arr, o);
      if (!b) return upload(o, ta.data, ta.w, ta.h);
      // Same grid and chunking (common grid): read the matching tile of B at B's own time index.
      const sliceB = o.sliceSpec.map((s, i) => (i === 0 ? b.timeIndex : s));
      const tb = await readTile(b.arr, { ...o, sliceSpec: sliceB });
      const out = new Float32Array(ta.data.length);
      for (let i = 0; i < out.length; i++) {
        const x = ta.data[i]!, y = tb.data[i]!;
        // ratio: log2(A/B) where both are wet enough (>= 0.1 mm/day) to make a ratio meaningful
        out[i] = op === "ratio" ? (x >= 0.1 && y >= 0.1 ? Math.log2(x / y) : NaN) : x - y;
      }
      return upload(o, out, ta.w, ta.h);
    },
    renderTile: renderTile(colormapTexture, style),
    onViewportLoad: opts.onLoad,
  } as never);
}
