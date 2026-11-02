// Golden tests: every fixture written by make_fixtures.py must decode bit-exactly.
// Run: node --test packages/pco-wasm/tests/   (after `wasm-pack build --target web --out-dir pkg`)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { initSync, decode_f32, decode_f64, decode_u16, decode_i16, decode_u32, decode_i32 } from "../pkg/pco_wasm.js";

const here = dirname(fileURLToPath(import.meta.url));
initSync({ module: readFileSync(join(here, "../pkg/pco_wasm_bg.wasm")) });

const DECODERS = { float32: decode_f32, float64: decode_f64, uint16: decode_u16, int16: decode_i16, uint32: decode_u32, int32: decode_i32 };
const fixtures = JSON.parse(readFileSync(join(here, "fixtures/index.json"), "utf8"));

for (const { name, dtype, n } of fixtures) {
  test(`${name} (${dtype})`, () => {
    const encoded = readFileSync(join(here, `fixtures/${name}.pco`));
    const expected = readFileSync(join(here, `fixtures/${name}.raw`));
    const decoded = DECODERS[dtype](encoded);
    assert.equal(decoded.length, n);
    const got = Buffer.from(decoded.buffer, decoded.byteOffset, decoded.byteLength);
    assert.ok(got.equals(expected), "decoded bytes differ from numcodecs.pcodec");
  });
}

test("rejects corrupt input with an error, not a crash", () => {
  assert.throws(() => decode_f32(new Uint8Array([1, 2, 3, 4, 5])), /pcodec decode failed/);
});

test("decode throughput (ERA5 map chunk)", () => {
  const encoded = readFileSync(join(here, "fixtures/era5_t2m_spatial_chunk.pco"));
  const reps = 20;
  const t0 = performance.now();
  for (let i = 0; i < reps; i++) decode_f32(encoded);
  const ms = (performance.now() - t0) / reps;
  const mb = (721 * 1440 * 4) / 1e6;
  console.log(`  ERA5 721x1440 float32 chunk: ${ms.toFixed(1)} ms/decode = ${(mb / (ms / 1000)).toFixed(0)} MB/s (single thread)`);
});
