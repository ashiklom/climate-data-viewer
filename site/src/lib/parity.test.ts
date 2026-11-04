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
  let derive: typeof import("./derive");
  beforeAll(async () => {
    // Local mirror URLs in sources.json are relative to the dev server.
    (globalThis as { location?: unknown }).location = new URL("http://localhost:5173/");
    data = await import("./data");
    data.registerCodecs({ pcodecWasm: readFileSync(join(import.meta.dirname, "../../../packages/pco-wasm/pkg/pco_wasm_bg.wasm")) });
    mod = await import("./layers");
    derive = await import("./derive");
  });

  const cases: Case[] = enabled ? JSON.parse(readFileSync(FIXTURES, "utf8")) : [];
  it.each(cases)("$dataset $kind $variable $date [$yi, $xi]", async (c) => {
    const src = c.kind === "native"
      ? await mod.nativeSource(c.dataset as never, c.variable, c.date)
      : await mod.commonSource(c.dataset as never, c.variable, c.date);
    const read = async (arr: typeof src.arr) => {
      const chunk = await zarr.get(arr, [src.timeIndex, c.yi, c.xi]);
      const raw = typeof chunk === "object" && chunk !== null && "data" in chunk ? (chunk as { data: ArrayLike<number> }).data : [chunk as number];
      return data.cfDecode(raw as ArrayLike<number>, arr.attrs as Record<string, unknown>);
    };
    // derived variables (Daymet tas, rsds, tdps) combine several native arrays, as getTileData does
    const inputs = await Promise.all([src.arr, ...(src.more ?? [])].map(read));
    const got = src.spec ? derive.combine(src.spec, inputs)[0]! : inputs[0]![0]!;
    expect(got).toBe(Math.fround(c.value));
  }, 120000);
});
