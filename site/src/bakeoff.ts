// Rendering bake-off: the same local Icechunk data drawn with deck.gl-zarr (left) and @carbonplan/zarr-layer (right).
// Cases: PRISM pr (CF-packed uint32, pcodec, NAD83, 256x256 tiles), ERA5 tas (float32, pcodec, 0.25 deg), and
// ERA5 - MERRA-2 pr on the common grid (two stores; deck.gl only).
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { MinimalTileData, RenderTileResult } from "@developmentseed/deck.gl-raster";
import {
  Colormap,
  COLORMAP_INDEX,
  CreateTexture,
  FilterNoDataVal,
  LinearRescale,
  createColormapTexture,
  decodeColormapSprite,
} from "@developmentseed/deck.gl-raster/gpu-modules";
import colormapsPng from "@developmentseed/deck.gl-raster/gpu-modules/colormaps.png";
import { ZarrLayer as DeckZarrLayer, type GetTileDataOptions } from "@developmentseed/deck.gl-zarr";
import { ZarrLayer as CarbonZarrLayer } from "@carbonplan/zarr-layer";
import type { Device, Texture } from "@luma.gl/core";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as zarr from "zarrita";

import { cfDecode, dayIndex, openIcechunk, openIcechunkGroup, registerCodecs, sources } from "./lib/data";

registerCodecs();

type Case = { id: string; label: string; dataset: "prism" | "era5"; group: string; variable: string; date: string;
  clim: [number, number]; colormap: keyof typeof COLORMAP_INDEX; center: [number, number]; zoom: number };

const CASES: Case[] = [
  { id: "prism", label: "PRISM pr 2021-10-10 (mm/day)", dataset: "prism", group: "daily", variable: "ppt", date: "2021-10-10",
    clim: [0, 40], colormap: "ylgnbu", center: [-98, 39], zoom: 3.4 },
  { id: "era5", label: "ERA5 tas 2021-07-01 (°C)", dataset: "era5", group: "daily", variable: "tas", date: "2021-07-01",
    clim: [-30, 40], colormap: "thermal", center: [0, 20], zoom: 1 },
];

const MAPS: Record<string, maplibregl.Map> = {};
// Dev aid: save every map canvas as PNG via the dev server (page screenshots do not capture WebGL).
(window as unknown as { __snapshot: () => Promise<string[]> }).__snapshot = async () =>
  Promise.all(Object.entries(MAPS).map(async ([name, m]) => {
    const blob: Blob = await new Promise((r) => m.getCanvas().toBlob((b) => r(b!), "image/png"));
    await fetch(`/__snapshot?name=bakeoff-${name}`, { method: "POST", body: blob });
    return name;
  }));

const BASEMAP = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const log = (msg: string) => {
  const el = document.getElementById("log")!;
  el.textContent += `${new Date().toISOString().slice(11, 19)} ${msg}\n`;
  console.log(msg);
};

type TileData = MinimalTileData & { texture: Texture };

