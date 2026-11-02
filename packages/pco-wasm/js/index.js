// zarrita codec for "numcodecs.pcodec" (array -> bytes), decoding with the pco crate compiled to WebAssembly.
//
//   import { registerPcodec } from "@climate-mirror/pco-wasm";
//   registerPcodec();                 // browser: fetches pco_wasm_bg.wasm next to this module
//   registerPcodec({ wasm: bytes });  // Node / custom loading: pass the .wasm bytes or a URL
//
// Decode-only: zarr chunks written by numcodecs.pcodec are pco "standalone" files, decoded with
// pco::standalone::simple_decompress for the array's data type.
import { registry } from "zarrita";
import init, { initSync, decode_f32, decode_f64, decode_i16, decode_i32, decode_i64, decode_u16, decode_u32, decode_u64 } from "../pkg/pco_wasm.js";

const DECODERS = {
  float32: decode_f32,
  float64: decode_f64,
  int16: decode_i16,
  int32: decode_i32,
  int64: decode_i64,
  uint16: decode_u16,
  uint32: decode_u32,
  uint64: decode_u64,
};

let ready;

/** Load the WebAssembly module once. `wasm` may be bytes (BufferSource), a URL, or omitted (browser default). */
export function initPcodec(wasm) {
  if (!ready) {
    ready = wasm instanceof ArrayBuffer || ArrayBuffer.isView(wasm)
      ? Promise.resolve(initSync({ module: wasm }))
      : init(wasm === undefined ? undefined : { module_or_path: wasm });
  }
  return ready;
}

function cStrides(shape) {
  const strides = new Array(shape.length);
  let s = 1;
  for (let i = shape.length - 1; i >= 0; i--) {
    strides[i] = s;
    s *= shape[i];
  }
  return strides;
}

export class PcodecCodec {
  kind = "array_to_bytes";
  #decode;
  #shape;

  constructor(_configuration, meta) {
    this.#decode = DECODERS[meta.dataType];
    if (!this.#decode) throw new Error(`numcodecs.pcodec: unsupported data type ${meta.dataType}`);
    this.#shape = meta.shape;
  }

  static fromConfig(configuration, meta) {
    return new PcodecCodec(configuration, meta);
  }

  encode() {
    throw new Error("numcodecs.pcodec: encoding is not supported (decode-only build)");
  }

  decode(bytes) {
    const data = this.#decode(bytes);
    const n = this.#shape.reduce((a, b) => a * b, 1);
    if (data.length !== n) throw new Error(`numcodecs.pcodec: decoded ${data.length} values, expected ${n}`);
    return { data, shape: this.#shape, stride: cStrides(this.#shape) };
  }
}

/** Register the codec with zarrita's global registry (call once, before opening arrays). */
export function registerPcodec(options = {}) {
  registry.set("numcodecs.pcodec", async () => {
    await initPcodec(options.wasm);
    return PcodecCodec;
  });
}
