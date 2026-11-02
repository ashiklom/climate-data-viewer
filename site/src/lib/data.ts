// Data access shared by the site: codec registration, opening Icechunk / Zarr v2 stores, CF decoding,
// and date -> index lookup. Store locations come from src/generated/sources.json (scripts/web/write_sources.py).
import { registerPcodec } from "@climate-mirror/pco-wasm";
import { IcechunkStore } from "icechunk-js";
import * as zarr from "zarrita";

import sources from "../generated/sources.json";

export { sources };
export type Sources = typeof sources;
export type DatasetName = keyof Sources["datasets"];

// zarrita translates v2 numcodecs `fixedscaleoffset` filters (NASA POWER) into the v3 `scale_offset` codec, but its
// decode computes in float64. The scale_offset spec (and numcodecs) evaluate in the array's data type, i.e. float32:
//   dec = float32(float32(enc / scale) + offset)
// With POWER's offset of 1000 the difference is up to ~6e-5. This override is spec-conformant for float32 and defers
// to zarrita's codec for other types, so the site matches Python readers bit-for-bit.
type CodecFactory = { fromConfig(config: { scale?: number; offset?: number }, meta: { dataType: string }): unknown };

function scaleOffsetFloat32Aware(original: () => Promise<unknown>) {
  return async () => {
    const base = (await original()) as CodecFactory;
    return {
      fromConfig(config: { scale?: number; offset?: number }, meta: { dataType: string }) {
        if (meta.dataType !== "float32") return base.fromConfig(config, meta);
        const scale = Math.fround(config.scale ?? 1), offset = Math.fround(config.offset ?? 0);
        return {
          kind: "array_to_array" as const,
          encode(): never {
            throw new Error("scale_offset: encode not supported");
          },
          decode(chunk: zarr.Chunk<"float32">) {
            const src = chunk.data, out = new Float32Array(src.length), f = Math.fround;
            for (let i = 0; i < src.length; i++) out[i] = f(f(src[i]! / scale) + offset);
            return { ...chunk, data: out };
          },
        };
      },
    };
  };
}

let registered = false;
/** Register custom codecs once. In Node (tests), pass the pcodec .wasm bytes. */
export function registerCodecs(options: { pcodecWasm?: BufferSource } = {}) {
  if (registered) return;
  registered = true;
  registerPcodec(options.pcodecWasm ? { wasm: options.pcodecWasm } : {});
  const original = zarr.registry.get("scale_offset")!; // capture zarrita's codec before overriding
  zarr.registry.set("scale_offset", scaleOffsetFloat32Aware(original) as never);
}

const icechunkCache = new Map<string, Promise<IcechunkStore>>();
export function openIcechunk(url: string): Promise<IcechunkStore> {
  const abs = new URL(url, typeof location === "undefined" ? undefined : location.href).href;
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

const UNIT_MS: Record<string, number> = { seconds: 1000, minutes: 60000, hours: 3600000, days: 86400000 };

export type TimeAxis = { originMs: number; unitMs: number; first: number; step: number; length: number };

/** Read a regular CF time coordinate ("<unit> since <date>") as origin, first value and step. */
export async function timeAxis(group: zarr.Group<zarr.Readable>, name = "time"): Promise<TimeAxis> {
  const t = await zarr.open(group.resolve(name), { kind: "array" });
  const units = String((t.attrs as Record<string, unknown>).units ?? "");
  const m = /^(\w+) since (\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2})?))?/.exec(units);
  if (!m || !UNIT_MS[m[1]!]) throw new Error(`unsupported time units: ${units}`);
  const two = await zarr.get(t, [zarr.slice(0, 2)]);
  const [a, b] = Array.from(two.data as ArrayLike<number | bigint>, Number);
  return {
    originMs: Date.parse(`${m[2]}T${m[3] ?? "00:00"}Z`), unitMs: UNIT_MS[m[1]!]!,
    first: a!, step: b! - a!, length: t.shape[0]!,
  };
}

/** Index on a regular time axis of the instant `iso` (e.g. "2021-07-01" = its 00:00 UTC). */
export function indexOf(ax: TimeAxis, iso: string): number {
  const v = (Date.parse(iso.length === 10 ? `${iso}T00:00Z` : iso) - ax.originMs) / ax.unitMs;
  return Math.round((v - ax.first) / ax.step);
}

/** Index of `date` (YYYY-MM-DD) on a contiguous daily `time` coordinate. */
export async function dayIndex(group: zarr.Group<zarr.Readable>, date: string, timeName = "time"): Promise<number> {
  return indexOf(await timeAxis(group, timeName), date);
}
