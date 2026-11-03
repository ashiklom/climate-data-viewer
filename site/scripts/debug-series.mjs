// Run pointSeries for each dataset separately in headless Chrome, reporting time and JS heap.
import { chromium } from "playwright-core";
const [variable = "pr", lon = "-72.93", lat = "41.31", only = ""] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=metal", "--enable-precise-memory-info"] });
for (const ds of only ? only.split(",") : ["prism", "chirps", "era5", "era5land", "merra2", "imerg"]) {
  const page = await browser.newPage();
  page.on("crash", () => console.log(`  ${ds}: PAGE CRASHED`));
  await page.goto("http://localhost:5173/");
  await page.waitForFunction(() => window.__pointSeries, null, { timeout: 60000 });
  try {
    const r = await page.evaluate(async ([d, v, x, y]) => {
      const t0 = performance.now();
      try {
        const s = await window.__pointSeries(d, v, Number(x), Number(y), "2021-01-01", "2021-12-31");
        const vals = s.values.filter(Number.isFinite);
        return { ms: Math.round(performance.now() - t0), n: s.values.length, finite: vals.length,
          mean: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null, heapMB: Math.round(performance.memory.usedJSHeapSize / 1e6), source: s.source };
      } catch (e) { return { error: String(e).slice(0, 300), ms: Math.round(performance.now() - t0) }; }
    }, [ds, variable, lon, lat]);
    console.log(ds, JSON.stringify(r));
  } catch (e) { console.log(ds, "evaluate failed:", e.message.split("\n")[0]); }
  await page.close();
}
await browser.close();
