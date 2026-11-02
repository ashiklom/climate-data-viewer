// Python <-> site parity: values read through the site's own path (sources.json -> nativeSource/commonSource ->
// zarrita + icechunk-js + pco-wasm + float32 scale_offset -> cfDecode) must equal xarray's decoded float32 values.
// Needs the dev server (npm run dev) for local mirrors and fixtures from scripts/web/make_parity_fixtures.py.
// Run: PARITY=1 npx vitest run src/lib/parity.test.ts
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import * as zarr from "zarrita";

const FIXTURES = join(import.meta.dirname, "../../test-fixtures/parity.json");
const enabled = process.env.PARITY === "1" && existsSync(FIXTURES);

type Case = { dataset: string; kind: "native" | "common"; variable: string; date: string; yi: number; xi: number; value: number };

describe.runIf(enabled)("python/site parity", () => {
  let mod: typeof import("./layers");
  let data: typeof import("./data");
  beforeAll(async () => {
    // Local mirror URLs in sources.json are relative to the dev server.
    (globalThis as { location?: unknown }).location = new URL("http://localhost:5173/");
    data = await import("./data");
    data.registerCodecs({ pcodecWasm: readFileSync(join(import.meta.dirname, "../../../packages/pco-wasm/pkg/pco_wasm_bg.wasm")) });
    mod = await import("./layers");
  });

  const cases: Case[] = enabled ? JSON.parse(readFileSync(FIXTURES, "utf8")) : [];
  it.each(cases)("$dataset $kind $variable $date [$yi, $xi]", async (c) => {
    const src = c.kind === "native"
      ? await mod.nativeSource(c.dataset as never, c.variable, c.date)
      : await mod.commonSource(c.dataset as never, c.variable, c.date);
    const chunk = await zarr.get(src.arr, [src.timeIndex, c.yi, c.xi]);
    const raw = typeof chunk === "object" && chunk !== null && "data" in chunk ? (chunk as { data: ArrayLike<number> }).data : [chunk as number];
    const got = data.cfDecode(raw as ArrayLike<number>, src.arr.attrs as Record<string, unknown>)[0]!;
    expect(got).toBe(Math.fround(c.value));
  }, 120000);
});
