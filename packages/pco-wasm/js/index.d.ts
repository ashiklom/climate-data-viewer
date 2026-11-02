/** Load the WebAssembly module once (bytes, URL, or the default location next to the module). */
export function initPcodec(wasm?: BufferSource | URL | string): Promise<unknown>;

/** zarrita array->bytes codec for "numcodecs.pcodec" (decode only). */
export declare class PcodecCodec {
  kind: "array_to_bytes";
  constructor(configuration: unknown, meta: { dataType: string; shape: number[] });
  static fromConfig(configuration: unknown, meta: { dataType: string; shape: number[] }): PcodecCodec;
  encode(): never;
  decode(bytes: Uint8Array): { data: ArrayLike<number>; shape: number[]; stride: number[] };
}

/** Register the codec with zarrita's global registry; call once before opening arrays. */
export function registerPcodec(options?: { wasm?: BufferSource | URL | string }): void;
