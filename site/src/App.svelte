<script lang="ts">
  import { MapboxOverlay } from "@deck.gl/mapbox";
  import { createColormapTexture, decodeColormapSprite, COLORMAP_INDEX } from "@developmentseed/deck.gl-raster/gpu-modules";
  import colormapsPng from "@developmentseed/deck.gl-raster/gpu-modules/colormaps.png";
  import type { Device, Texture } from "@luma.gl/core";
  import * as Plot from "@observablehq/plot";
  import maplibregl from "maplibre-gl";
  import "maplibre-gl/dist/maplibre-gl.css";
  import { onMount, untrack } from "svelte";

  import { registerCodecs, sources, type DatasetName } from "./lib/data";
  import { commonSource, makeLayer, nativeSource, type Style } from "./lib/layers";
  import { boxMeans as computeBoxMeans, pointSeries, type BoxMean, type Series } from "./lib/series";
  import { DISPLAY, RATIO_RANGE } from "./lib/vars";

  registerCodecs();

  const DATASETS = Object.keys(sources.datasets) as DatasetName[];
  const VARIABLES = Object.keys(sources.canonical);
  const [PERIOD_START, PERIOD_END] = sources.prototype_period;
  // OpenStreetMap raster tiles (tile.openstreetmap.org: fine for a local prototype; a public site needs its own
  // tile provider per the OSM tile usage policy).
  const BASEMAP: maplibregl.StyleSpecification = {
    version: 8,
    sources: {
      osm: {
        type: "raster", tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, maxzoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
  // Natural Earth 1:10m lines (scripts/web/make_overlays.py), drawn above the data layer.
  const OVERLAYS = [
    { id: "coastline", label: "Coastlines", color: "#1d3557", width: 0.9 },
    { id: "countries", label: "National borders", color: "#111", width: 1.1 },
    { id: "states", label: "US state borders", color: "#444", width: 0.7 },
  ] as const;
  const COLORS = ["#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951", "#a463f2"];

  type Mode = "native" | "diff" | "ratio";
  let variable = $state("pr");
  let date = $state("2021-07-01");
  let mode = $state<Mode>("native");
  let datasetA = $state<DatasetName>("era5");
  let datasetB = $state<DatasetName>("merra2");
  let status = $state("");
  let point = $state<{ lon: number; lat: number } | null>(null);
  let series = $state<Series[]>([]);
  let seriesStatus = $state("");
  let boxMeans = $state<BoxMean[]>([]);
  let sharedCells = $state(0);
  let transparency = $state(0); // percent; 0 = opaque data layer
  let overlaysOn = $state<Record<string, boolean>>({ coastline: true, countries: true, states: true });

  let mapEl: HTMLDivElement;
  let chartEl: HTMLDivElement;
  let legendEl: HTMLCanvasElement;
  let map: maplibregl.Map;
  let overlay: MapboxOverlay;
  let colormapImage: ImageData;
  let colormapTexture: Texture | null = null;
  let dataLayer: ReturnType<typeof makeLayer> | null = null;

  const available = $derived(DATASETS.filter((d) => (sources.datasets[d].variables as string[]).includes(variable)));
  const canonical = $derived(sources.canonical[variable as keyof typeof sources.canonical]);
  const dayOfYear = $derived(Math.round((Date.parse(date) - Date.parse(PERIOD_START)) / 86400000));

  $effect(() => {
    // keep dataset choices valid for the variable; ratio maps only make sense for precipitation
    if (!available.includes(datasetA)) datasetA = available[0]!;
    if (!available.includes(datasetB) || datasetB === datasetA) datasetB = available.find((d) => d !== datasetA) ?? available[0]!;
    if (mode === "ratio" && variable !== "pr") mode = "diff";
  });

  function style(): Style {
    const d = DISPLAY[variable]!;
    if (mode === "native") return { clim: d.clim, cmap: d.cmap, reversed: d.reversed };
    if (mode === "ratio") return { clim: RATIO_RANGE, cmap: "brbg" };
    return { clim: [-d.diff, d.diff], cmap: d.diffCmap, reversed: d.diffReversed };
  }

  function drawLegend(s: Style) {
    if (!legendEl || !colormapImage) return;
    const ctx = legendEl.getContext("2d")!;
    const row = COLORMAP_INDEX[s.cmap];
    const w = colormapImage.width;
    for (let x = 0; x < legendEl.width; x++) {
      let src = Math.floor((x / legendEl.width) * w);
      if (s.reversed) src = w - 1 - src;
      const i = (row * w + src) * 4;
      const p = colormapImage.data;
      ctx.fillStyle = `rgb(${p[i]},${p[i + 1]},${p[i + 2]})`;
      ctx.fillRect(x, 0, 1, legendEl.height);
    }
  }

  let renderToken = 0;
  async function updateLayer() {
    if (!overlay || !colormapTexture) return;
    const token = ++renderToken;
    const s = style();
    drawLegend(s);
    status = "loading…";
    const t0 = performance.now();
    try {
      let layer;
      const id = `${mode}-${datasetA}-${datasetB}-${variable}-${date}`;
      const onLoad = () => { if (token === renderToken) status = `loaded in ${((performance.now() - t0) / 1000).toFixed(1)} s`; };
      if (mode === "native") {
        layer = makeLayer(id, await nativeSource(datasetA, variable, date), s, colormapTexture, { onLoad });
      } else {
        const [a, b] = await Promise.all([commonSource(datasetA, variable, date), commonSource(datasetB, variable, date)]);
        layer = makeLayer(id, a, s, colormapTexture, { b, op: mode, onLoad });
      }
      if (token === renderToken) { dataLayer = layer; showDataLayer(); }
    } catch (e) {
      status = `error: ${e instanceof Error ? e.message : e}`;
      console.error(e);
    }
  }

  function showDataLayer() {
    // below the overlay lines; opacity changes keep the layer (and its loaded tiles)
    if (overlay && dataLayer) overlay.setProps({ layers: [dataLayer.clone({ opacity: 1 - transparency / 100, beforeId: `overlay-${OVERLAYS[0].id}` } as never)] });
  }

  async function loadSeries(lon: number, lat: number) {
    point = { lon, lat };
    seriesStatus = "loading series…";
    const t0 = performance.now();
    const withSeries = DATASETS.filter((d) => (sources.datasets[d].series_variables as string[]).includes(variable));
    const results = await Promise.allSettled(withSeries.map((d) => pointSeries(d, variable, lon, lat, PERIOD_START, PERIOD_END)));
    series = results.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    const failed = results.flatMap((r, i) => (r.status === "rejected" ? [`${withSeries[i]}: ${r.reason}`] : []));
    seriesStatus = `${series.length} series in ${((performance.now() - t0) / 1000).toFixed(1)} s` + (failed.length ? ` — failed: ${failed.join("; ")}` : "");
    drawChart();
  }

  function drawChart() {
    if (!chartEl) return;
    chartEl.replaceChildren();
    if (!series.length) return;
    const rows = series.flatMap((s) => s.dates.map((d, i) => ({ dataset: s.dataset, date: new Date(d), value: s.values[i] }))
      .filter((r) => Number.isFinite(r.value)));
    chartEl.append(Plot.plot({
      width: chartEl.clientWidth || 800, height: 240, marginLeft: 50,
      y: { label: `${canonical.long_name} (${canonical.units})`, grid: true },
      x: { label: null },
      color: { legend: true, domain: series.map((s) => s.dataset), range: COLORS },
      marks: [
        Plot.lineY(rows, { x: "date", y: "value", stroke: "dataset", strokeWidth: 1.2 }),
        Plot.ruleX([new Date(date)], { stroke: "#888", strokeDasharray: "3,3" }),
      ],
    }));
  }

  function addOverlays() {
    for (const o of OVERLAYS) {
      map.addSource(`overlay-${o.id}`, { type: "geojson", data: `${import.meta.env.BASE_URL}overlays/${o.id}.geojson` });
      map.addLayer({
        id: `overlay-${o.id}`, type: "line", source: `overlay-${o.id}`,
        layout: { visibility: overlaysOn[o.id] ? "visible" : "none", "line-join": "round" },
        paint: { "line-color": o.color, "line-width": o.width, "line-opacity": 0.85 },
      });
    }
  }

  const fmt = (v: number) => (Number.isFinite(v) ? v.toFixed(2) : "—");

  async function meansOverView() {
    const b = map.getBounds();
    const box: [number, number, number, number] = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    ({ means: boxMeans, sharedCells } = await computeBoxMeans(available, variable, date, box));
  }

  onMount(() => {
    map = new maplibregl.Map({ container: mapEl, style: BASEMAP, center: [-30, 20], zoom: 1.3,
      canvasContextAttributes: { preserveDrawingBuffer: true } });
    Object.assign(window as object, { __map: map, __pointSeries: pointSeries }); // automation/debug hooks
    map.on("load", async () => {
      overlay = new MapboxOverlay({ interleaved: true, layers: [] });
      map.addControl(overlay);
      addOverlays();
      const bytes = new Uint8Array(await (await fetch(colormapsPng)).arrayBuffer());
      colormapImage = await decodeColormapSprite(bytes);
      const device = await new Promise<Device>((resolve) => {
        const check = () => {
          const deck = (overlay as unknown as { _deck?: { device?: Device } })._deck;
          if (deck?.device) resolve(deck.device); else setTimeout(check, 50);
        };
        check();
      });
      colormapTexture = createColormapTexture(device, colormapImage);
      updateLayer();
    });
    map.on("click", (e) => loadSeries(e.lngLat.lng, e.lngLat.lat));
  });

  $effect(() => {
    // re-render when any map control changes
    void [variable, date, mode, datasetA, datasetB];
    updateLayer();
  });
  $effect(() => {
    void transparency;
    untrack(showDataLayer);
  });
  $effect(() => {
    const on = { ...overlaysOn };
    if (!map?.loaded()) return;
    for (const o of OVERLAYS) if (map.getLayer(`overlay-${o.id}`)) map.setLayoutProperty(`overlay-${o.id}`, "visibility", on[o.id] ? "visible" : "none");
  });
  $effect(() => {
    // reload series when the variable changes; `point` is read untracked because loadSeries assigns it
    void [variable];
    const p = untrack(() => point);
    if (p) untrack(() => loadSeries(p.lon, p.lat));
  });
</script>

<div class="app">
  <aside>
    <h1>Daily climate data comparison</h1>
    <p class="sub">Prototype · {PERIOD_START} – {PERIOD_END}</p>

    <label>Variable
      <select bind:value={variable}>
        {#each VARIABLES as v}<option value={v}>{sources.canonical[v as keyof typeof sources.canonical].long_name} ({v})</option>{/each}
      </select>
    </label>

    <label>Date <input type="date" bind:value={date} min={PERIOD_START} max={PERIOD_END} /></label>
    <input type="range" min="0" max="364" value={dayOfYear}
      oninput={(e) => (date = new Date(Date.parse(PERIOD_START) + Number(e.currentTarget.value) * 86400000).toISOString().slice(0, 10))} />

    <fieldset>
      <legend>Map</legend>
      <label><input type="radio" bind:group={mode} value="native" /> Native grid</label>
      <label><input type="radio" bind:group={mode} value="diff" /> A − B (common 0.25° grid)</label>
      <label class:disabled={variable !== "pr"}><input type="radio" bind:group={mode} value="ratio" disabled={variable !== "pr"} /> log₂(A / B) (precipitation, wet cells)</label>
    </fieldset>

    <label>Dataset {mode === "native" ? "" : "A"}
      <select bind:value={datasetA}>{#each available as d}<option value={d}>{sources.datasets[d].label}</option>{/each}</select>
    </label>
    {#if mode !== "native"}
      <label>Dataset B
        <select bind:value={datasetB}>{#each available.filter((d) => d !== datasetA) as d}<option value={d}>{sources.datasets[d].label}</option>{/each}</select>
      </label>
    {/if}

    <div class="legend">
      <canvas bind:this={legendEl} width="240" height="12"></canvas>
      <div class="ticks"><span>{style().clim[0]}</span><span>{mode === "ratio" ? "log₂(A/B)" : canonical.units}</span><span>{style().clim[1]}</span></div>
    </div>
    <p class="status">{status}</p>

    <label>Data layer transparency: {transparency}%
      <input type="range" min="0" max="100" step="5" bind:value={transparency} />
    </label>
    <fieldset>
      <legend>Overlays</legend>
      {#each OVERLAYS as o}<label><input type="checkbox" bind:checked={overlaysOn[o.id]} /> {o.label}</label>{/each}
    </fieldset>

    <button onclick={meansOverView}>Area means over current view</button>
    {#if boxMeans.length}
      <table>
        <thead><tr><th></th><th>shared cells</th><th>own cells</th></tr></thead>
        <tbody>
          {#each boxMeans as m}<tr><td>{sources.datasets[m.dataset].label}</td><td>{fmt(m.shared)}</td><td class="own">{fmt(m.own)} <small>({m.ownCells})</small></td></tr>{/each}
        </tbody>
      </table>
      <p class="note">Common 0.25° grid, cos(lat)-weighted, {date}, {canonical.units}. "Shared cells": only the
        {sharedCells} cells every listed dataset covers (compare these). "Own cells": each dataset's full coverage
        in the view, which mixes land-only and global grids.</p>
    {/if}

    <details>
      <summary>Caveats</summary>
      <ul>
        {#each available as d}<li><b>{d}</b>: day = {sources.datasets[d].day_window}</li>{/each}
        {#if canonical.comparable_note}<li>{canonical.comparable_note}</li>{/if}
        <li>CHIRPS daily values are CHIRPS pentad totals split into days with ERA5: daily CHIRPS vs ERA5/ERA5-Land comparisons are partly circular; compare over ≥5 days.</li>
        <li>CHIRPS (dynamical.org) values are bit-rounded to 8 mantissa bits (≤0.2% relative).</li>
        <li>PRISM covers CONUS only; its day ends at 12 UTC.</li>
        <li>A − B and A / B use conservative regridding to the ERA5 0.25° grid; cells more than half missing are blank.</li>
      </ul>
    </details>
  </aside>

  <main>
    <div class="map" bind:this={mapEl}></div>
    <section class="series">
      {#if point}
        <h2>{canonical.long_name} at {point.lat.toFixed(2)}°, {point.lon.toFixed(2)}° <small>{seriesStatus}</small></h2>
      {:else}
        <h2>Click the map for daily time series of every dataset</h2>
      {/if}
      <div bind:this={chartEl}></div>
    </section>
  </main>
</div>

<style>
  :global(body) { margin: 0; font-family: system-ui, sans-serif; font-size: 14px; color: #222; }
  .app { display: grid; grid-template-columns: 300px 1fr; height: 100vh; }
  aside { padding: 12px; overflow: auto; border-right: 1px solid #ddd; display: flex; flex-direction: column; gap: 8px; }
  h1 { font-size: 17px; margin: 0; }
  .sub, .note { color: #666; margin: 0; font-size: 12px; }
  label { display: flex; flex-direction: column; gap: 2px; }
  fieldset label { flex-direction: row; gap: 6px; }
  .disabled { color: #aaa; }
  main { display: grid; grid-template-rows: 1fr 300px; min-width: 0; }
  .map { min-height: 0; }
  .series { padding: 8px 12px; border-top: 1px solid #ddd; overflow: hidden; }
  .series h2 { font-size: 14px; margin: 0 0 4px; }
  .series small { color: #666; font-weight: normal; }
  .legend canvas { width: 100%; height: 12px; display: block; }
  .ticks { display: flex; justify-content: space-between; font-size: 12px; color: #444; }
  .status { font-size: 12px; color: #666; margin: 0; }
  table { font-size: 12px; border-collapse: collapse; }
  td { padding: 1px 6px; border-bottom: 1px solid #eee; }
  th { padding: 1px 6px; font-weight: 500; color: #666; text-align: left; }
  td.own { color: #888; white-space: nowrap; }
  details { font-size: 12px; }
</style>
