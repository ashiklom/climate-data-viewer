// Browser read benchmark: per dataset, time to a fully loaded native precipitation map (CONUS view, 2021-07-15)
// and to one 2021 daily point series (New Haven), each in a fresh browser context (empty HTTP cache).
// Requires the dev server (npm run dev). Prints one line per measurement and a JSON summary
// (medians: results/read_benchmark_browser.csv). Map view: CONUS at zoom 3.3, 1400x950.
import { chromium } from "playwright-core";

const DATASETS = ["prism", "chirps", "era5", "era5land", "merra2", "imerg"];
const REPEATS = 2;
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=metal", "--enable-gpu"] });

async function fresh() {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 950 } });
  const page = await ctx.newPage();
  let bytes = 0, requests = 0;
  page.on("response", async (r) => {
    const len = Number(r.headers()["content-length"] ?? 0);
    if (r.url().includes("/data/") || !r.url().startsWith("http://localhost")) { bytes += len; requests += 1; }
  });
  await page.goto((process.env.SITE ?? "http://localhost:5173") + "/");
  await page.waitForFunction(() => /loaded in|error/.test(document.querySelector(".status")?.textContent ?? ""), null, { timeout: 120000 });
  return { ctx, page, net: () => ({ bytes, requests }), reset: () => { bytes = 0; requests = 0; } };
}

const rows = [];
for (const d of DATASETS) {
  for (let k = 0; k < REPEATS; k++) {
    // Map: switch dataset, wait for the layer's onViewportLoad.
    let { ctx, page, net, reset } = await fresh();
    await page.evaluate(() => window.__map.jumpTo({ center: [-97, 39], zoom: 3.3 }));
    await page.locator('input[type="date"]').fill("2021-07-15");
    await page.waitForFunction(() => /loaded in|error/.test(document.querySelector(".status")?.textContent ?? ""));
    if (d === "era5") {  // the default dataset is ERA5: load another first so the switch re-reads
      await page.locator("select").nth(1).selectOption("merra2");
      await page.waitForFunction(() => /loaded in|error/.test(document.querySelector(".status")?.textContent ?? ""));
    }
    reset();
    const t0 = Date.now();
    await page.locator("select").nth(1).selectOption(d);
    await page.waitForFunction(() => /loaded in|error/.test(document.querySelector(".status")?.textContent ?? ""), null, { timeout: 180000 });
    const map = { s: (Date.now() - t0) / 1000, status: await page.locator(".status").textContent(), ...net() };
    await ctx.close();

    // Series: call the site's own pointSeries through Vite's module graph.
    ({ ctx, page, net, reset } = await fresh());
    reset();
    const series = await page.evaluate(async (ds) => {
      const { pointSeries } = await import("/src/lib/series.ts");
      const t0 = performance.now();
      const s = await pointSeries(ds, "pr", -72.93, 41.31, "2021-01-01", "2021-12-31");
      return { s: (performance.now() - t0) / 1000, n: s.values.filter(Number.isFinite).length, source: s.source };
    }, d);
    Object.assign(series, net());
    await ctx.close();
    const row = { dataset: d, repeat: k, map_s: map.s, map_status: map.status, map_mb: map.bytes / 1e6, map_requests: map.requests,
                  series_s: series.s, series_values: series.n, series_mb: series.bytes / 1e6, series_requests: series.requests, series_source: series.source };
    rows.push(row);
    console.log(JSON.stringify(row));
  }
}
await browser.close();
console.log("SUMMARY " + JSON.stringify(rows));
