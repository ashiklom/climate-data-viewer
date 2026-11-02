// End-to-end check of the comparison site in headless system Chrome (WebGL via ANGLE/Metal).
// Requires the dev server (npm run dev). Writes screenshots to ../data/logs/snapshots/e2e-*.png and
// fails (exit 1) on page errors or a step that does not finish.
import { chromium } from "playwright-core";

const OUT = "../data/logs/snapshots";
const browser = await chromium.launch({ channel: "chrome", headless: true, args: ["--use-angle=metal", "--enable-gpu"] });
const page = await browser.newPage({ viewport: { width: 1400, height: 950 } });
const problems = [];
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text().slice(0, 300)}`); });
page.on("crash", () => console.log("PAGE CRASHED"));

async function waitText(selector, re, timeout = 120000) {
  const t0 = Date.now();
  await page.waitForFunction(([s, r]) => new RegExp(r).test(document.querySelector(s)?.textContent ?? ""), [selector, re.source], { timeout });
  return ((Date.now() - t0) / 1000).toFixed(1);
}
async function step(name, fn) {
  try {
    const info = await fn();
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${OUT}/e2e-${name}.png` });
    console.log(`ok   ${name}${info ? ` (${info})` : ""}`);
  } catch (e) {
    problems.push(`${name}: ${e.message.split("\n")[0]}`);
    await page.screenshot({ path: `${OUT}/e2e-${name}-FAILED.png` });
    console.log(`FAIL ${name}: ${e.message.split("\n")[0]}`);
  }
}
const status = () => page.locator(".status").textContent();

await page.goto("http://localhost:5173/");
await step("native-era5-pr", async () => `${await waitText(".status", /loaded in|error/)} s; ${await status()}`);

await step("series-new-haven", async () => {
  const xy = await page.evaluate(() => window.__map.project([-72.93, 41.31]));
  const box = await page.locator(".map").boundingBox();
  await page.mouse.click(box.x + xy.x, box.y + xy.y);
  await waitText(".series h2 small", /series in/);
  return await page.locator(".series h2 small").textContent();
});

await step("diff-era5-minus-merra2", async () => {
  await page.locator('input[value="diff"]').check();
  return `${await waitText(".status", /loaded in|error/)} s; ${await status()}`;
});

await step("ratio-era5-over-imerg", async () => {
  await page.locator('input[value="ratio"]').check();
  await page.locator("select").nth(2).selectOption("imerg");
  return `${await waitText(".status", /loaded in|error/)} s; ${await status()}`;
});

await step("native-prism-tas", async () => {
  await page.locator('input[value="native"]').check();
  await page.locator("select").first().selectOption("tas");
  await page.locator("select").nth(1).selectOption("prism");
  await page.locator('input[type="date"]').fill("2021-10-10");
  await page.evaluate(() => window.__map.jumpTo({ center: [-97, 39], zoom: 3.3 }));
  return `${await waitText(".status", /loaded in|error/)} s; ${await status()}`;
});

await step("area-means", async () => {
  await page.getByText("Area means over current view").click();
  await page.waitForSelector("aside table td", { timeout: 60000 });
  return (await page.locator("aside table").innerText()).replace(/\s+/g, " ");
});

await browser.close();
if (problems.length) {
  console.log("\nPROBLEMS:\n" + problems.join("\n"));
  process.exit(1);
}
