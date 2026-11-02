# @climate-mirror/pco-wasm

Decode-only [pcodec](https://github.com/pcodec/pcodec) for [zarrita](https://zarrita.dev) in the browser and in
Node. It reads Zarr arrays whose chunks were written with `numcodecs.pcodec`, which is how our PRISM mirror and
Earthmover's ERA5 store are encoded. No other browser decoder for pcodec exists.

- The `pco` crate (1.0.4, pure Rust) is compiled to WebAssembly with `wasm-bindgen`. The build is 154 KB, or
  50 KB gzipped.
- `numcodecs.pcodec` writes each chunk in pco's *standalone* format, so a chunk decodes with one
  `pco::standalone::simple_decompress::<T>` call, where `T` comes from the array's data type.
- Supported data types: float32/64, int16/32/64, uint16/32/64.

```js
import { registerPcodec } from "@climate-mirror/pco-wasm";
registerPcodec(); // once, before zarr.open(); in Node pass { wasm: <bytes of pkg/pco_wasm_bg.wasm> }
```

## Build and test

```bash
npm install
npm run build      # wasm-pack build --release --target web --out-dir pkg   (needs rustup + wasm32 target + wasm-pack)
npm run fixtures   # Python-encoded golden chunks + values read via zarr-python (needs the repo's uv env)
npm test
```

- `tests/golden.test.mjs` decodes 36 fixtures and checks them bit-exactly against numcodecs. The fixtures cover
  every dtype; NaN, inf, constant, empty and single-value chunks; pcodec levels 4, 8 and 12; a harmonized PRISM
  block; and a real chunk from Earthmover's ERA5 store.
- `tests/zarrita.test.mjs` reads end to end through icechunk-js and zarrita: Earthmover ERA5 spatial and temporal
  arrays from S3, plus the local PRISM mirror served over HTTP. It checks the values against zarr-python.

Measured decode speed: one 721×1440 float32 ERA5 map chunk (4.2 MB raw) decodes in 3.6 ms, about 1.2 GB/s on one
thread in Node 24 on an M-series Mac.