function deckGetTileData(arr: zarr.Array<zarr.DataType, zarr.Readable>, other?: zarr.Array<zarr.DataType, zarr.Readable>) {
  return async (a: zarr.Array<zarr.DataType, zarr.Readable>, o: GetTileDataOptions): Promise<TileData> => {
    const chunk = await zarr.get(a, o.sliceSpec, { signal: o.signal });
    let data = cfDecode(chunk.data as ArrayLike<number>, a.attrs as Record<string, unknown>);
    if (other) {
      const b = await zarr.get(other, o.sliceSpec, { signal: o.signal });
      const bd = cfDecode(b.data as ArrayLike<number>, other.attrs as Record<string, unknown>);
      data = data.map((v, i) => v - bd[i]!);
    }
    const [h, w] = chunk.shape.slice(-2) as [number, number];
    const texture = o.device.createTexture({
      format: "r32float", width: w, height: h, data, mipLevels: 1,
      sampler: { minFilter: "nearest", magFilter: "nearest", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
    });
    return { texture, width: w, height: h, byteLength: data.byteLength };
  };
}

function deckRenderTile(colormapTexture: Texture, colormap: keyof typeof COLORMAP_INDEX, clim: [number, number]) {
  return (d: TileData): RenderTileResult => ({
    renderPipeline: [
      { module: CreateTexture, props: { textureName: d.texture } },
      { module: FilterNoDataVal, props: { value: NaN } },
      { module: LinearRescale, props: { rescaleMin: clim[0], rescaleMax: clim[1] } },
      { module: Colormap, props: { colormapTexture, colormapIndex: COLORMAP_INDEX[colormap] } },
    ],
  });
}

async function colormapTexture(device: Device): Promise<Texture> {
  const bytes = new Uint8Array(await (await fetch(colormapsPng)).arrayBuffer());
  return createColormapTexture(device, await decodeColormapSprite(bytes));
}

function makeMap(container: string, c: Case) {
  const map = new maplibregl.Map({ container, style: BASEMAP, center: c.center, zoom: c.zoom, attributionControl: false,
    canvasContextAttributes: { preserveDrawingBuffer: true } });
  map.once("load", () => map.resize()); // the CSS grid may settle after construction
  MAPS[container] = map;
  return map;
}

// Viridis-like ramp for zarr-layer (it takes explicit colors).
const RAMPS: Record<string, string[]> = {
  ylgnbu: ["#ffffd9", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#0c2c84"],
  thermal: ["#042333", "#2c3395", "#744992", "#b15f82", "#eb7958", "#fbb43d", "#e8fa5b"],
};

async function runCase(c: Case) {
  const ds = sources.datasets[c.dataset];
  const url = ds.maps.url;
  const group = await openIcechunkGroup(url, c.group);
  const idx = await dayIndex(group, c.date);
  log(`[${c.id}] ${c.label}: time index ${idx}`);

  // deck.gl-zarr (left)
  const left = makeMap(`${c.id}-deck`, c);
  left.on("load", async () => {
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    left.addControl(overlay);
    const device = await waitForDevice(overlay);
    const cmap = await colormapTexture(device);
    const arr = await zarr.open(group.resolve(c.variable), { kind: "array" });
    const t0 = performance.now();
    overlay.setProps({
      layers: [new DeckZarrLayer({
        // deck.gl-zarr 0.9: `variable` names a multiscale *group*; a single-level array is passed as `node`,
        // with the GeoZarr attributes (stored on our group) as `metadata`.
        id: `${c.id}-deck-layer`, node: arr, metadata: group.attrs, selection: { time: idx },
        getTileData: deckGetTileData(arr), renderTile: deckRenderTile(cmap, c.colormap, c.clim),
        onViewportLoad: () => log(`[${c.id}] deck.gl-zarr: viewport loaded in ${(performance.now() - t0).toFixed(0)} ms`),
      } as never)],
    });
  });

  // @carbonplan/zarr-layer (right)
  const right = makeMap(`${c.id}-carbon`, c);
  right.on("load", async () => {
    const store = await openIcechunk(url);
    const prefixed = { get: (key: string, opts?: unknown) => store.get(`/${c.group}${key}` as never, opts as never),
      getRange: (key: string, range: unknown, opts?: unknown) => store.getRange(`/${c.group}${key}` as never, range as never, opts as never) };
    const t0 = performance.now();
    let reported = false;
    right.addLayer(new CarbonZarrLayer({
      id: `${c.id}-carbon-layer`, store: prefixed as never, variable: c.variable, selector: { time: { selected: idx, type: "index" } },
      clim: c.clim, colormap: RAMPS[c.colormap]!, zarrVersion: 3,
      onLoadingStateChange: (s: { loading: boolean; error?: unknown }) => {
        if (s.error) log(`[${c.id}] zarr-layer error: ${String(s.error)}`);
        if (!s.loading && !reported) {
          reported = true;
          log(`[${c.id}] zarr-layer: loaded in ${(performance.now() - t0).toFixed(0)} ms`);
        }
      },
    } as never) as never);
  });
}

async function runDiff() {
  // ERA5 - MERRA-2 precipitation on the common grid, 2021-07-01 (two separate repos): deck.gl only.
  const a = await openIcechunkGroup(sources.datasets.era5.common.url, sources.datasets.era5.common.group);
  const b = await openIcechunkGroup(sources.datasets.merra2.common.url, sources.datasets.merra2.common.group);
  const idx = await dayIndex(a, "2021-07-01");
  const arrA = await zarr.open(a.resolve("pr"), { kind: "array" });
  const arrB = await zarr.open(b.resolve("pr"), { kind: "array" });
  const map = new maplibregl.Map({ container: "diff-deck", style: BASEMAP, center: [0, 15], zoom: 1, attributionControl: false,
    canvasContextAttributes: { preserveDrawingBuffer: true } });
  MAPS["diff-deck"] = map;
  map.once("load", () => map.resize());
  map.on("load", async () => {
    const overlay = new MapboxOverlay({ interleaved: true, layers: [] });
    map.addControl(overlay);
    const cmap = await colormapTexture(await waitForDevice(overlay));
    const t0 = performance.now();
    overlay.setProps({
      layers: [new DeckZarrLayer({
        id: "diff-layer", node: arrA, metadata: a.attrs, selection: { time: idx },
        getTileData: deckGetTileData(arrA, arrB), renderTile: deckRenderTile(cmap, "brbg", [-20, 20]),
        onViewportLoad: () => log(`[diff] ERA5 - MERRA-2 pr: viewport loaded in ${(performance.now() - t0).toFixed(0)} ms`),
      } as never)],
    });
  });
}

function waitForDevice(overlay: MapboxOverlay): Promise<Device> {
  return new Promise((resolve) => {
    const check = () => {
      const deck = (overlay as unknown as { _deck?: { device?: Device } })._deck;
      if (deck?.device) resolve(deck.device);
      else setTimeout(check, 50);
    };
    check();
  });
}

for (const c of CASES) runCase(c).catch((e) => log(`[${c.id}] ERROR ${e}`));
runDiff().catch((e) => log(`[diff] ERROR ${e}`));
