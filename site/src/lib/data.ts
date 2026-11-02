// Data access shared by the site: codec registration, opening Icechunk / Zarr v2 stores, CF decoding,
// and date -> index lookup. Store locations come from src/generated/sources.json (scripts/web/write_sources.py).
import { registerPcodec } from "@climate-mirror/pco-wasm";
import { IcechunkStore } from "icechunk-js";
import * as zarr from "zarrita";

import sources from "../generated/sources.json";

export { sources };
export type Sources = typeof sources;
export type DatasetName = keyof Sources["datasets"];

// numcodecs.fixedscaleoffset (NASA POWER): stored = round((x - offset) * scale) as `astype`; decode = stored / scale + offset.
class FixedScaleOffset {
  kind = "array_to_array" as const;
  #scale: number;
  #offset: number;
  constructor(config: { scale: number; offset: number }) {
    this.#scale = config.scale;
    this.#offset = config.offset;
  }
  static fromConfig(config: { scale: number; offset: number }) {
    return new FixedScaleOffset(config);
  }
  encode(): never {
    throw new Error("fixedscaleoffset: encode not supported");
  }
  decode(chunk: zarr.Chunk<zarr.DataType>) {
    const src = chunk.data as Float32Array;
    const out = new Float32Array(src.length);
    for (let i = 0; i < src.length; i++) out[i] = src[i]! / this.#scale + this.#offset;
    return { ...chunk, data: out };
  }
}

let registered = false;
export function registerCodecs() {
  if (registered) return;
  registered = true;
  registerPcodec();
  zarr.registry.set("fixedscaleoffset", async () => FixedScaleOffset as never);
}

const icechunkCache = new Map<string, Promise<IcechunkStore>>();
export function openIcechunk(url: string): Promise<IcechunkStore> {
  const abs = new URL(url, location.href).href;
  if (!icechunkCache.has(abs)) icechunkCache.set(abs, IcechunkStore.open(abs, { branch: "main" }));
  return icechunkCache.get(abs)!;
}

export async function openIcechunkGroup(url: string, group: string) {
  const store = await openIcechunk(url);
  return zarr.open(store.resolve(group ? `/${group}` : "/"), { kind: "group" });
}

export async function openZarr2Group(url: string, headers?: Record<string, string>) {
  const fetchStore = new zarr.FetchStore(url, headers ? { overrides: { headers } } : undefined);
  const store = await zarr.withConsolidatedMetadata(fetchStore, { format: "v2" });
  return zarr.open.v2(store, { kind: "group" });
}

/** CF decoding of a raw chunk (scale_factor / add_offset / _FillValue) into float32 with NaN for missing. */
export function cfDecode(data: ArrayLike<number>, attrs: Record<string, unknown>): Float32Array {
  const scale = typeof attrs.scale_factor === "number" ? attrs.scale_factor : 1;
  const offset = typeof attrs.add_offset === "number" ? attrs.add_offset : 0;
  const fill = typeof attrs._FillValue === "number" ? attrs._FillValue : undefined;
  const out = new Float32Array(data.length);
  for (let i = 0; i < data.length; i++) {
    const v = data[i]!;
    out[i] = v === fill ? NaN : v * scale + offset;
  }
  return out;
}

/** Index of `date` (YYYY-MM-DD) on a contiguous daily `time` coordinate ("days since ..." units). */
export async function dayIndex(group: zarr.Group<zarr.Readable>, date: string, timeName = "time"): Promise<number> {
  const t = await zarr.open(group.resolve(timeName), { kind: "array" });
  const units = String((t.attrs as Record<string, unknown>).units ?? "");
  const m = /days since (\d{4}-\d{2}-\d{2})/.exec(units);
  if (!m) throw new Error(`unsupported time units: ${units}`);
  const first = (await zarr.get(t, [0])) as unknown as number | bigint;
  const days = (Date.parse(date) - Date.parse(m[1]!)) / 86400000;
  return days - Number(first);
}
