// Headless check of a site page with system Chrome (WebGL via ANGLE/Metal): waits for a log line or timeout,
// prints console output, and writes a full-page screenshot.  Usage:
//   node scripts/snapshot.mjs <path> <out.png> [waitMs] [doneRegex]
import { chromium } from "playwright-core";

const [path = "/", out = "snapshot.png", waitMs = "60000", done = ""] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=metal", "--enable-gpu"] });
const page = await browser.newPage({ viewport: { width: 1200, height: 1300 }, deviceScaleFactor: 1 });
const lines = [];
page.on("console", (m) => lines.push(`[${m.type()}] ${m.text()}`));
page.on("pageerror", (e) => lines.push(`[pageerror] ${e.message}`));
await page.goto(`${process.env.SITE ?? "http://localhost:5173"}${path}`);
const t0 = Date.now();
const re = done ? new RegExp(done) : null;
while (Date.now() - t0 < Number(waitMs)) {
  if (re && lines.filter((l) => re.test(l)).length >= 1 && lines.filter((l) => re.test(l)).length >= Number(process.env.DONE_COUNT ?? 1)) break;
  await page.waitForTimeout(500);
}
await page.waitForTimeout(1500);
await page.screenshot({ path: out, fullPage: true });
console.log(lines.filter((l) => !/vite\] connect|lighting|Binding sampler/.test(l)).slice(0, 60).join("\n"));
console.log(`screenshot: ${out} after ${((Date.now() - t0) / 1000).toFixed(1)} s`);
await browser.close();
