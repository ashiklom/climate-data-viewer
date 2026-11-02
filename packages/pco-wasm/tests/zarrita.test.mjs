// End-to-end: icechunk-js + zarrita + this codec read pcodec chunks from real Icechunk repos,
// and the values match what Python (icechunk + zarr + numcodecs) reads (fixtures/zarrita_expected.json).
import { after, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import * as zarr from "zarrita";
import { IcechunkStore } from "icechunk-js";

import { registerPcodec } from "../js/index.js";
import { serveDirectory } from "./static-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
registerPcodec({ wasm: readFileSync(join(here, "../pkg/pco_wasm_bg.wasm")) });
const expected = JSON.parse(readFileSync(join(here, "fixtures/zarrita_expected.json"), "utf8"));

// "local:<name>" URLs are local mirrors under data/stores, served over HTTP like the Vite dev server does.
const storesDir = join(here, "../../../data/stores");
const { server, port } = await serveDirectory(storesDir);
after(() => server.close());
const resolveUrl = (url) => (url.startsWith("local:") ? `http://127.0.0.1:${port}/${url.slice(6)}` : url);

for (const c of expected) {
  const skip = c.url.startsWith("local:") && !existsSync(join(storesDir, c.url.slice(6)));
  test(`${c.label}`, { skip: skip && "local store not built" }, async () => {
    const t0 = performance.now();
    const store = await IcechunkStore.open(resolveUrl(c.url), { branch: "main" });
    const arr = await zarr.open(store.resolve(c.path), { kind: "array" });
    const sel = c.selection.map((s) => (Array.isArray(s) ? zarr.slice(s[0], s[1]) : s));
    const out = await zarr.get(arr, sel);
    const ms = performance.now() - t0;
    assert.deepEqual(Array.from(out.shape), c.shape);
    const got = Array.from(out.data);
    assert.equal(got.length, c.values.length);
    for (let i = 0; i < got.length; i++) {
      const a = got[i], b = c.values[i];
      assert.ok((Number.isNaN(a) && b === null) || a === b, `value ${i}: ${a} != ${b}`);
    }
    console.log(`  ${c.label}: ${c.shape.join("x")} ${arr.dtype} in ${ms.toFixed(0)} ms`);
  });
}
